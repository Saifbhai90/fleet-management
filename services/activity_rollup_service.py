"""Daily rollups over vehicle_activity_record.

Reports that summarise a date range have to touch every GPS point in it, so no
index can help them: grouping 30 days of vehicle_activity_record reads ~900k
rows and spills the sort to disk (measured: 28 s / 79 MB for dwell by location,
23 s / 43 MB for per-vehicle presence). Rolling each day up once turns both into
scans of a few thousand pre-aggregated rows.

Two rollups live here, because both are byproducts of reading the same day:

* ``vehicle_stop_location_daily`` — standing time per (day, vehicle, place),
  for the Stoppage & Dwell report.
* ``vehicle_activity_day_summary`` — points and first/last sighting per
  (day, vehicle), so Device Health can spot units that went quiet.

Two details of the source data drive the dwell implementation:

* ``stop_time`` is the standing time *at that point*, not a running total, so a
  visit's dwell is the sum over its points. It arrives as ``H:MM:SS`` with an
  unpadded hour (``9:58:14``).
* Consecutive points at the same place are one visit, not many. A vehicle
  parked for four minutes emits four points each carrying ``00:01:00``; counting
  rows would report four stops. Visits are therefore found by walking each
  vehicle's day in time order and starting a new visit when the place changes.

The walk is done in Python rather than SQL window functions: a single day is
only ~28k points, and the app also runs on SQLite locally, where the
Postgres-specific interval and regexp functions this would need are absent.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, timedelta

from flask import current_app
from sqlalchemy import func, text

from app import db
from models import (
    VehicleActivityDaySummary,
    VehicleActivityRecord,
    VehicleStopLocationDaily,
    VehicleStopRollupStatus,
)
from utils import clean_geo_location, pk_date, pk_now, strip_ufone_reg_tag

logger = logging.getLogger(__name__)

# Ignore a "stop" this short: at a 1-minute reporting interval these are
# traffic-light pauses and rounding, not dwells worth reporting.
MIN_VISIT_SECONDS = 60

# Cap how long a single web request will spend building missing days, so a wide
# date range degrades into partial coverage instead of a timeout.
BUILD_BUDGET_SECONDS = 20.0

# How long a rollup of the current or previous day is trusted before it is
# rebuilt. Rebuilding costs a full scan of that day's points, so doing it on
# every page load makes each visit several seconds slower for data that has
# barely changed.
ROLLUP_FRESH_SECONDS = 600


def clean_location(raw: str) -> str:
    """Address as stored in the rollup: prefix stripped, cut to the column width.

    3,451,847 of 3,501,569 stored locations carry the ``0||`` prefix; the rest
    are already bare.
    """
    return clean_geo_location(raw)[:200]


def reg_variants(regno: str) -> list:
    """Spellings of one vehicle to match against rollup rows.

    The rollup copies vehicle_no from the activity table, which stores regnos
    tag-stripped (``GBD-24-877``) while the vehicle picker offers them tagged
    (``GBD-24-877 USG``). Filtering on the picker's value alone finds nothing.
    """
    raw = (regno or '').strip()
    if not raw:
        return []
    return list({raw, strip_ufone_reg_tag(raw)} - {''})


def parse_hms(raw: str) -> int:
    """``H:MM:SS`` (hour not zero-padded) to seconds; 0 for anything unparseable."""
    text = (raw or '').strip()
    if not text:
        return 0
    parts = text.split(':')
    if len(parts) != 3:
        return 0
    try:
        hours, minutes, seconds = (int(p) for p in parts)
    except (TypeError, ValueError):
        return 0
    if minutes < 0 or seconds < 0 or hours < 0:
        return 0
    return hours * 3600 + minutes * 60 + seconds


def format_duration(seconds) -> str:
    """Seconds as ``4d 6h`` / ``2h 15m`` / ``45m``.

    Fleet-wide totals reach thousands of hours (ten ambulances parked at one
    hospital for a month), and ``4023h 27m`` is not a number anyone can read, so
    anything past a day is expressed in days.
    """
    total = int(seconds or 0)
    if total <= 0:
        return '0m'
    minutes_total = total // 60
    hours, minutes = divmod(minutes_total, 60)
    if hours >= 24:
        days, rem_hours = divmod(hours, 24)
        return f'{days}d {rem_hours}h' if rem_hours else f'{days}d'
    if hours and minutes:
        return f'{hours}h {minutes}m'
    if hours:
        return f'{hours}h'
    return f'{minutes}m'


def _visits_for_day(day: date) -> tuple:
    """Walk one day's points and fold them into per-(vehicle, place) totals.

    Returns ``(rows, source_points)`` where rows is keyed by
    ``(vehicle_no, location)``.
    """
    points = (
        db.session.query(
            VehicleActivityRecord.vehicle_no,
            VehicleActivityRecord.record_date_time,
            VehicleActivityRecord.location,
            VehicleActivityRecord.stop_time,
            VehicleActivityRecord.latitude,
            VehicleActivityRecord.longitude,
            VehicleActivityRecord.id,
        )
        .filter(
            VehicleActivityRecord.task_date == day,
            VehicleActivityRecord.location.isnot(None),
            VehicleActivityRecord.location != '',
        )
        # record_date_time is an ISO string, so lexical order is time order; id
        # breaks ties so the visit walk is deterministic.
        .order_by(
            VehicleActivityRecord.vehicle_no,
            VehicleActivityRecord.record_date_time,
            VehicleActivityRecord.id,
        )
        .yield_per(5000)
    )

    totals = {}
    source_points = 0
    # State of the visit currently being accumulated.
    cur_key = None
    cur_seconds = 0
    cur_points = 0
    cur_first = None
    cur_last = None
    cur_lat = None
    cur_lon = None

    def flush():
        """Close the open visit and add it to its place's running totals."""
        if cur_key is None:
            return
        if cur_seconds < MIN_VISIT_SECONDS:
            return
        row = totals.setdefault(cur_key, {
            'visits': 0, 'stop_seconds': 0, 'points': 0,
            'longest_visit_seconds': 0,
            'first_seen': cur_first, 'last_seen': cur_last,
            'latitude': cur_lat, 'longitude': cur_lon,
        })
        row['visits'] += 1
        row['stop_seconds'] += cur_seconds
        row['points'] += cur_points
        row['longest_visit_seconds'] = max(row['longest_visit_seconds'], cur_seconds)
        if cur_first and (not row['first_seen'] or cur_first < row['first_seen']):
            row['first_seen'] = cur_first
        if cur_last and (not row['last_seen'] or cur_last > row['last_seen']):
            row['last_seen'] = cur_last
        if row['latitude'] is None and cur_lat is not None:
            row['latitude'] = cur_lat
            row['longitude'] = cur_lon

    for reg, rdt, location, stop_time, lat, lon, _id in points:
        source_points += 1
        place = clean_location(location)
        if not place:
            continue
        key = (reg, place)
        if key != cur_key:
            flush()
            cur_key = key
            cur_seconds = 0
            cur_points = 0
            cur_first = rdt
            cur_lat = lat
            cur_lon = lon
        cur_seconds += parse_hms(stop_time)
        cur_points += 1
        cur_last = rdt
        if cur_lat is None and lat is not None:
            cur_lat = lat
            cur_lon = lon
    flush()

    return totals, source_points


