"""Ignition On/Off report from PortalXS trips (vehicle_trip_record).

Each PortalXS trip is one ignition cycle: IGON → IGOFF, with optional movement.
The History page already shows moving trips; this report keeps the idle cycles
too (engine on, zero km), which is what "ignition on/off" usually means.

Data is PortalXS only — never Ufone. Rows land in vehicle_trip_record when the
GPS activity sync runs, and a selected vehicle is refreshed on demand.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, or_

from app import db
from models import VehicleTripRecord
from services.activity_rollup_service import format_duration
from services.trip_record_service import (
    ensure_trips_for_range,
    store_reg_no,
)
from utils import pk_date, strip_ufone_reg_tag

logger = logging.getLogger(__name__)


def default_window(days: int = 7) -> tuple[date, date]:
    today = pk_date()
    return today - timedelta(days=days - 1), today


def _parse_seconds(raw) -> int:
    """TravelTimeS arrives as bare seconds (``2451``) or occasionally ``H:MM:SS``."""
    text = str(raw or '').strip()
    if not text:
        return 0
    if ':' in text:
        parts = text.split(':')
        try:
            nums = [int(p) for p in parts]
        except (TypeError, ValueError):
            return 0
        if len(nums) == 3:
            return max(0, nums[0] * 3600 + nums[1] * 60 + nums[2])
        if len(nums) == 2:
            return max(0, nums[0] * 60 + nums[1])
        return 0
    try:
        return max(0, int(float(text)))
    except (TypeError, ValueError):
        return 0


def _parse_rdt(raw: str):
    text = (raw or '').strip().replace(' ', 'T')
    if not text:
        return None
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def cycle_seconds(igon_rdt: str, igoff_rdt: str, travel_time_s: str = '') -> int:
    """Prefer the PortalXS duration; fall back to the on→off timestamps."""
    from_field = _parse_seconds(travel_time_s)
    if from_field > 0:
        return from_field
    start, end = _parse_rdt(igon_rdt), _parse_rdt(igoff_rdt)
    if start and end and end >= start:
        return int((end - start).total_seconds())
    return 0


def _reg_filter(vehicle_no: str = ''):
    raw = (vehicle_no or '').strip()
    if not raw:
        return True
    variants = {raw, strip_ufone_reg_tag(raw), store_reg_no(raw, raw)} - {''}
    upper = {v.upper() for v in variants}
    return or_(
        VehicleTripRecord.vehicle_no.in_(list(variants)),
        func.upper(func.trim(VehicleTripRecord.vehicle_no)).in_(list(upper)),
    )


def ignition_by_vehicle(from_date: date, to_date: date,
                        vehicle_no: str = '', limit: int = 80) -> list:
    """Per-vehicle ignition totals for the window, most cycles first.

    Aggregated in Python rather than SQL: travel_time_s is a free-form string
    (bare seconds or occasionally H:MM:SS), so a SUM cast would fail on junk.
    A week of trips is a few thousand rows — cheap enough.
    """
    rows = (
        db.session.query(
            VehicleTripRecord.vehicle_no,
            VehicleTripRecord.mileage,
            VehicleTripRecord.travel_time_s,
            VehicleTripRecord.igon_rdt,
            VehicleTripRecord.igoff_rdt,
            VehicleTripRecord.trip_status,
        )
        .filter(
            VehicleTripRecord.task_date >= from_date,
            VehicleTripRecord.task_date <= to_date,
            _reg_filter(vehicle_no),
        )
        .all()
    )

    by_reg: dict[str, dict] = {}
    for reg, mileage, travel, igon, igoff, status in rows:
        bucket = by_reg.setdefault(reg, {
            'vehicle_no': reg,
            'cycles': 0,
            'moving_cycles': 0,
            'idle_cycles': 0,
            'on_seconds': 0,
            'distance': 0.0,
        })
        km = float(mileage or 0)
        secs = cycle_seconds(igon or '', igoff or '', travel or '')
        bucket['cycles'] += 1
        bucket['on_seconds'] += secs
        bucket['distance'] += km
        if km > 0.05:
            bucket['moving_cycles'] += 1
        else:
            bucket['idle_cycles'] += 1

    out = []
    for reg, b in by_reg.items():
        out.append({
            'vehicle_no': reg,
            'cycles': b['cycles'],
            'moving_cycles': b['moving_cycles'],
            'idle_cycles': b['idle_cycles'],
            'on_seconds': b['on_seconds'],
            'on_text': format_duration(b['on_seconds']),
            'distance': round(b['distance'], 1),
            'avg_cycle_text': format_duration(
                b['on_seconds'] // b['cycles'] if b['cycles'] else 0),
        })
    out.sort(key=lambda r: (-r['cycles'], -r['on_seconds']))
    return out[:limit]


def ignition_log(from_date: date, to_date: date, vehicle_no: str = '',
                 limit: int = 400) -> list:
    """Individual ignition cycles, newest first."""
    query = (
        VehicleTripRecord.query.filter(
            VehicleTripRecord.task_date >= from_date,
            VehicleTripRecord.task_date <= to_date,
            _reg_filter(vehicle_no),
        )
        .order_by(VehicleTripRecord.igon_rdt.desc(), VehicleTripRecord.id.desc())
        .limit(limit)
    )
    rows = []
    for r in query.all():
        km = float(r.mileage or 0)
        secs = cycle_seconds(r.igon_rdt or '', r.igoff_rdt or '', r.travel_time_s or '')
        idle = km <= 0.05
        rows.append({
            'vehicle_no': r.vehicle_no,
            'task_date': r.task_date,
            'igon_rdt': r.igon_rdt or '',
            'igon_time': (r.igon_rdt or '')[11:19],
            'igoff_rdt': r.igoff_rdt or '',
            'igoff_time': (r.igoff_rdt or '')[11:19],
            'on_seconds': secs,
            'on_text': format_duration(secs),
            'distance': round(km, 1),
            'max_speed': float(r.max_speed or 0),
            'status': r.trip_status or ('Idle' if idle else 'Movement'),
            'idle': idle,
            'landmark': r.igon_landmark or r.igoff_landmark or '',
            'latitude': float(r.igon_lat) if r.igon_lat is not None else None,
            'longitude': float(r.igon_lon) if r.igon_lon is not None else None,
        })
    return rows


def ignition_daily(from_date: date, to_date: date, vehicle_no: str = '') -> list:
    """Fleet (or one vehicle) cycle counts per day — for the chart."""
    rows = (
        db.session.query(
            VehicleTripRecord.task_date,
            VehicleTripRecord.mileage,
            VehicleTripRecord.travel_time_s,
            VehicleTripRecord.igon_rdt,
            VehicleTripRecord.igoff_rdt,
        )
        .filter(
            VehicleTripRecord.task_date >= from_date,
            VehicleTripRecord.task_date <= to_date,
            _reg_filter(vehicle_no),
        )
        .all()
    )
    by_day: dict[date, dict] = {}
    for day, mileage, travel, igon, igoff in rows:
        bucket = by_day.setdefault(day, {
            'task_date': day, 'cycles': 0, 'idle_cycles': 0,
            'on_seconds': 0, 'distance': 0.0,
        })
        km = float(mileage or 0)
        bucket['cycles'] += 1
        bucket['on_seconds'] += cycle_seconds(igon or '', igoff or '', travel or '')
        bucket['distance'] += km
        if km <= 0.05:
            bucket['idle_cycles'] += 1
    out = []
    for day in sorted(by_day):
        b = by_day[day]
        out.append({
            'task_date': day,
            'date_text': day.strftime('%d %b'),
            'cycles': b['cycles'],
            'idle_cycles': b['idle_cycles'],
            'moving_cycles': b['cycles'] - b['idle_cycles'],
            'on_seconds': b['on_seconds'],
            'on_text': format_duration(b['on_seconds']),
            'distance': round(b['distance'], 1),
        })
    return out


def coverage(from_date: date, to_date: date) -> dict:
    """How many days in the window already have at least one trip row."""
    present = {
        row[0] for row in
        db.session.query(VehicleTripRecord.task_date)
        .filter(VehicleTripRecord.task_date >= from_date,
                VehicleTripRecord.task_date <= to_date)
        .distinct().all()
    }
    requested = (to_date - from_date).days + 1
    missing = []
    cursor = from_date
    while cursor <= to_date:
        if cursor not in present:
            missing.append(cursor)
        cursor += timedelta(days=1)
    return {
        'days_requested': requested,
        'days_ready': requested - len(missing),
        'days_missing': len(missing),
        'complete': not missing,
        'first_missing': missing[0] if missing else None,
    }


def refresh_vehicle(account_id: int, portalxs_regno: str, from_date: date,
                    to_date: date, vehicle_no: str = '') -> tuple[list, str | None, str]:
    """Pull this vehicle's cycles from PortalXS for the window (DB-backed after)."""
    if not portalxs_regno:
        return [], 'Vehicle selected nahi hai.', 'none'
    return ensure_trips_for_range(
        account_id, portalxs_regno, from_date, to_date, vehicle_no=vehicle_no,
    )
