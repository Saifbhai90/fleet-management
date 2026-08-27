"""Daily snapshots of the PortalXS fleet report, and trends over them.

The fleet report is one SOAP call per vehicle per date range, which is why the
page fetches it in browser-driven batches and holds the result in a 5-minute
memory cache. That makes "how did this vehicle's score move over the month?"
unanswerable: the numbers are gone as soon as the cache expires.

So each day is snapshotted into fleet_score_daily once and read from there
afterwards. Snapshotting a past day costs the same SOAP calls as viewing it, so
history can also be filled in on demand rather than only accumulating forward.
"""
from __future__ import annotations

import logging
import threading
from datetime import date, timedelta

from flask import current_app
from sqlalchemy import func

from app import db
from models import FleetScoreDaily, FleetScoreSyncStatus, PortalXSAccount
from services.portalxs_service import (
    fetch_fleet_report_batch,
    get_all_vehicles_for_account,
)
from utils import pk_date, pk_now, safe_float, strip_ufone_reg_tag

logger = logging.getLogger(__name__)

# Vehicles per SOAP fan-out. The report page uses 8 with an 18 s deadline to
# stay inside a request; a scheduled snapshot has no such limit.
SNAPSHOT_BATCH_SIZE = 12
SNAPSHOT_WORKERS = 8
SNAPSHOT_DEADLINE = 60


def _soap_day(day: date) -> tuple[str, str]:
    return f'{day.isoformat()}T00:00:00', f'{day.isoformat()}T23:59:59'


def snapshot_day(account_id: int, day: date, source: str = 'auto') -> dict:
    """Fetch and store every vehicle's fleet-report row for one day.

    Idempotent: re-running a day updates the rows in place, so a day can be
    refreshed once more data has settled upstream.
    """
    vehicles = get_all_vehicles_for_account(account_id) or []
    regnos = [v['portalxs_regno'] for v in vehicles if v.get('portalxs_regno')]
    names = {
        v['portalxs_regno']: (v.get('vehicle_no') or v['portalxs_regno'])
        for v in vehicles if v.get('portalxs_regno')
    }
    fdt, tdt = _soap_day(day)

    stored = 0
    errors: list[str] = []
    for i in range(0, len(regnos), SNAPSHOT_BATCH_SIZE):
        chunk = regnos[i:i + SNAPSHOT_BATCH_SIZE]
        try:
            result = fetch_fleet_report_batch(
                account_id, chunk, fdt, tdt,
                max_workers=SNAPSHOT_WORKERS, deadline_sec=SNAPSHOT_DEADLINE,
            )
        except Exception as exc:
            db.session.rollback()
            errors.append(str(exc)[:200])
            logger.warning('fleet score batch failed account=%s day=%s: %s',
                           account_id, day, exc)
            continue

        errors.extend(result.get('errors') or [])
        for row in result.get('rows') or []:
            regno = row.get('_regno') or row.get('RegNo') or ''
            if not regno:
                continue
            try:
                _upsert_row(account_id, day, names.get(regno) or regno, row)
                stored += 1
            except Exception as exc:
                db.session.rollback()
                errors.append(f'{regno}: {str(exc)[:120]}')
        db.session.commit()

    _mark_status(account_id, day, source, len(regnos), stored, len(errors))
    logger.info('fleet score snapshot account=%s day=%s stored=%s/%s errors=%s',
                account_id, day, stored, len(regnos), len(errors))
    return {
        'account_id': account_id,
        'task_date': day.isoformat(),
        'vehicles': len(regnos),
        'stored': stored,
        'errors': errors[:10],
        'error_count': len(errors),
    }


def _upsert_row(account_id: int, day: date, vehicle_no: str, row: dict):
    reg = strip_ufone_reg_tag(vehicle_no) or vehicle_no
    rec = FleetScoreDaily.query.filter_by(
        account_id=account_id, task_date=day, reg_no=reg).first()
    if rec is None:
        rec = FleetScoreDaily(account_id=account_id, task_date=day, reg_no=reg)
        db.session.add(rec)
    rec.vehicle_score = safe_float(row.get('VehicleScore'))
    rec.distance = safe_float(row.get('Distance'))
    rec.fuel_consumption = safe_float(row.get('FuelConsumption'))
    rec.trips = int(safe_float(row.get('Trips')))
    rec.duration = int(safe_float(row.get('Duration')))
    rec.alerts = int(safe_float(row.get('Alerts')))
    rec.built_at = pk_now()


