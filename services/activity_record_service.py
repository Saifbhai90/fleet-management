"""Vehicle activity records: PortalXS sync into vehicle_activity_record.

Same table as Excel Tracker Activity Report uploads.

Rules (aligned with mileage / History):
- Today: always re-fetch PortalXS for the vehicle unless Excel-protected, replace portalxs rows.
- Past day with DB rows for that vehicle: DB only.
- Past day empty: PortalXS once, upsert.
- Excel-uploaded vehicle (data_source='excel' or legacy NULL): never overwritten by PortalXS.

Auto schedule (PKT): 11:00 today, 16:00 (4 PM) today, next day 05:00 final for yesterday.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, or_

from utils import pk_date, pk_now, normalize_vehicle_reg_key, strip_ufone_reg_tag
from services.trip_record_service import upsert_portalxs_trips, vehicle_day_has_trips

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
            'LandMark': r.location or '',
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


def activity_rows_to_history_points(rows: list[dict]) -> list[dict]:
    """Map DB/activity rows to Route History playback shape (LAT/LON/RecordDateTime)."""
    out = []
    for r in rows or []:
        lat, lon = r.get('LAT'), r.get('LON')
        if lat is None or lon is None:
            continue
        try:
            lat_f, lon_f = float(lat), float(lon)
        except (TypeError, ValueError):
            continue
        if lat_f == 0.0 and lon_f == 0.0:
            continue
        out.append({
            'RegNo': r.get('RegNo') or '',
            'RecordDateTime': r.get('RecordDateTime') or '',
            'LAT': lat_f,
            'LON': lon_f,
            'Speed': float(r.get('Speed') or 0),
            'Reason': r.get('Reason') or '',
            'LandMark': r.get('LandMark') or r.get('Location') or '',
            'Direction': r.get('DirectionDeg') if r.get('DirectionDeg') is not None else r.get('Direction'),
            'data_source': r.get('data_source') or '',
        })
    return out


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
    """Fetch one vehicle/day from PortalXS and replace portalxs rows in DB.

    Always syncs trips for the same vehicle/day alongside activity GPS points.
    """
    from app import db
    from models import VehicleActivityRecord
    from services.portalxs_service import fetch_history, enrich_activity_report_rows

    store = store_reg_no(portalxs_regno, vehicle_no)

    # Trips travel with every activity refresh (History panel uses same day rules).
    try:
        upsert_portalxs_trips(account_id, portalxs_regno, task_date, vehicle_no=vehicle_no)
    except Exception as e:
        logger.warning(
            'activity co-sync trips failed %s %s: %s', portalxs_regno, task_date, e,
        )

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

    Also keeps vehicle_trip_record in sync for the same days (trips panel / History).

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
        trips_synced = False

        if need_fetch and not is_excel_protected(d, portalxs_regno, vehicle_no):
            result = upsert_portalxs_activity(
                account_id, portalxs_regno, d,
                vehicle_no=vehicle_no, group_name=group_name,
            )
            trips_synced = True  # upsert_portalxs_activity always co-syncs trips
            if not result.get('ok'):
                errors.append(f"{d.isoformat()}: {result.get('error') or 'fetch failed'}")
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

        # Excel-protected / DB-only activity days: still refresh or fill trips.
        if not trips_synced:
            trip_need = mode == 'refresh_all' or not vehicle_day_has_trips(
                d, portalxs_regno, vehicle_no,
            )
            if trip_need:
                try:
                    upsert_portalxs_trips(
                        account_id, portalxs_regno, d, vehicle_no=vehicle_no,
                    )
                except Exception as e:
                    logger.warning(
                        'ensure activity co-sync trips failed %s %s: %s',
                        portalxs_regno, d, e,
                    )

        all_rows.extend(day_rows)
        d += timedelta(days=1)

    label = '+'.join(sorted(sources)) if sources else 'db'
    err = '; '.join(errors) if errors else None
    return all_rows, err, label


def ensure_history_points_for_range(
    account_id: int,
    portalxs_regno: str,
    from_date: date,
    to_date: date,
    vehicle_no: str = '',
    group_name: str = '',
) -> tuple[list[dict], Optional[str], str]:
    """Same DB rules as Activity Report; returns map-ready history points."""
    rows, err, label = ensure_activity_for_range(
        account_id, portalxs_regno, from_date, to_date,
        vehicle_no=vehicle_no, group_name=group_name,
    )
    return activity_rows_to_history_points(rows), err, label


def pending_vehicles_for_day(account_id: int, task_date: date, mode: Optional[str] = None) -> list[dict]:
    """Vehicles needing PortalXS activity fetch for auto/full sync."""
    from services.portalxs_service import get_all_vehicles_for_account

    mode = mode or day_fetch_mode(task_date)
    vehicles = get_all_vehicles_for_account(account_id)
    pending = []
    for v in vehicles:
        regno = (v.get('portalxs_regno') or '').strip()
        if not regno:
            continue
        vno = (v.get('vehicle_no') or regno).strip()
        if is_excel_protected(task_date, regno, vno):
            continue
        if mode == 'fill_missing' and vehicle_day_has_activity(task_date, regno, vno):
            continue
        pending.append({
            'portalxs_regno': regno,
            'vehicle_no': vno,
            'group_name': v.get('group_name') or '',
        })
    return pending


def sync_day_full(account_id: int, task_date: date, max_workers: int = 4) -> dict:
    """Full-fleet PortalXS → vehicle_activity_record for one day (auto schedule)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from flask import current_app

    pending = pending_vehicles_for_day(account_id, task_date, mode='refresh_all')
    ok = 0
    skipped = 0
    errors: list[str] = []
    if not pending:
        return {
            'task_date': task_date.isoformat(),
            'account_id': account_id,
            'fetched': 0,
            'excel_or_empty': 0,
            'pending': 0,
            'errors': [],
            'error_count': 0,
        }

    app = current_app._get_current_object()

    def _worker(item: dict) -> dict:
        with app.app_context():
            return upsert_portalxs_activity(
                account_id,
                item['portalxs_regno'],
                task_date,
                vehicle_no=item.get('vehicle_no') or '',
                group_name=item.get('group_name') or '',
            )

    workers = max(1, min(int(max_workers or 4), 8))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_worker, item): item for item in pending}
        for fut in as_completed(futures):
            item = futures[fut]
            try:
                result = fut.result()
            except Exception as exc:
                errors.append(f"{item.get('portalxs_regno')}: {str(exc)[:160]}")
                logger.warning(
                    'activity sync failed account=%s day=%s regno=%s: %s',
                    account_id, task_date, item.get('portalxs_regno'), exc,
                )
                continue
            if not result.get('ok'):
                errors.append(
                    f"{item.get('portalxs_regno')}: {result.get('error') or 'fetch failed'}"
                )
            elif result.get('source') == 'excel_skip':
                skipped += 1
            else:
                ok += 1

    return {
        'task_date': task_date.isoformat(),
        'account_id': account_id,
        'fetched': ok,
        'excel_skipped': skipped,
        'pending': len(pending),
        'errors': errors[:50],
        'error_count': len(errors),
    }


