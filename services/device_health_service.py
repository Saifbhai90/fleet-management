"""Device Health / Tamper reporting over vehicle_activity_record.

A GPS unit reports its own condition through the same activity stream as its
position: losing vehicle power, running on internal battery, or failing
outright all arrive as rows with a distinctive ``reason``. Those rows are
0.205% of the table (7,169 of 3.5M), which is what makes this report both
cheap to answer and impossible to answer quickly without help — see
``ensure_device_health_index``.

A unit that stops reporting altogether is the other half of device health, and
it produces no rows at all. That case is covered by comparing each vehicle's
last-seen point against the report window rather than by counting events.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date, timedelta

from sqlalchemy import func

from app import db
from models import VehicleActivityRecord
from services.activity_rollup_service import day_presence
from utils import (
    clean_geo_location,
    normalize_vehicle_reg_key,
    pk_date,
    strip_ufone_reg_tag,
)

logger = logging.getLogger(__name__)

# Reasons the GPS unit uses to describe itself rather than the vehicle's motion.
# This tuple is the single source of truth: the report filters on it and the
# partial index below is built from it, so the two cannot drift apart.
DEVICE_EVENT_REASONS = (
    'Main Power Off',
    'Main Power On',
    'Battery Voltage',
    'Battery Current',
    'Low Battery',
    'Low battery alarm',
    'Error',
)

# Losing main power is the tamper signal — someone unplugged the unit. The rest
# are health telemetry.
TAMPER_REASONS = ('Main Power Off',)


def _index_name() -> str:
    """Name the index after its own predicate.

    ``CREATE INDEX IF NOT EXISTS`` silently keeps an existing index even when
    the predicate it was built from has changed, which would leave the report
    quietly falling back to a full scan. Folding a digest of the reason list
    into the name means editing DEVICE_EVENT_REASONS asks for a different
    index instead of accepting a stale one.
    """
    digest = hashlib.sha1(
        '|'.join(sorted(DEVICE_EVENT_REASONS)).encode('utf-8')
    ).hexdigest()[:8]
    return f'ix_var_device_events_{digest}'


def ensure_device_health_index() -> str:
    """Create the partial index this report needs, and drop superseded ones.

    Device-health rows are 0.2% of vehicle_activity_record, so filtering them
    off the task_date index reads a month of GPS points to discard 99.8% of
    them (measured: 11.5 s for a 30-day window). A partial index holds only the
    7k matching rows — under a megabyte, against ~140 MB for a full
    ``(reason, task_date)`` index on a table whose indexes already total
    700 MB.
    """
    name = _index_name()
    reasons = ', '.join("'" + r.replace("'", "''") + "'" for r in DEVICE_EVENT_REASONS)
    with db.engine.connect() as conn:
        if conn.dialect.name == 'postgresql':
            # Same reasoning as app.py's index loop: never let a lock wait on
            # this 1.5 GB table turn a deploy into a hang.
            conn.execute(db.text("SET lock_timeout = '5s'"))
            conn.execute(db.text("SET statement_timeout = '180s'"))
            conn.commit()
            stale = conn.execute(db.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'vehicle_activity_record' "
                "  AND indexname LIKE 'ix_var_device_events_%' "
                "  AND indexname <> :keep"), {'keep': name}).all()
            for (old,) in stale:
                conn.execute(db.text(f'DROP INDEX IF EXISTS {old}'))
                conn.commit()
                logger.info('dropped superseded device-health index %s', old)

        conn.execute(db.text(
            f'CREATE INDEX IF NOT EXISTS {name} '
            f'ON vehicle_activity_record (reason, task_date) '
            f'WHERE reason IN ({reasons})'))
        conn.commit()
    return name


def activity_reg_variants(regno: str) -> list:
    """Spellings of one vehicle to match against activity rows.

    The vehicle picker offers tagged regnos (``GBD-24-877 USG``) while the
    activity table stores them tag-stripped (``GBD-24-877``), so filtering on
    the picker's value alone silently returns nothing.
    """
    raw = (regno or '').strip()
    if not raw:
        return []
    return list({raw, strip_ufone_reg_tag(raw)} - {''})


def _event_class(reason: str) -> str:
    """Group a raw reason into something a fleet manager can act on."""
    text = (reason or '').strip().lower()
    if text == 'main power off':
        return 'power_lost'
    if text == 'main power on':
        return 'power_restored'
    if 'low battery' in text:
        return 'low_battery'
    if text.startswith('battery'):
        return 'battery_telemetry'
    if text == 'error':
        return 'error'
    return 'other'


def device_event_summary(from_date: date, to_date: date,
                         vehicle_no: str = '') -> list:
    """Per-vehicle counts of each device event in the window.

    Returns one dict per vehicle, sorted worst-first, so the report can lead
    with the units that need attention.
    """
    query = (
        db.session.query(
            VehicleActivityRecord.vehicle_no,
            VehicleActivityRecord.reason,
            func.count(VehicleActivityRecord.id),
            func.min(VehicleActivityRecord.record_date_time),
            func.max(VehicleActivityRecord.record_date_time),
        )
        .filter(
            VehicleActivityRecord.task_date >= from_date,
            VehicleActivityRecord.task_date <= to_date,
            VehicleActivityRecord.reason.in_(DEVICE_EVENT_REASONS),
        )
        .group_by(VehicleActivityRecord.vehicle_no, VehicleActivityRecord.reason)
    )
    variants = activity_reg_variants(vehicle_no)
    if variants:
        query = query.filter(VehicleActivityRecord.vehicle_no.in_(variants))

    per_vehicle = {}
    for reg, reason, count, first_seen, last_seen in query.all():
        row = per_vehicle.setdefault(reg, {
            'vehicle_no': reg,
            'power_lost': 0,
            'power_restored': 0,
            'low_battery': 0,
            'battery_telemetry': 0,
            'error': 0,
            'other': 0,
            'total_events': 0,
            'first_event': None,
            'last_event': None,
            'reasons': {},
        })
        row[_event_class(reason)] += count
        row['total_events'] += count
        row['reasons'][reason] = count
        # record_date_time is an ISO string, so string order is time order.
        if first_seen and (row['first_event'] is None or first_seen < row['first_event']):
            row['first_event'] = first_seen
        if last_seen and (row['last_event'] is None or last_seen > row['last_event']):
            row['last_event'] = last_seen

    rows = list(per_vehicle.values())
    for row in rows:
        row['tamper_suspected'] = row['power_lost'] > 0
        row['health_score'] = _health_score(row)
        row['status'] = _status_for(row)
    rows.sort(key=lambda r: (r['health_score'], -r['total_events']))
    return rows


def _health_score(row: dict) -> int:
    """0–100, where 100 is a unit with nothing wrong.

    Power loss is weighted hardest because it is the only event here that
    normally means human interference rather than wear.
    """
    penalty = (
        row['power_lost'] * 12
        + row['low_battery'] * 8
        + row['error'] * 6
        + row['power_restored'] * 2
    )
    return max(0, 100 - min(100, penalty))


def _status_for(row: dict) -> str:
    if row['power_lost'] or row['error']:
        return 'critical'
    if row['low_battery']:
        return 'warning'
    if row['total_events']:
        return 'info'
    return 'ok'


def device_event_log(from_date: date, to_date: date, vehicle_no: str = '',
                     limit: int = 500) -> list:
    """The individual device events, newest first, for the detail list."""
    query = (
        db.session.query(
            VehicleActivityRecord.vehicle_no,
            VehicleActivityRecord.record_date_time,
            VehicleActivityRecord.reason,
            VehicleActivityRecord.location,
            VehicleActivityRecord.task_date,
        )
        .filter(
            VehicleActivityRecord.task_date >= from_date,
            VehicleActivityRecord.task_date <= to_date,
            VehicleActivityRecord.reason.in_(DEVICE_EVENT_REASONS),
        )
    )
    variants = activity_reg_variants(vehicle_no)
    if variants:
        query = query.filter(VehicleActivityRecord.vehicle_no.in_(variants))

    rows = query.order_by(
        VehicleActivityRecord.task_date.desc(),
        VehicleActivityRecord.record_date_time.desc(),
    ).limit(limit).all()

    return [{
        'vehicle_no': reg,
        'when': rdt or '',
        'time': (rdt or '')[11:19],
        'task_date': task_date,
        'reason': reason or '',
        'event_class': _event_class(reason),
        'location': clean_geo_location(location),
    } for reg, rdt, reason, location, task_date in rows]


def reporting_gaps(from_date: date, to_date: date, vehicles: list,
                   vehicle_no: str = '') -> list:
    """Vehicles whose unit went quiet — the failures that emit no events at all.

    ``vehicles`` is the account's vehicle list, so a unit that reported nothing
    is visible as a gap instead of merely being absent from the results.

    Presence comes from the daily rollup rather than the raw activity table:
    counting points per vehicle over the raw rows is a group-by over ~900k rows
    with a 43 MB disk sort (measured: 23 s for a 30-day window).

    The two identifier spaces do not match literally: mappings carry Ufone tags
    (``GBD-24-877 USG``) that the activity table does not (``GBD-24-877``). On
    this account that is 25 of 48 vehicles, so matching on the raw string would
    report half the fleet as permanently dark. Both sides are normalised first.
    """
    seen = {}
    for reg, info in day_presence(from_date, to_date).items():
        key = normalize_vehicle_reg_key(reg)
        if not key:
            continue
        # Two spellings of one vehicle can both appear; merge them.
        merged = seen.setdefault(key, {'last_point': '', 'points': 0, 'days': 0})
        merged['points'] += info['points']
        merged['days'] = max(merged['days'], info['days'])
        if info['last_point'] > merged['last_point']:
            merged['last_point'] = info['last_point']

    span_days = max(1, (to_date - from_date).days + 1)
    wanted = normalize_vehicle_reg_key(vehicle_no) if vehicle_no else ''

    rows = []
    for vehicle in vehicles:
        reg = vehicle.get('portalxs_regno') or ''
        key = normalize_vehicle_reg_key(reg)
        if not key or (wanted and key != wanted):
            continue
        display = vehicle.get('vehicle_no') or reg
        info = seen.get(key)
        if info is None:
            rows.append({
                'vehicle_no': display, 'regno': reg, 'last_point': '',
                'points': 0, 'days': 0, 'missing_days': span_days, 'silent': True,
            })
            continue
        missing = span_days - info['days']
        if missing > 0:
            rows.append({
                'vehicle_no': display,
                'regno': reg,
                'last_point': info['last_point'],
                'points': info['points'],
                'days': info['days'],
                'missing_days': missing,
                'silent': False,
            })
    rows.sort(key=lambda r: (-r['missing_days'], r['vehicle_no']))
    return rows


def default_window(days: int = 7) -> tuple:
    """The report's default range: the last ``days`` days ending today."""
    today = pk_date()
    return today - timedelta(days=days - 1), today