def _mark_status(account_id: int, day: date, source: str, total: int,
                 stored: int, error_count: int):
    st = FleetScoreSyncStatus.query.filter_by(
        account_id=account_id, task_date=day).first()
    if st is None:
        st = FleetScoreSyncStatus(account_id=account_id, task_date=day)
        db.session.add(st)
    st.last_synced_at = pk_now()
    st.source = source
    st.vehicles_total = total
    st.fetched_count = stored
    st.error_count = error_count
    db.session.commit()


def snapshot_all_active_accounts(day: date, source: str = 'auto') -> list[dict]:
    results = []
    for acct in PortalXSAccount.query.filter_by(is_active=True).all():
        try:
            results.append(snapshot_day(acct.id, day, source=source))
        except Exception as exc:
            db.session.rollback()
            logger.exception('fleet score snapshot account=%s day=%s failed',
                             acct.id, day)
            results.append({'account_id': acct.id, 'task_date': day.isoformat(),
                            'error': str(exc)[:300]})
    return results


# ── Reading the history ──────────────────────────────────────────────────────

def snapshotted_days(account_id: int, from_date: date, to_date: date) -> set:
    rows = (db.session.query(FleetScoreSyncStatus.task_date)
            .filter(FleetScoreSyncStatus.account_id == account_id,
                    FleetScoreSyncStatus.task_date >= from_date,
                    FleetScoreSyncStatus.task_date <= to_date)
            .all())
    return {r[0] for r in rows}


def missing_days(account_id: int, from_date: date, to_date: date) -> list:
    """Days in the range with no snapshot attempt yet, oldest first.

    Today is included: its snapshot is only ever a partial day, so the caller
    decides whether re-taking it is worth the SOAP calls.
    """
    done = snapshotted_days(account_id, from_date, to_date)
    days, cursor = [], from_date
    while cursor <= to_date:
        if cursor not in done:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def daily_fleet_score(account_id: int, from_date: date, to_date: date) -> list:
    """Fleet-wide averages per day, oldest first — the trend line itself."""
    rows = (
        db.session.query(
            FleetScoreDaily.task_date,
            func.avg(FleetScoreDaily.vehicle_score),
            func.count(FleetScoreDaily.id),
            func.sum(FleetScoreDaily.distance),
            func.sum(FleetScoreDaily.alerts),
            func.sum(FleetScoreDaily.trips),
        )
        .filter(FleetScoreDaily.account_id == account_id,
                FleetScoreDaily.task_date >= from_date,
                FleetScoreDaily.task_date <= to_date)
        .group_by(FleetScoreDaily.task_date)
        .order_by(FleetScoreDaily.task_date)
        .all()
    )
    return [{
        'task_date': day,
        'date_text': day.strftime('%d %b'),
        'avg_score': round(float(avg or 0), 1),
        'vehicles': int(count or 0),
        'distance': round(float(dist or 0), 1),
        'alerts': int(alerts or 0),
        'trips': int(trips or 0),
    } for day, avg, count, dist, alerts, trips in rows]


def vehicle_score_summary(account_id: int, from_date: date, to_date: date,
                          limit: int = 100) -> list:
    """Per-vehicle averages over the window, best score first."""
    rows = (
        db.session.query(
            FleetScoreDaily.reg_no,
            func.avg(FleetScoreDaily.vehicle_score),
            func.min(FleetScoreDaily.vehicle_score),
            func.max(FleetScoreDaily.vehicle_score),
            func.count(FleetScoreDaily.id),
            func.sum(FleetScoreDaily.distance),
            func.sum(FleetScoreDaily.alerts),
        )
        .filter(FleetScoreDaily.account_id == account_id,
                FleetScoreDaily.task_date >= from_date,
                FleetScoreDaily.task_date <= to_date)
        .group_by(FleetScoreDaily.reg_no)
        .order_by(func.avg(FleetScoreDaily.vehicle_score).desc())
        .limit(limit)
        .all()
    )
    return [{
        'reg_no': reg,
        'avg_score': round(float(avg or 0), 1),
        'min_score': round(float(lo or 0), 1),
        'max_score': round(float(hi or 0), 1),
        'days': int(days or 0),
        'distance': round(float(dist or 0), 1),
        'alerts': int(alerts or 0),
    } for reg, avg, lo, hi, days, dist, alerts in rows]