def build_day_summary(day: date) -> int:
    """(Re)build the per-vehicle presence summary for one date. Idempotent."""
    rows = (
        db.session.query(
            VehicleActivityRecord.vehicle_no,
            func.count(VehicleActivityRecord.id),
            func.min(VehicleActivityRecord.record_date_time),
            func.max(VehicleActivityRecord.record_date_time),
        )
        .filter(VehicleActivityRecord.task_date == day)
        .group_by(VehicleActivityRecord.vehicle_no)
        .all()
    )

    VehicleActivityDaySummary.query.filter_by(task_date=day).delete(
        synchronize_session=False)
    if rows:
        db.session.bulk_insert_mappings(VehicleActivityDaySummary, [{
            'task_date': day,
            'vehicle_no': reg,
            'points': int(points or 0),
            'first_seen': first_seen,
            'last_seen': last_seen,
            'built_at': pk_now(),
        } for reg, points, first_seen, last_seen in rows])
    return len(rows)


def build_all_day_summaries() -> int:
    """Backfill every day's presence summary in a single pass.

    One ``GROUP BY (task_date, vehicle_no)`` over the whole table is far cheaper
    than repeating a per-day query 126 times, so the initial backfill uses this
    instead of walking days.
    """
    rows = (
        db.session.query(
            VehicleActivityRecord.task_date,
            VehicleActivityRecord.vehicle_no,
            func.count(VehicleActivityRecord.id),
            func.min(VehicleActivityRecord.record_date_time),
            func.max(VehicleActivityRecord.record_date_time),
        )
        .group_by(VehicleActivityRecord.task_date, VehicleActivityRecord.vehicle_no)
        .all()
    )

    VehicleActivityDaySummary.query.delete(synchronize_session=False)
    if rows:
        now = pk_now()
        db.session.bulk_insert_mappings(VehicleActivityDaySummary, [{
            'task_date': day,
            'vehicle_no': reg,
            'points': int(points or 0),
            'first_seen': first_seen,
            'last_seen': last_seen,
            'built_at': now,
        } for day, reg, points, first_seen, last_seen in rows])
    db.session.commit()
    logger.info('activity day summary rebuilt: %s rows', len(rows))
    return len(rows)


