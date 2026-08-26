"""Vehicle trip records: PortalXS trips into vehicle_trip_record.

Synced together with GPS Point / Activity Report (same day rules):
- Today: always re-fetch PortalXS and replace DB rows for the vehicle.
- Past day with DB rows: DB only.
- Past day empty: PortalXS once, upsert, then DB.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, or_

from utils import pk_date, pk_now, normalize_vehicle_reg_key, strip_ufone_reg_tag

logger = logging.getLogger(__name__)

_SOURCE_PORTALXS = 'portalxs'


def normalize_reg_key(raw: Optional[str]) -> str:
    return normalize_vehicle_reg_key(raw)


def store_reg_no(portalxs_regno: str = '', vehicle_no: str = '') -> str:
    return (
        strip_ufone_reg_tag(vehicle_no or portalxs_regno)
        or (vehicle_no or portalxs_regno or '').strip()
    )


def day_fetch_mode(task_date: date, today: Optional[date] = None) -> str:
    today = today or pk_date()
    if task_date >= today:
        return 'refresh_all'
    return 'fill_missing'


def _vehicle_no_match_filter(portalxs_regno: str = '', vehicle_no: str = ''):
    from models import VehicleTripRecord

    variants = {
        (portalxs_regno or '').strip(),
        (vehicle_no or '').strip(),
        store_reg_no(portalxs_regno, vehicle_no),
        strip_ufone_reg_tag(portalxs_regno),
        strip_ufone_reg_tag(vehicle_no),
    }
    variants = {v for v in variants if v}
    if not variants:
        return VehicleTripRecord.id < 0
    upper = {v.upper() for v in variants}
    return or_(
        VehicleTripRecord.vehicle_no.in_(list(variants)),
        func.upper(func.trim(VehicleTripRecord.vehicle_no)).in_(list(upper)),
    )


def vehicle_day_has_trips(task_date: date, portalxs_regno: str = '', vehicle_no: str = '') -> bool:
    from models import VehicleTripRecord

    keys = {
        normalize_reg_key(x)
        for x in (portalxs_regno, vehicle_no, store_reg_no(portalxs_regno, vehicle_no))
        if normalize_reg_key(x)
    }
    if not keys:
        return False
    for (vno,) in (
        VehicleTripRecord.query.filter_by(task_date=task_date)
        .with_entities(VehicleTripRecord.vehicle_no)
        .distinct()
        .all()
    ):
        if normalize_reg_key(vno) in keys:
            return True
    return False


def records_to_trip_rows(records: list) -> list[dict]:
    rows = []
    for r in records:
        rows.append({
            'IGON_RDT': r.igon_rdt or '',
            'IGON_LAT': float(r.igon_lat) if r.igon_lat is not None else None,
            'IGON_LON': float(r.igon_lon) if r.igon_lon is not None else None,
            'IGON_LandMark': r.igon_landmark or '',
            'IGOFF_RDT': r.igoff_rdt or '',
            'IGOFF_LAT': float(r.igoff_lat) if r.igoff_lat is not None else None,
            'IGOFF_LON': float(r.igoff_lon) if r.igoff_lon is not None else None,
            'IGOFF_LandMark': r.igoff_landmark or '',
            'Mileage': float(r.mileage or 0),
            'TravelTimeS': r.travel_time_s or '',
            'MaxSpeed': float(r.max_speed or 0),
            'AvgSpeed': float(r.avg_speed or 0),
            'TripStatus': r.trip_status or '',
            'RegNo': r.vehicle_no or '',
            'data_source': r.data_source or '',
        })
    return rows


def load_trips_from_db(task_date: date, portalxs_regno: str = '', vehicle_no: str = '') -> list[dict]:
    from models import VehicleTripRecord

    q = (
        VehicleTripRecord.query.filter(
            VehicleTripRecord.task_date == task_date,
            _vehicle_no_match_filter(portalxs_regno, vehicle_no),
        )
        .order_by(VehicleTripRecord.igon_rdt.asc(), VehicleTripRecord.id.asc())
    )
    return records_to_trip_rows(q.all())


def delete_trips_for_vehicle(task_date: date, portalxs_regno: str = '', vehicle_no: str = '') -> int:
    from app import db
    from models import VehicleTripRecord

    n = (
        VehicleTripRecord.query.filter(
            VehicleTripRecord.task_date == task_date,
            _vehicle_no_match_filter(portalxs_regno, vehicle_no),
        ).delete(synchronize_session=False)
    )
    db.session.flush()
    return int(n or 0)


def upsert_portalxs_trips(
    account_id: int,
    portalxs_regno: str,
    task_date: date,
    vehicle_no: str = '',
) -> dict:
    """Fetch one vehicle/day trips from PortalXS and replace DB rows."""
    from app import db
    from models import VehicleTripRecord
    from services.portalxs_service import fetch_trips

    store = store_reg_no(portalxs_regno, vehicle_no)
    fdt = f'{task_date.isoformat()}T00:00:00'
    tdt = f'{task_date.isoformat()}T23:59:59'
    try:
        raw = fetch_trips(account_id, portalxs_regno, fdt, tdt) or []
    except Exception as e:
        logger.warning('trips portalxs fetch failed %s %s: %s', portalxs_regno, task_date, e)
        return {
            'ok': False,
            'source': 'error',
            'error': str(e)[:240],
            'count': 0,
            'rows': [],
            'vehicle_no': store,
        }

    delete_trips_for_vehicle(task_date, portalxs_regno, vehicle_no)
    today = pk_date()
    mappings = []
    for t in raw:
        mappings.append({
            'task_date': task_date,
            'upload_date': today,
            'created_at': pk_now(),
            'vehicle_no': store,
            'igon_rdt': (t.get('IGON_RDT') or '')[:50] or None,
            'igon_lat': t.get('IGON_LAT'),
            'igon_lon': t.get('IGON_LON'),
            'igon_landmark': t.get('IGON_LandMark') or None,
            'igoff_rdt': (t.get('IGOFF_RDT') or '')[:50] or None,
            'igoff_lat': t.get('IGOFF_LAT'),
            'igoff_lon': t.get('IGOFF_LON'),
            'igoff_landmark': t.get('IGOFF_LandMark') or None,
            'mileage': float(t.get('Mileage') or 0),
            'travel_time_s': (t.get('TravelTimeS') or '')[:30] or None,
            'max_speed': float(t.get('MaxSpeed') or 0),
            'avg_speed': float(t.get('AvgSpeed') or 0),
            'trip_status': (t.get('TripStatus') or '')[:50] or None,
            'data_source': _SOURCE_PORTALXS,
        })
    if mappings:
        db.session.bulk_insert_mappings(VehicleTripRecord, mappings)
    db.session.commit()
    rows = load_trips_from_db(task_date, portalxs_regno, vehicle_no)
    return {
        'ok': True,
        'source': 'portalxs',
        'count': len(rows),
        'rows': rows,
        'vehicle_no': store,
    }


def ensure_trips_for_range(
    account_id: int,
    portalxs_regno: str,
    from_date: date,
    to_date: date,
    vehicle_no: str = '',
) -> tuple[list[dict], Optional[str], str]:
    """Day rules across a range; return trip rows for History panel."""
    if to_date < from_date:
        from_date, to_date = to_date, from_date

    today = pk_date()
    all_rows: list[dict] = []
    sources = set()
    errors = []

    d = from_date
    while d <= to_date:
        mode = day_fetch_mode(d, today=today)
        need_fetch = mode == 'refresh_all' or not vehicle_day_has_trips(d, portalxs_regno, vehicle_no)

        if need_fetch:
            result = upsert_portalxs_trips(
                account_id, portalxs_regno, d, vehicle_no=vehicle_no,
            )
            if not result.get('ok'):
                errors.append(f"{d.isoformat()}: {result.get('error') or 'fetch failed'}")
                day_rows = load_trips_from_db(d, portalxs_regno, vehicle_no)
            else:
                day_rows = result.get('rows') or []
                sources.add(result.get('source') or 'portalxs')
        else:
            day_rows = load_trips_from_db(d, portalxs_regno, vehicle_no)
            sources.add('db')

        all_rows.extend(day_rows)
        d += timedelta(days=1)

    label = '+'.join(sorted(sources)) if sources else 'db'
    err = '; '.join(errors) if errors else None
    return all_rows, err, label