def score_movers(account_id: int, from_date: date, to_date: date,
                 limit: int = 5) -> dict:
    """Vehicles whose score moved most between the two halves of the window.

    A single day's score says little on its own — comparing half-window
    averages is what separates a real slide from one bad afternoon.
    """
    span = (to_date - from_date).days
    if span < 3:
        return {'improved': [], 'declined': [], 'split_date': None}

    split = from_date + timedelta(days=span // 2)

    def _avg_by_reg(start, end):
        rows = (
            db.session.query(FleetScoreDaily.reg_no,
                             func.avg(FleetScoreDaily.vehicle_score))
            .filter(FleetScoreDaily.account_id == account_id,
                    FleetScoreDaily.task_date >= start,
                    FleetScoreDaily.task_date <= end)
            .group_by(FleetScoreDaily.reg_no)
            .all()
        )
        return {reg: float(avg or 0) for reg, avg in rows}

    earlier = _avg_by_reg(from_date, split)
    later = _avg_by_reg(split + timedelta(days=1), to_date)

    moves = [{
        'reg_no': reg,
        'before': round(earlier[reg], 1),
        'after': round(later[reg], 1),
        'change': round(later[reg] - earlier[reg], 1),
    } for reg in earlier.keys() & later.keys()]

    moves.sort(key=lambda m: m['change'])
    declined = [m for m in moves if m['change'] < 0][:limit]
    improved = [m for m in reversed(moves) if m['change'] > 0][:limit]
    return {'improved': improved, 'declined': declined, 'split_date': split}


def coverage(account_id: int, from_date: date, to_date: date) -> dict:
    """How much of the window has been snapshotted, for the page to be honest."""
    requested = (to_date - from_date).days + 1
    missing = missing_days(account_id, from_date, to_date)
    last = (db.session.query(func.max(FleetScoreSyncStatus.last_synced_at))
            .filter(FleetScoreSyncStatus.account_id == account_id)
            .scalar())
    return {
        'days_requested': requested,
        'days_missing': len(missing),
        'days_ready': requested - len(missing),
        'complete': not missing,
        'first_missing': missing[0] if missing else None,
        'last_synced_at': last,
    }


def default_window(days: int = 30) -> tuple[date, date]:
    today = pk_date()
    return today - timedelta(days=days - 1), today


# ── On-demand backfill ───────────────────────────────────────────────────────

# A day is ~48 SOAP calls, so a 30-day gap is ~1,400 — far past what a request
# can hold. The page starts a worker instead and reads progress on reload.
_snapshot_lock = threading.Lock()

# Bound one on-demand run so a wide range cannot occupy the worker for an hour;
# the rest is picked up by the next run or the nightly schedule.
MAX_ON_DEMAND_DAYS = 10


def snapshot_running() -> bool:
    return _snapshot_lock.locked()


def _snapshot_worker(app, account_id: int, days: list):
    with app.app_context():
        try:
            for day in days:
                snapshot_day(account_id, day, source='manual')
        except Exception as exc:
            db.session.rollback()
            logger.warning('on-demand fleet score snapshot failed: %s', exc)
        finally:
            db.session.remove()
            _snapshot_lock.release()


def start_snapshot(account_id: int, from_date: date, to_date: date):
    """Snapshot this window's missing days in the background.

    Returns the number of days started, 0 when nothing is missing, or None when
    a run is already in progress.
    """
    days = missing_days(account_id, from_date, to_date)[:MAX_ON_DEMAND_DAYS]
    if not days:
        return 0
    if not _snapshot_lock.acquire(blocking=False):
        return None
    # Released by _snapshot_worker, including on failure.
    threading.Thread(
        target=_snapshot_worker,
        args=(current_app._get_current_object(), account_id, days),
        daemon=True,
        name='fleet-score-snapshot',
    ).start()
    return len(days)