def day_presence(from_date: date, to_date: date) -> dict:
    """Per-vehicle presence over the range, keyed by raw activity vehicle_no."""
    rows = (
        db.session.query(
            VehicleActivityDaySummary.vehicle_no,
            func.sum(VehicleActivityDaySummary.points),
            func.count(VehicleActivityDaySummary.task_date),
            func.max(VehicleActivityDaySummary.last_seen),
        )
        .filter(
            VehicleActivityDaySummary.task_date >= from_date,
            VehicleActivityDaySummary.task_date <= to_date,
        )
        .group_by(VehicleActivityDaySummary.vehicle_no)
        .all()
    )
    return {
        reg: {
            'points': int(points or 0),
            'days': int(days or 0),
            'last_point': last_seen or '',
        }
        for reg, points, days, last_seen in rows
    }


def _claim_day(day: date) -> bool:
    """Claim the exclusive right to rebuild ``day``, for this transaction only.

    Every worker process runs its own refresher, and two of them rebuilding the
    same day would race on the delete-then-insert. The advisory lock is held
    until the build commits or rolls back. SQLite (local dev) has no equivalent
    and only ever runs a single process, so there the claim always succeeds.
    """
    if db.session.get_bind().dialect.name != 'postgresql':
        return True
    got = db.session.execute(
        text('SELECT pg_try_advisory_xact_lock(:key)'),
        {'key': int(day.strftime('%Y%m%d'))},
    ).scalar()
    return bool(got)


def build_day(day: date) -> dict:
    """(Re)build both rollups for one date. Idempotent.

    Returns ``rollup_rows=None`` when another process holds the day.
    """
    if not _claim_day(day):
        logger.info('rollup %s skipped: already being built elsewhere', day)
        return {'date': day, 'source_points': 0, 'rollup_rows': None,
                'vehicles': 0}

    summary_rows = build_day_summary(day)
    totals, source_points = _visits_for_day(day)

    VehicleStopLocationDaily.query.filter_by(task_date=day).delete(
        synchronize_session=False)

    if totals:
        db.session.bulk_insert_mappings(VehicleStopLocationDaily, [{
            'task_date': day,
            'vehicle_no': reg,
            'location': place,
            'visits': agg['visits'],
            'stop_seconds': agg['stop_seconds'],
            'points': agg['points'],
            'longest_visit_seconds': agg['longest_visit_seconds'],
            'first_seen': agg['first_seen'],
            'last_seen': agg['last_seen'],
            'latitude': agg['latitude'],
            'longitude': agg['longitude'],
            'built_at': pk_now(),
        } for (reg, place), agg in totals.items()])

    status = VehicleStopRollupStatus.query.filter_by(task_date=day).first()
    if status is None:
        status = VehicleStopRollupStatus(task_date=day)
        db.session.add(status)
    status.built_at = pk_now()
    status.source_points = source_points
    status.rollup_rows = len(totals)

    db.session.commit()
    logger.info('rollup %s: %s points -> %s stop rows, %s vehicles',
                day, source_points, len(totals), summary_rows)
    return {
        'date': day,
        'source_points': source_points,
        'rollup_rows': len(totals),
        'vehicles': summary_rows,
    }


def _built_days(from_date: date, to_date: date) -> dict:
    """``{task_date: built_at}`` for every day already rolled up in the range."""
    return {
        row.task_date: row.built_at for row in
        VehicleStopRollupStatus.query.filter(
            VehicleStopRollupStatus.task_date >= from_date,
            VehicleStopRollupStatus.task_date <= to_date,
        ).all()
    }