def format_sync_pkt(dt) -> str:
    if not dt:
        return '—'
    return dt.strftime('%d %b %Y %I:%M %p') + ' PKT'


def mark_activity_sync_status(
    task_date: date,
    source: str = 'auto',
    account_id: Optional[int] = None,
    fetched_count: int = 0,
    error_count: int = 0,
    errors: Optional[list] = None,
) -> None:
    """Persist last sync time + optional fail remarks for UI.

    Pass errors=None to keep existing remarks (e.g. manual single-vehicle success).
    Pass errors=[] (or a list) to replace remarks — used by full-fleet auto sync.
    """
    from app import db
    from models import VehicleActivitySyncStatus

    row = VehicleActivitySyncStatus.query.filter_by(
        account_id=account_id, task_date=task_date,
    ).first()
    if not row:
        row = VehicleActivitySyncStatus(account_id=account_id, task_date=task_date)
        db.session.add(row)
    row.last_synced_at = pk_now()
    row.source = source if source in ('auto', 'manual') else 'manual'
    row.fetched_count = fetched_count
    if errors is not None:
        row.error_count = error_count
        remarks = []
        for item in (errors or [])[:80]:
            if isinstance(item, dict):
                regno = (item.get('regno') or item.get('portalxs_regno') or '').strip()
                err = (item.get('error') or item.get('message') or '').strip()
            else:
                text = str(item or '').strip()
                if ':' in text:
                    regno, err = text.split(':', 1)
                    regno, err = regno.strip(), err.strip()
                else:
                    regno, err = '', text
            if not (regno or err):
                continue
            remarks.append({'regno': regno[:80], 'error': err[:240]})
        row.error_remarks = json.dumps(remarks) if remarks else None
    db.session.commit()


def clear_activity_sync_remarks(account_id: Optional[int] = None, task_date: Optional[date] = None) -> int:
    """Dismiss fail remarks (X button). Keeps last_synced_at."""
    from app import db
    from models import VehicleActivitySyncStatus

    q = VehicleActivitySyncStatus.query
    if account_id is not None:
        q = q.filter_by(account_id=account_id)
    if task_date is not None:
        q = q.filter_by(task_date=task_date)
    rows = q.filter(VehicleActivitySyncStatus.error_remarks.isnot(None)).all()
    n = 0
    for row in rows:
        if row.error_remarks:
            row.error_remarks = None
            row.error_count = 0
            n += 1
    if n:
        db.session.commit()
    return n


