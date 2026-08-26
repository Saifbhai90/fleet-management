"""Vehicle activity records: PortalXS sync into vehicle_activity_record.

Same table as Excel Tracker Activity Report uploads.

Rules (aligned with mileage):
- Today: always re-fetch PortalXS for the vehicle unless Excel-protected, replace portalxs rows.
- Past day with DB rows for that vehicle: DB only.
- Past day empty: PortalXS once, upsert.
- Excel-uploaded vehicle (data_source='excel' or legacy NULL): never overwritten by PortalXS.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, or_

from utils import pk_date, pk_now, normalize_vehicle_reg_key, strip_ufone_reg_tag

logger = logging.getLogger(__name__)

_SOURCE_EXCEL = 'excel'
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


def is_excel_protected(task_date: date, portalxs_regno: str = '', vehicle_no: str = '') -> bool:
    """True if this vehicle already has Excel (or legacy) activity rows for the day."""
    from models import VehicleActivityRecord

    keys = {normalize_reg_key(x) for x in (portalxs_regno, vehicle_no, store_reg_no(portalxs_regno, vehicle_no)) if normalize_reg_key(x)}
    if not keys:
        return False
    rows = (
        VehicleActivityRecord.query.filter(
            VehicleActivityRecord.task_date == task_date,
            or_(
                VehicleActivityRecord.data_source == _SOURCE_EXCEL,
                VehicleActivityRecord.data_source.is_(None),
            ),
        )
        .with_entities(VehicleActivityRecord.vehicle_no)
        .distinct()
        .all()
    )
    for (vno,) in rows:
        if normalize_reg_key(vno) in keys:
            return True
    return False


def vehicle_day_has_activity(task_date: date, portalxs_regno: str = '', vehicle_no: str = '') -> bool:
    from models import VehicleActivityRecord

    keys = {normalize_reg_key(x) for x in (portalxs_regno, vehicle_no, store_reg_no(portalxs_regno, vehicle_no)) if normalize_reg_key(x)}
    if not keys:
        return False
    for (vno,) in (
        VehicleActivityRecord.query.filter_by(task_date=task_date)
        .with_entities(VehicleActivityRecord.vehicle_no)
        .distinct()
        .all()
    ):
        if normalize_reg_key(vno) in keys:
            return True
    return False


def _vehicle_no_match_filter(portalxs_regno: str = '', vehicle_no: str = ''):
    from models import VehicleActivityRecord

    variants = {
        (portalxs_regno or '').strip(),
        (vehicle_no or '').strip(),
        store_reg_no(portalxs_regno, vehicle_no),
        strip_ufone_reg_tag(portalxs_regno),
        strip_ufone_reg_tag(vehicle_no),
    }
    variants = {v for v in variants if v}
    if not variants:
        return VehicleActivityRecord.id < 0
    upper = {v.upper() for v in variants}
    return or_(
        VehicleActivityRecord.vehicle_no.in_(list(variants)),
        func.upper(func.trim(VehicleActivityRecord.vehicle_no)).in_(list(upper)),
    )


def records_to_report_rows(records: list) -> list[dict]:
    rows = []
    for r in records:
        rows.append({
            'RegNo': r.vehicle_no or '',
            'Group': r.group_name or '',
            'RecordDateTime': r.record_date_time or '',
            'Location': r.location or '',
            'Speed': float(r.speed or 0),
            'Direction': r.direction or '',
            'Distance': float(r.distance or 0),
            'TravelTime': r.travel_time or '00:00:00',
            'StopTime': r.stop_time or '00:00:00',
            'Reason': r.reason or '',
            'LAT': float(r.latitude) if r.latitude is not None else None,
            'LON': float(r.longitude) if r.longitude is not None else None,
            'data_source': r.data_source or '',
        })
    return rows


def load_activity_from_db(task_date: date, portalxs_regno: str = '', vehicle_no: str = '') -> list[dict]:
    from models import VehicleActivityRecord

    q = (
        VehicleActivityRecord.query.filter(
            VehicleActivityRecord.task_date == task_date,
            _vehicle_no_match_filter(portalxs_regno, vehicle_no),
        )
        .order_by(VehicleActivityRecord.record_date_time.asc(), VehicleActivityRecord.id.asc())
    )
    return records_to_report_rows(q.all())


def delete_portalxs_activity_for_vehicle(task_date: date, portalxs_regno: str = '', vehicle_no: str = '') -> int:
    """Remove PortalXS-sourced rows only (never excel)."""
    from models import VehicleActivityRecord
    from app import db

    n = (
        VehicleActivityRecord.query.filter(
            VehicleActivityRecord.task_date == task_date,
            _vehicle_no_match_filter(portalxs_regno, vehicle_no),
            VehicleActivityRecord.data_source == _SOURCE_PORTALXS,
        ).delete(synchronize_session=False)
    )
    db.session.flush()
    return int(n or 0)


def delete_all_activity_for_vehicle(task_date: date, vehicle_no: str) -> int:
    """Used before Excel replace for one vehicle."""
    from models import VehicleActivityRecord
    from app import db

    n = (
        VehicleActivityRecord.query.filter(
            VehicleActivityRecord.task_date == task_date,
            _vehicle_no_match_filter('', vehicle_no),
        ).delete(synchronize_session=False)
    )
    db.session.flush()
    return int(n or 0)


def upsert_portalxs_activity(
    account_id: int,
    portalxs_regno: str,
    task_date: date,
    vehicle_no: str = '',
    group_name: str = '',
) -> dict:
    """Fetch one vehicle/day from PortalXS and replace portalxs rows in DB."""
    from app import db
    from models import VehicleActivityRecord
    from services.portalxs_service import fetch_history, enrich_activity_report_rows

    store = store_reg_no(portalxs_regno, vehicle_no)
    if is_excel_protected(task_date, portalxs_regno, vehicle_no):
        rows = load_activity_from_db(task_date, portalxs_regno, vehicle_no)
        return {
            'ok': True,
            'source': 'excel_skip',
            'count': len(rows),
            'rows': rows,
            'vehicle_no': store,
        }

    fdt = f'{task_date.isoformat()}T00:00:00'
    tdt = f'{task_date.isoformat()}T23:59:59'
    try:
        raw = fetch_history(account_id, portalxs_regno, fdt, tdt) or []
    except Exception as e:
        logger.warning('activity portalxs fetch failed %s %s: %s', portalxs_regno, task_date, e)
        return {'ok': False, 'source': 'error', 'error': str(e)[:240], 'count': 0, 'rows': [], 'vehicle_no': store}

    enriched = enrich_activity_report_rows(raw, group_name=group_name or '')
    delete_portalxs_activity_for_vehicle(task_date, portalxs_regno, vehicle_no)

    today = pk_date()
    mappings = []
    for p in enriched:
        mappings.append({
            'task_date': task_date,
            'upload_date': today,
            'created_at': pk_now(),
            'vehicle_no': store,
            'group_name': (p.get('Group') or group_name or '')[:100] or None,
            'record_date_time': (p.get('RecordDateTime') or '')[:50] or None,
            'location': p.get('Location') or None,
            'speed': float(p.get('Speed') or 0),
            'direction': (p.get('Direction') or '')[:20] or None,
            'distance': float(p.get('Distance') or 0),
            'travel_time': (p.get('TravelTime') or '')[:30] or None,
            'stop_time': (p.get('StopTime') or '')[:30] or None,
            'reason': (p.get('Reason') or '')[:100] or None,
            'latitude': p.get('LAT'),
            'longitude': p.get('LON'),
            'source_file': 'portalxs',
            'data_source': _SOURCE_PORTALXS,
        })
    if mappings:
        db.session.bulk_insert_mappings(VehicleActivityRecord, mappings)
    db.session.commit()
    rows = load_activity_from_db(task_date, portalxs_regno, vehicle_no)
    return {
        'ok': True,
        'source': 'portalxs',
        'count': len(rows),
        'rows': rows,
        'vehicle_no': store,
    }


def ensure_activity_for_range(
    account_id: int,
    portalxs_regno: str,
    from_date: date,
    to_date: date,
    vehicle_no: str = '',
    group_name: str = '',
) -> tuple[list[dict], Optional[str], str]:
    """Apply mileage-like day rules across a date range; return report rows.

    Returns (rows, error, overall_source_label).
    """
    if to_date < from_date:
        from_date, to_date = to_date, from_date

    today = pk_date()
    all_rows: list[dict] = []
    sources = set()
    errors = []

    d = from_date
    while d <= to_date:
        mode = day_fetch_mode(d, today=today)
        need_fetch = mode == 'refresh_all' or not vehicle_day_has_activity(d, portalxs_regno, vehicle_no)

        if need_fetch and not is_excel_protected(d, portalxs_regno, vehicle_no):
            result = upsert_portalxs_activity(
                account_id, portalxs_regno, d,
                vehicle_no=vehicle_no, group_name=group_name,
            )
            if not result.get('ok'):
                errors.append(f"{d.isoformat()}: {result.get('error') or 'fetch failed'}")
                # fall back to whatever is in DB
                day_rows = load_activity_from_db(d, portalxs_regno, vehicle_no)
            else:
                day_rows = result.get('rows') or []
                sources.add(result.get('source') or 'portalxs')
        else:
            day_rows = load_activity_from_db(d, portalxs_regno, vehicle_no)
            if is_excel_protected(d, portalxs_regno, vehicle_no):
                sources.add('excel')
            else:
                sources.add('db')

        all_rows.extend(day_rows)
        d += timedelta(days=1)

    label = '+'.join(sorted(sources)) if sources else 'db'
    err = '; '.join(errors) if errors else None
    return all_rows, err, label