def unbuilt_days(from_date: date, to_date: date) -> list:
    """Dates in the range that have never been rolled up.

    This is what the reader cares about: a day with no rollup is a day missing
    from the report. Today is excluded even when it was rolled up minutes ago,
    which is the difference from ``stale_days``.
    """
    built = _built_days(from_date, to_date)
    days = []
    cursor = from_date
    while cursor <= to_date:
        if cursor not in built:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def stale_days(from_date: date, to_date: date) -> list:
    """Dates worth (re)building: never built, or recent and no longer fresh.

    Points keep arriving for the current day and a late sync can still extend
    the previous one, so those two are eligible for rebuilding. Rebuilding them
    on *every* page load costs ~5 s per day for no new information, so a day
    rolled up within ROLLUP_FRESH_SECONDS is left alone.
    """
    built = _built_days(from_date, to_date)
    today = pk_date()
    refresh_from = today - timedelta(days=1)
    now = pk_now()
    days = []
    cursor = from_date
    while cursor <= to_date:
        built_at = built.get(cursor)
        if built_at is None:
            days.append(cursor)
        elif cursor >= refresh_from:
            age = (now - built_at).total_seconds()
            if age >= ROLLUP_FRESH_SECONDS:
                days.append(cursor)
        cursor += timedelta(days=1)
    return days


def ensure_days(from_date: date, to_date: date,
                budget_seconds: float = BUILD_BUDGET_SECONDS) -> dict:
    """Build whatever days are missing or stale, newest first, within a budget.

    Newest first because a partially built range is far more useful to the
    reader when the recent end is the part that is present.
    """
    pending = sorted(stale_days(from_date, to_date), reverse=True)
    started = time.monotonic()
    built = []
    for day in pending:
        if built and time.monotonic() - started > budget_seconds:
            break
        try:
            build_day(day)
            built.append(day)
        except Exception as exc:
            db.session.rollback()
            logger.warning('dwell rollup build failed for %s: %s', day, exc)
            break
    return {
        'built': built,
        'remaining': [d for d in pending if d not in built],
        'complete': len(built) == len(pending),
    }


_refresh_lock = threading.Lock()


def _refresh_recent(app, from_date: date, to_date: date):
    with app.app_context():
        try:
            ensure_days(from_date, to_date)
        except Exception as exc:
            db.session.rollback()
            logger.warning('background rollup refresh failed: %s', exc)
        finally:
            db.session.remove()
            _refresh_lock.release()


def ensure_for_request(from_date: date, to_date: date) -> dict:
    """Make the range readable without making the reader wait for a refresh.

    Days that were never rolled up are built inline, because a missing day is a
    hole in the report. Refreshing today and yesterday, on the other hand, only
    adds points that arrived in the last few minutes, and costs ~7 s per day —
    so that runs in the background and the request serves the previous rollup.
    """
    missing = unbuilt_days(from_date, to_date)
    result = {'built': [], 'remaining': [], 'complete': True}
    if missing:
        result = ensure_days(min(missing), max(missing))

    if stale_days(from_date, to_date) and _refresh_lock.acquire(blocking=False):
        # Released by _refresh_recent, including on failure.
        threading.Thread(
            target=_refresh_recent,
            args=(current_app._get_current_object(), from_date, to_date),
            daemon=True,
            name='activity-rollup-refresh',
        ).start()
    return result