def _parse_remarks(raw) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, dict):
            out.append({
                'regno': (item.get('regno') or '').strip(),
                'error': (item.get('error') or '').strip(),
            })
        elif item:
            out.append({'regno': '', 'error': str(item)[:240]})
    return out


def _activity_status_dict(row) -> Optional[dict]:
    if not row:
        return None
    remarks = _parse_remarks(row.error_remarks)
    return {
        'task_date': row.task_date.isoformat() if row.task_date else '',
        'task_date_label': row.task_date.strftime('%d %b %Y') if row.task_date else '',
        'last_synced_at': row.last_synced_at.isoformat(sep=' ') if row.last_synced_at else '',
        'last_synced_label': format_sync_pkt(row.last_synced_at),
        'source': row.source or '',
        'fetched_count': row.fetched_count or 0,
        'error_count': row.error_count or len(remarks),
        'remarks': remarks,
        'account_id': row.account_id,
    }


def get_activity_sync_status_display(account_id: Optional[int] = None) -> dict:
    """Status for Activity Report UI: last auto + today + active fail remarks."""
    from models import VehicleActivitySyncStatus

    today = pk_date()

    auto_q = VehicleActivitySyncStatus.query.filter_by(source='auto')
    if account_id:
        last_auto = (
            auto_q.filter_by(account_id=account_id)
            .order_by(VehicleActivitySyncStatus.last_synced_at.desc())
            .first()
        )
        if not last_auto:
            last_auto = (
                VehicleActivitySyncStatus.query.filter_by(source='auto')
                .order_by(VehicleActivitySyncStatus.last_synced_at.desc())
                .first()
            )
    else:
        last_auto = auto_q.order_by(VehicleActivitySyncStatus.last_synced_at.desc()).first()

    today_q = VehicleActivitySyncStatus.query.filter_by(task_date=today)
    if account_id:
        today_row = (
            today_q.filter_by(account_id=account_id)
            .order_by(VehicleActivitySyncStatus.last_synced_at.desc())
            .first()
        )
        if not today_row:
            today_row = (
                VehicleActivitySyncStatus.query.filter_by(task_date=today)
                .order_by(VehicleActivitySyncStatus.last_synced_at.desc())
                .first()
            )
    else:
        today_row = today_q.order_by(VehicleActivitySyncStatus.last_synced_at.desc()).first()

    # Prefer remarks from the newest row that still has them
    remarks_q = VehicleActivitySyncStatus.query.filter(
        VehicleActivitySyncStatus.error_remarks.isnot(None),
        VehicleActivitySyncStatus.error_remarks != '',
    )
    if account_id:
        remarks_row = (
            remarks_q.filter_by(account_id=account_id)
            .order_by(VehicleActivitySyncStatus.last_synced_at.desc())
            .first()
        )
        if not remarks_row:
            remarks_row = remarks_q.order_by(VehicleActivitySyncStatus.last_synced_at.desc()).first()
    else:
        remarks_row = remarks_q.order_by(VehicleActivitySyncStatus.last_synced_at.desc()).first()

    remarks = _parse_remarks(remarks_row.error_remarks) if remarks_row else []
    remarks_meta = _activity_status_dict(remarks_row) if remarks_row and remarks else None

    return {
        'today': today.isoformat(),
        'today_label': today.strftime('%d %b %Y'),
        'last_auto': _activity_status_dict(last_auto),
        'today_last': _activity_status_dict(today_row),
        'fail_remarks': remarks,
        'fail_remarks_meta': remarks_meta,
    }


def sync_all_active_accounts_for_day(task_date: date) -> list[dict]:
    from models import PortalXSAccount

    results = []
    accounts = PortalXSAccount.query.filter_by(is_active=True).all()
    for acct in accounts:
        try:
            result = sync_day_full(acct.id, task_date)
            mark_activity_sync_status(
                task_date,
                source='auto',
                account_id=acct.id,
                fetched_count=int(result.get('fetched') or 0),
                error_count=int(result.get('error_count') or 0),
                errors=result.get('errors') or [],
            )
            results.append(result)
        except Exception as exc:
            logger.exception('activity sync account=%s day=%s failed', acct.id, task_date)
            mark_activity_sync_status(
                task_date,
                source='auto',
                account_id=acct.id,
                fetched_count=0,
                error_count=1,
                errors=[f'account:{str(exc)[:240]}'],
            )
            results.append({
                'task_date': task_date.isoformat(),
                'account_id': acct.id,
                'error': str(exc)[:300],
            })
    return results
