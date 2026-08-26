"""Vehicle mileage records: PortalXS sync into vehicle_mileage_record.

Rules:
- Today: always re-fetch PortalXS for all vehicles except Excel-protected regs, upsert.
- Past day with DB rows: DB only.
- Past day empty: PortalXS once (fill), upsert.
- Excel-uploaded reg_no (data_source='excel'): never overwritten by PortalXS.
- Auto schedule uses full-fleet refresh (same as today refresh), skip excel regs only.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Optional

from utils import pk_date, pk_now

logger = logging.getLogger(__name__)

_SOURCE_EXCEL = 'excel'
_SOURCE_PORTALXS = 'portalxs'
_VEHICLE_SUFFIX_RE = re.compile(
    r'[\s\-_]*(?:COW|RAS|BLS|ALS|EMG|EMERGENCY)\s*$',
    re.IGNORECASE,
)


def normalize_reg_key(raw: Optional[str]) -> str:
    if not raw:
        return ''
    s = str(raw).strip()
    s = _VEHICLE_SUFFIX_RE.sub('', s).strip()
    return s.upper().replace(' ', '')


def _split_dt(val: Optional[str]) -> tuple[str, str]:
    s = (val or '').strip()
    if not s:
        return '', ''
    if 'T' in s:
        d, t = s.split('T', 1)
        return d[:10], (t[:8] if t else '')
    if ' ' in s and len(s) >= 10:
        d, t = s.split(' ', 1)
        return d[:10], (t[:8] if t else '')
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return s[:10], ''
    return s, ''


def day_has_mileage_data(task_date: date) -> bool:
    from models import VehicleMileageRecord
    return (
        VehicleMileageRecord.query.filter_by(task_date=task_date)
        .with_entities(VehicleMileageRecord.id)
        .first()
        is not None
    )


def excel_protected_keys(task_date: date) -> set[str]:
    from models import VehicleMileageRecord
    from app import db
    rows = (
        VehicleMileageRecord.query.filter(
            VehicleMileageRecord.task_date == task_date,
            db.or_(
                VehicleMileageRecord.data_source == _SOURCE_EXCEL,
                VehicleMileageRecord.data_source.is_(None),
            ),
        )
        .with_entities(VehicleMileageRecord.reg_no)
        .all()
    )
    return {normalize_reg_key(r[0]) for r in rows if r[0]}


def _vehicle_match_keys(portalxs_regno: str, vehicle_no: Optional[str] = None) -> set[str]:
    keys = set()
    for raw in (portalxs_regno, vehicle_no):
        k = normalize_reg_key(raw)
        if k:
            keys.add(k)
    return keys


def is_excel_protected(task_date: date, portalxs_regno: str, vehicle_no: Optional[str] = None) -> bool:
    protected = excel_protected_keys(task_date)
    if not protected:
        return False
    return bool(_vehicle_match_keys(portalxs_regno, vehicle_no) & protected)


def find_mileage_record(task_date: date, portalxs_regno: str, vehicle_no: Optional[str] = None):
    from models import VehicleMileageRecord
    keys = _vehicle_match_keys(portalxs_regno, vehicle_no)
    if not keys:
        return None
    rows = VehicleMileageRecord.query.filter_by(task_date=task_date).all()
    for row in rows:
        if normalize_reg_key(row.reg_no) in keys:
            return row
    return None


def record_to_row(rec, seq: int = 0) -> dict:
    dfc, tfc = _split_dt(rec.date_time_c)
    dfd, tfd = _split_dt(rec.date_time_d)
    dfe, tfe = _split_dt(rec.date_time_e)
    dff, tff = _split_dt(rec.date_time_f)
    date_from = dfc or dfe or (rec.task_date.isoformat() if rec.task_date else '')
    time_from = tfc or tfe or '00:00:00'
    date_to = dfd or dff or (rec.task_date.isoformat() if rec.task_date else '')
    time_to = tfd or tff or '23:59:59'
    return {
        'ID': seq or rec.id,
        '_regno': rec.reg_no or '',
        'vehicle_no': rec.reg_no or '',
        'DateFrom': date_from,
        'TimeFrom': time_from,
        'DateTo': date_to,
        'TimeTo': time_to,
        'Mileage': float(rec.mileage or 0),
        'PToP': float(rec.ptop or 0),
        'source': rec.data_source or 'db',
        'task_date': rec.task_date.isoformat() if rec.task_date else '',
    }


def list_day_rows(task_date: date) -> list[dict]:
    from models import VehicleMileageRecord
    rows = (
        VehicleMileageRecord.query.filter_by(task_date=task_date)
        .order_by(VehicleMileageRecord.reg_no.asc())
        .all()
    )
    return [record_to_row(r, i + 1) for i, r in enumerate(rows)]


def aggregate_range_rows(from_date: date, to_date: date) -> list[dict]:
    """Load per-day records and sum Mileage/PToP by normalized reg key."""
    from models import VehicleMileageRecord

    if from_date > to_date:
        from_date, to_date = to_date, from_date
    recs = (
        VehicleMileageRecord.query
        .filter(
            VehicleMileageRecord.task_date >= from_date,
            VehicleMileageRecord.task_date <= to_date,
        )
        .order_by(VehicleMileageRecord.task_date.asc(), VehicleMileageRecord.reg_no.asc())
        .all()
    )
    by_key: dict[str, dict] = {}
    for rec in recs:
        key = normalize_reg_key(rec.reg_no) or (rec.reg_no or '')
        if not key:
            continue
        if key not in by_key:
            row = record_to_row(rec)
            row['DateFrom'] = from_date.isoformat()
            row['TimeFrom'] = '00:00:00'
            row['DateTo'] = to_date.isoformat()
            row['TimeTo'] = '23:59:59'
            row['Mileage'] = float(rec.mileage or 0)
            row['PToP'] = float(rec.ptop or 0)
            by_key[key] = row
        else:
            by_key[key]['Mileage'] = float(by_key[key]['Mileage'] or 0) + float(rec.mileage or 0)
            by_key[key]['PToP'] = float(by_key[key]['PToP'] or 0) + float(rec.ptop or 0)
    out = list(by_key.values())
    out.sort(key=lambda r: (r.get('vehicle_no') or r.get('_regno') or ''))
    for i, r in enumerate(out, start=1):
        r['ID'] = i
    return out


def day_fetch_mode(task_date: date, today: Optional[date] = None) -> str:
    """Return 'refresh_all' | 'fill_missing' | 'db_only'."""
    today = today or pk_date()
    if task_date == today:
        return 'refresh_all'
    if day_has_mileage_data(task_date):
        return 'db_only'
    return 'fill_missing'


def pending_regnos_for_day(
    account_id: int,
    task_date: date,
    mode: Optional[str] = None,
) -> list[dict]:
    """Vehicles still needing a PortalXS fetch for this day.

    Returns list of {portalxs_regno, vehicle_no}.
    """
    from services.portalxs_service import get_all_vehicles_for_account

    mode = mode or day_fetch_mode(task_date)
    if mode == 'db_only':
        return []

    vehicles = get_all_vehicles_for_account(account_id)
    protected = excel_protected_keys(task_date)
    existing_keys = set()
    if mode == 'fill_missing':
        from models import VehicleMileageRecord
        existing_keys = {
            normalize_reg_key(r[0])
            for r in VehicleMileageRecord.query.filter_by(task_date=task_date)
            .with_entities(VehicleMileageRecord.reg_no)
            .all()
            if r[0]
        }

    pending = []
    for v in vehicles:
        regno = v.get('portalxs_regno') or ''
        vno = v.get('vehicle_no') or regno
        keys = _vehicle_match_keys(regno, vno)
        if keys & protected:
            continue
        if mode == 'fill_missing' and (keys & existing_keys):
            continue
        pending.append({'portalxs_regno': regno, 'vehicle_no': vno})
    return pending


def upsert_from_portalxs(
    task_date: date,
    portalxs_regno: str,
    vehicle_no: Optional[str],
    mileage: float,
    ptop: float,
    date_from: str = '',
    time_from: str = '',
    date_to: str = '',
    time_to: str = '',
) -> Optional[dict]:
    """Upsert PortalXS mileage into vehicle_mileage_record. Skips Excel-protected."""
    from app import db
    from models import VehicleMileageRecord

    if is_excel_protected(task_date, portalxs_regno, vehicle_no):
        existing = find_mileage_record(task_date, portalxs_regno, vehicle_no)
        return record_to_row(existing) if existing else None

    store_reg = (vehicle_no or portalxs_regno or '').strip()
    if not store_reg:
        return None

    day_s = task_date.isoformat()
    df = (date_from or day_s)[:10]
    tf = (time_from or '00:00:00')[:8]
    dt = (date_to or day_s)[:10]
    tt = (time_to or '23:59:59')[:8]

    rec = find_mileage_record(task_date, portalxs_regno, vehicle_no)
    if rec and (rec.data_source or '') == _SOURCE_EXCEL:
        return record_to_row(rec)

    if not rec:
        rec = VehicleMileageRecord(
            task_date=task_date,
            upload_date=pk_date(),
            reg_no=store_reg,
            created_at=pk_now(),
        )
        db.session.add(rec)
    else:
        # Prefer stable fleet vehicle_no when available
        if vehicle_no:
            rec.reg_no = vehicle_no

    rec.upload_date = pk_date()
    rec.date_time_c = f'{df} {tf}'.strip()
    rec.date_time_d = f'{dt} {tt}'.strip()
    rec.date_time_e = df
    rec.date_time_f = dt
    rec.mileage = mileage or 0
    rec.ptop = ptop or 0
    rec.data_source = _SOURCE_PORTALXS
    db.session.commit()
    out = record_to_row(rec)
    out['source'] = _SOURCE_PORTALXS
    return out


def fetch_and_upsert_one(account_id: int, portalxs_regno: str, task_date: date, vehicle_no: str = '') -> dict:
    """Fetch one vehicle from PortalXS for a single calendar day and upsert."""
    from services.portalxs_service import fetch_mileage, normalize_mileage_report

    fdt = f'{task_date.isoformat()}T00:00:00'
    tdt = f'{task_date.isoformat()}T23:59:59'
    raw = fetch_mileage(account_id, portalxs_regno, fdt, tdt)
    if isinstance(raw, dict):
        raw_list = [raw]
    elif isinstance(raw, list):
        raw_list = raw
    else:
        raw_list = []

    if not raw_list:
        item = normalize_mileage_report({}, query_from=fdt, query_to=tdt)
        miles = float(item.get('Mileage') or 0)
        ptop = float(item.get('PToP') or 0)
    else:
        first = normalize_mileage_report(
            raw_list[0] if isinstance(raw_list[0], dict) else {},
            query_from=fdt, query_to=tdt,
        )
        miles = 0.0
        ptop = 0.0
        for chunk in raw_list:
            if not isinstance(chunk, dict):
                continue
            n = normalize_mileage_report(chunk, query_from=fdt, query_to=tdt)
            miles += float(n.get('Mileage') or 0)
            ptop += float(n.get('PToP') or 0)
            if not first.get('DateFrom') and n.get('DateFrom'):
                first = n
        item = dict(first)

    row = upsert_from_portalxs(
        task_date=task_date,
        portalxs_regno=portalxs_regno,
        vehicle_no=vehicle_no or portalxs_regno,
        mileage=miles,
        ptop=ptop,
        date_from=item.get('DateFrom') or task_date.isoformat(),
        time_from=item.get('TimeFrom') or '00:00:00',
        date_to=item.get('DateTo') or task_date.isoformat(),
        time_to=item.get('TimeTo') or '23:59:59',
    )
    if not row:
        # Excel skip with no prior row — return stub for UI continuity
        return {
            'ID': '',
            '_regno': portalxs_regno,
            'vehicle_no': vehicle_no or portalxs_regno,
            'DateFrom': task_date.isoformat(),
            'TimeFrom': '00:00:00',
            'DateTo': task_date.isoformat(),
            'TimeTo': '23:59:59',
            'Mileage': 0,
            'PToP': 0,
            'source': 'excel_skip',
            'task_date': task_date.isoformat(),
        }
    return row


def sync_day_full(account_id: int, task_date: date) -> dict:
    """Full-fleet PortalXS refresh for one day (auto schedule). Skips Excel regs."""
    pending = pending_regnos_for_day(account_id, task_date, mode='refresh_all')
    ok = 0
    skipped = 0
    errors = []
    for item in pending:
        regno = item['portalxs_regno']
        try:
            fetch_and_upsert_one(
                account_id, regno, task_date, vehicle_no=item.get('vehicle_no') or regno
            )
            ok += 1
        except Exception as exc:
            errors.append(f'{regno}: {str(exc)[:120]}')
            logger.warning('mileage sync failed account=%s day=%s regno=%s: %s',
                           account_id, task_date, regno, exc)
    excel_n = len(excel_protected_keys(task_date))
    return {
        'task_date': task_date.isoformat(),
        'account_id': account_id,
        'fetched': ok,
        'excel_skipped': excel_n,
        'pending': len(pending),
        'errors': errors[:10],
        'error_count': len(errors),
    }


def sync_all_active_accounts_for_day(task_date: date) -> list[dict]:
    from models import PortalXSAccount
    results = []
    accounts = PortalXSAccount.query.filter_by(is_active=True).all()
    for acct in accounts:
        try:
            results.append(sync_day_full(acct.id, task_date))
        except Exception as exc:
            logger.exception('mileage sync account=%s day=%s failed', acct.id, task_date)
            results.append({
                'task_date': task_date.isoformat(),
                'account_id': acct.id,
                'error': str(exc)[:300],
            })
    return results


def plan_days_for_range(from_date: date, to_date: date) -> list[dict]:
    """Per-day fetch plan for the Generate UI."""
    today = pk_date()
    if from_date > to_date:
        from_date, to_date = to_date, from_date
    days = []
    d = from_date
    while d <= to_date:
        mode = day_fetch_mode(d, today=today)
        days.append({
            'date': d.isoformat(),
            'mode': mode,
            'needs_fetch': mode in ('refresh_all', 'fill_missing'),
        })
        d += timedelta(days=1)
    return days