def dwell_by_location(from_date: date, to_date: date, vehicle_no: str = '',
                      limit: int = 200) -> list:
    """Places the fleet stood still in, longest total dwell first."""
    query = (
        db.session.query(
            VehicleStopLocationDaily.location,
            func.sum(VehicleStopLocationDaily.stop_seconds),
            func.sum(VehicleStopLocationDaily.visits),
            func.count(func.distinct(VehicleStopLocationDaily.vehicle_no)),
            func.max(VehicleStopLocationDaily.longest_visit_seconds),
            func.max(VehicleStopLocationDaily.last_seen),
            func.max(VehicleStopLocationDaily.latitude),
            func.max(VehicleStopLocationDaily.longitude),
        )
        .filter(
            VehicleStopLocationDaily.task_date >= from_date,
            VehicleStopLocationDaily.task_date <= to_date,
        )
        .group_by(VehicleStopLocationDaily.location)
    )
    variants = reg_variants(vehicle_no)
    if variants:
        query = query.filter(VehicleStopLocationDaily.vehicle_no.in_(variants))

    rows = query.order_by(func.sum(VehicleStopLocationDaily.stop_seconds).desc()) \
                .limit(limit).all()

    # SUM() over a bigint column comes back as numeric, i.e. Decimal in Python,
    # which will not divide by a float — coerce before doing any arithmetic.
    out = []
    for location, stop_seconds, visits, vehicles, longest, last_seen, lat, lon in rows:
        total = int(stop_seconds or 0)
        trips = int(visits or 0)
        out.append({
            'location': location,
            'stop_seconds': total,
            'stop_hours': round(total / 3600.0, 1),
            'stop_text': format_duration(total),
            'visits': trips,
            'vehicles': int(vehicles or 0),
            'longest_visit_seconds': int(longest or 0),
            'longest_text': format_duration(longest),
            'avg_visit_seconds': total // trips if trips else 0,
            'avg_visit_text': format_duration(total // trips) if trips else '0m',
            'last_seen': last_seen or '',
            'latitude': float(lat) if lat is not None else None,
            'longitude': float(lon) if lon is not None else None,
        })
    return out


def dwell_by_vehicle(from_date: date, to_date: date, vehicle_no: str = '',
                     limit: int = 200) -> list:
    """Per-vehicle standing time, so the worst offenders are visible directly."""
    query = (
        db.session.query(
            VehicleStopLocationDaily.vehicle_no,
            func.sum(VehicleStopLocationDaily.stop_seconds),
            func.sum(VehicleStopLocationDaily.visits),
            func.count(func.distinct(VehicleStopLocationDaily.location)),
            func.count(func.distinct(VehicleStopLocationDaily.task_date)),
        )
        .filter(
            VehicleStopLocationDaily.task_date >= from_date,
            VehicleStopLocationDaily.task_date <= to_date,
        )
        .group_by(VehicleStopLocationDaily.vehicle_no)
    )
    variants = reg_variants(vehicle_no)
    if variants:
        query = query.filter(VehicleStopLocationDaily.vehicle_no.in_(variants))

    rows = query.order_by(func.sum(VehicleStopLocationDaily.stop_seconds).desc()) \
                .limit(limit).all()

    out = []
    for reg, stop_seconds, visits, places, days in rows:
        total = int(stop_seconds or 0)
        day_count = int(days or 0)
        out.append({
            'vehicle_no': reg,
            'stop_seconds': total,
            'stop_hours': round(total / 3600.0, 1),
            'stop_text': format_duration(total),
            'visits': int(visits or 0),
            'places': int(places or 0),
            'days': day_count,
            'avg_per_day_text': format_duration(total // day_count) if day_count else '0m',
            'avg_hours_per_day': round(total / 3600.0 / day_count, 1) if day_count else 0,
        })
    return out


def top_visit_detail(from_date: date, to_date: date, location: str,
                     limit: int = 100) -> list:
    """Which vehicles dwelled at one place, for the drill-down view."""
    rows = (
        db.session.query(
            VehicleStopLocationDaily.vehicle_no,
            VehicleStopLocationDaily.task_date,
            VehicleStopLocationDaily.visits,
            VehicleStopLocationDaily.stop_seconds,
            VehicleStopLocationDaily.first_seen,
            VehicleStopLocationDaily.last_seen,
        )
        .filter(
            VehicleStopLocationDaily.task_date >= from_date,
            VehicleStopLocationDaily.task_date <= to_date,
            VehicleStopLocationDaily.location == location,
        )
        .order_by(
            VehicleStopLocationDaily.task_date.desc(),
            VehicleStopLocationDaily.stop_seconds.desc(),
        )
        .limit(limit)
        .all()
    )
    return [{
        'vehicle_no': reg,
        'task_date': task_date,
        'visits': int(visits or 0),
        'stop_seconds': int(stop_seconds or 0),
        'stop_hours': round(int(stop_seconds or 0) / 3600.0, 1),
        'stop_text': format_duration(stop_seconds),
        'first_seen': first_seen or '',
        'last_seen': last_seen or '',
    } for reg, task_date, visits, stop_seconds, first_seen, last_seen in rows]


def coverage(from_date: date, to_date: date) -> dict:
    """How much of the requested range the rollup can actually answer.

    Counts only never-built days, so a report covering today does not warn
    about incompleteness merely because today is still accumulating points.
    """
    span = (to_date - from_date).days + 1
    pending = unbuilt_days(from_date, to_date)
    return {
        'days_requested': span,
        'days_missing': len(pending),
        'days_ready': span - len(pending),
        'complete': not pending,
    }
