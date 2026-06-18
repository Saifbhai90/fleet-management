"""Helpers for grouped driver document update events (portal + profile)."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc, func, or_

from models import Driver, DriverDocumentHistory

FIELD_LABELS = {
    'cnic_expiry_date': 'CNIC Expiry Date',
    'cnic_status': 'CNIC Status',
    'cnic_front_path': 'CNIC Front Photo',
    'cnic_back_path': 'CNIC Back Photo',
    'license_valid_from': 'License Valid From',
    'license_expiry_date': 'License Expiry Date',
    'license_status': 'License Status',
    'license_front_path': 'License Front Photo',
    'license_back_path': 'License Back Photo',
    'verify_license_photo_path': 'Verify License Photo',
    'bank_name': 'Bank Name',
    'account_no': 'Account No',
    'account_title': 'Account Title',
    'shirt_size': 'Shirt Size',
    'trouser_size': 'Trouser Size',
    'jacket_size': 'Jacket Size',
}

UPDATE_TYPE_LABELS = {
    'cnic': 'CNIC',
    'license': 'License',
    'bank_uniform': 'Bank & Uniform',
}

SOURCE_LABELS = {
    'profile': 'Driver Profile',
    'portal': 'Update Portal',
}

DATE_FIELDS = frozenset({
    'cnic_expiry_date',
    'license_valid_from',
    'license_expiry_date',
})

PORTAL_TAB_BY_TYPE = {
    'cnic': 'cnic',
    'license': 'license',
    'bank_uniform': 'bank',
}


def field_display_name(field_name: str) -> str:
    return FIELD_LABELS.get(field_name, field_name.replace('_', ' ').title())


def source_display_name(source: str | None) -> str:
    if not source:
        return SOURCE_LABELS['portal']
    return SOURCE_LABELS.get(source, source.replace('_', ' ').title())


def portal_tab_for_type(update_type: str) -> str:
    return PORTAL_TAB_BY_TYPE.get(update_type, 'cnic')


def get_latest_batch_ids_for_drivers(session, driver_ids: list[int], update_type: str | None = None) -> set[str]:
    """Latest update batch per driver (optionally filtered by document type)."""
    ids = [i for i in driver_ids if i]
    if not ids:
        return set()
    q = (
        session.query(
            DriverDocumentHistory.driver_id.label('driver_id'),
            func.max(DriverDocumentHistory.updated_at).label('max_at'),
        )
        .filter(
            DriverDocumentHistory.driver_id.in_(ids),
            DriverDocumentHistory.batch_id.isnot(None),
        )
    )
    if update_type:
        q = q.filter(DriverDocumentHistory.update_type == update_type)
    subq = q.group_by(DriverDocumentHistory.driver_id).subquery()
    rows = (
        session.query(DriverDocumentHistory.batch_id)
        .join(
            subq,
            (DriverDocumentHistory.driver_id == subq.c.driver_id)
            & (DriverDocumentHistory.updated_at == subq.c.max_at),
        )
        .distinct()
        .all()
    )
    return {r.batch_id for r in rows if r.batch_id}


def _coerce_field_value(field_name: str, raw: str | None):
    if raw is None or str(raw).strip() == '':
        return None
    text = str(raw).strip()
    if field_name in DATE_FIELDS:
        from datetime import datetime as _dt
        for fmt in ('%Y-%m-%d', '%d-%m-%Y'):
            try:
                return _dt.strptime(text[:10], fmt).date()
            except ValueError:
                continue
        return None
    return text


def _recalc_driver_doc_status(driver: Driver) -> None:
    from utils import pk_date

    today = pk_date()
    if driver.cnic_expiry_date:
        driver.cnic_status = 'Valid' if driver.cnic_expiry_date >= today else 'Expired'
    if driver.license_expiry_date:
        driver.license_status = 'Valid' if driver.license_expiry_date >= today else 'Expired'


def delete_doc_update_batch(session, batch_id: str, update_type: str | None = None) -> tuple[bool, str]:
    """Delete one history batch and revert driver fields to that batch's old values."""
    ensure_driver_doc_history_schema(session)
    rows = (
        DriverDocumentHistory.query.filter_by(batch_id=batch_id)
        .order_by(DriverDocumentHistory.id.asc())
        .all()
    )
    if not rows:
        return False, 'Update record not found.'

    driver_id = rows[0].driver_id
    latest = get_latest_batch_ids_for_drivers(session, [driver_id], update_type=update_type)
    if batch_id not in latest:
        return False, 'Only the latest update can be deleted.'

    driver = session.get(Driver, driver_id)
    if not driver:
        return False, 'Driver not found.'

    for row in rows:
        if not hasattr(driver, row.field_name):
            continue
        setattr(driver, row.field_name, _coerce_field_value(row.field_name, row.old_value))

    _recalc_driver_doc_status(driver)
    for row in rows:
        session.delete(row)
    session.commit()
    return True, 'Update deleted and driver data reverted to previous values.'


def is_media_value(value: str | None) -> bool:
    if not value:
        return False
    v = str(value)
    return v.startswith(('http://', 'https://', 'uploads/'))


def ensure_driver_doc_history_schema(session) -> bool:
    """Add missing columns on driver_document_history (no server restart needed)."""
    from sqlalchemy import inspect, text

    engine = session.get_bind()
    inspector = inspect(engine)
    if 'driver_document_history' not in inspector.get_table_names():
        return False
    cols = {c['name'] for c in inspector.get_columns('driver_document_history')}
    added = False
    if 'batch_id' not in cols:
        session.execute(text('ALTER TABLE driver_document_history ADD COLUMN batch_id VARCHAR(36)'))
        added = True
    if 'update_source' not in cols:
        session.execute(text('ALTER TABLE driver_document_history ADD COLUMN update_source VARCHAR(20)'))
        added = True
    if added:
        session.commit()
    return added


def backfill_driver_doc_batch_ids(session) -> int:
    """Assign batch_id to legacy rows grouped by submit (driver, type, second, user)."""
    ensure_driver_doc_history_schema(session)
    null_rows = (
        DriverDocumentHistory.query.filter(DriverDocumentHistory.batch_id.is_(None))
        .order_by(DriverDocumentHistory.updated_at.asc(), DriverDocumentHistory.id.asc())
        .all()
    )
    if not null_rows:
        return 0

    def _group_key(row: DriverDocumentHistory) -> tuple:
        ts = row.updated_at
        if ts is not None:
            ts = ts.replace(microsecond=0)
        return (row.driver_id, row.update_type, ts, row.updated_by or '')

    groups: dict[tuple, str] = {}
    for row in null_rows:
        key = _group_key(row)
        if key not in groups:
            groups[key] = str(uuid.uuid4())
        row.batch_id = groups[key]
    session.commit()
    return len(groups)


def _apply_event_filters(query, project_id=0, district_id=0, update_type='', q=''):
    if project_id:
        query = query.filter(Driver.project_id == project_id)
    if district_id:
        query = query.filter(Driver.district_id == district_id)
    if update_type:
        query = query.filter(DriverDocumentHistory.update_type == update_type)
    if q:
        like = f'%{q}%'
        query = query.filter(
            or_(
                Driver.name.ilike(like),
                Driver.driver_id.ilike(like),
                Driver.cnic_no.ilike(like),
                DriverDocumentHistory.updated_by.ilike(like),
                DriverDocumentHistory.field_name.ilike(like),
            )
        )
    return query


def events_query(session, project_id=0, district_id=0, update_type='', q=''):
    ensure_driver_doc_history_schema(session)
    query = (
        session.query(
            DriverDocumentHistory.batch_id.label('batch_id'),
            func.max(DriverDocumentHistory.driver_id).label('driver_id'),
            func.max(DriverDocumentHistory.update_type).label('update_type'),
            func.max(DriverDocumentHistory.updated_by).label('updated_by'),
            func.max(DriverDocumentHistory.updated_at).label('updated_at'),
            func.max(DriverDocumentHistory.update_source).label('update_source'),
            func.count(DriverDocumentHistory.id).label('field_count'),
        )
        .join(Driver, DriverDocumentHistory.driver_id == Driver.id)
        .filter(DriverDocumentHistory.batch_id.isnot(None))
        .group_by(DriverDocumentHistory.batch_id)
    )
    return _apply_event_filters(query, project_id, district_id, update_type, q)


def count_doc_update_stats(session, project_id=0, district_id=0, update_type='', q='') -> dict[str, int]:
    base = events_query(session, project_id, district_id, '', q)
    if update_type:
        base = base.filter(DriverDocumentHistory.update_type == update_type)

    subq = base.subquery()
    total = session.query(func.count()).select_from(subq).scalar() or 0

    by_type: dict[str, int] = {'cnic': 0, 'license': 0, 'bank_uniform': 0}
    type_rows = (
        session.query(
            subq.c.update_type,
            func.count().label('cnt'),
        )
        .group_by(subq.c.update_type)
        .all()
    )
    for ut, cnt in type_rows:
        if ut in by_type:
            by_type[ut] = int(cnt or 0)
    return {'total': total, **by_type}


def _event_from_row(r, fields: list[DriverDocumentHistory], *, is_deletable: bool = False) -> dict[str, Any]:
    return {
        'batch_id': r.batch_id,
        'update_type': r.update_type,
        'updated_by': r.updated_by,
        'updated_at': r.updated_at,
        'update_source': getattr(r, 'update_source', None) or 'portal',
        'field_count': r.field_count,
        'fields': fields,
        'summary': _event_summary(fields),
        'is_deletable': is_deletable,
    }


def paginate_doc_update_events(session, page=1, per_page=20, project_id=0, district_id=0, update_type='', q=''):
    base = events_query(session, project_id, district_id, update_type, q)
    subq = base.subquery()
    total = session.query(func.count()).select_from(subq).scalar() or 0

    rows = (
        base.order_by(desc(func.max(DriverDocumentHistory.updated_at)))
        .offset(max(0, (page - 1) * per_page))
        .limit(per_page)
        .all()
    )

    batch_ids = [r.batch_id for r in rows]
    fields_by_batch = load_fields_by_batch(session, batch_ids)
    drivers_by_id = _load_drivers(session, [r.driver_id for r in rows])
    latest_batches = get_latest_batch_ids_for_drivers(session, list(drivers_by_id.keys()))

    events = []
    for r in rows:
        ev = _event_from_row(
            r,
            fields_by_batch.get(r.batch_id, []),
            is_deletable=r.batch_id in latest_batches,
        )
        ev['driver'] = drivers_by_id.get(r.driver_id)
        ev['driver_id'] = r.driver_id
        events.append(ev)

    pages = max(1, (total + per_page - 1) // per_page) if total else 1
    return {
        'items': events,
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': pages,
        'has_prev': page > 1,
        'has_next': page < pages,
        'prev_num': page - 1 if page > 1 else None,
        'next_num': page + 1 if page < pages else None,
        'iter_pages': _iter_pages(page, pages),
    }


def _iter_pages(page: int, pages: int, left: int = 2, right: int = 2):
    if pages <= 1:
        return [1]
    out: list[int | str] = []
    last = 0
    for p in range(1, pages + 1):
        if p == 1 or p == pages or (page - left <= p <= page + right):
            if last and p - last > 1:
                out.append('…')
            out.append(p)
            last = p
    return out


def load_fields_by_batch(session, batch_ids: list[str]) -> dict[str, list[DriverDocumentHistory]]:
    if not batch_ids:
        return {}
    rows = (
        DriverDocumentHistory.query.filter(DriverDocumentHistory.batch_id.in_(batch_ids))
        .order_by(DriverDocumentHistory.id.asc())
        .all()
    )
    out: dict[str, list[DriverDocumentHistory]] = {}
    for row in rows:
        out.setdefault(row.batch_id, []).append(row)
    return out


def _load_drivers(session, driver_ids: list[int]) -> dict[int, Driver]:
    ids = [i for i in driver_ids if i]
    if not ids:
        return {}
    rows = Driver.query.filter(Driver.id.in_(ids)).all()
    return {d.id: d for d in rows}


def _event_summary(fields: list[DriverDocumentHistory]) -> str:
    if not fields:
        return ''
    names = [field_display_name(f.field_name) for f in fields[:3]]
    extra = len(fields) - 3
    text = ', '.join(names)
    if extra > 0:
        text += f' +{extra} more'
    return text


def _serialize_field(fld: DriverDocumentHistory) -> dict[str, Any]:
    return {
        'field_name': fld.field_name,
        'field_label': field_display_name(fld.field_name),
        'old_value': fld.old_value or '',
        'new_value': fld.new_value or '',
        'old_is_media': is_media_value(fld.old_value),
        'new_is_media': is_media_value(fld.new_value),
    }


def _serialize_event(event: dict[str, Any]) -> dict[str, Any]:
    updated_at = event.get('updated_at')
    src = event.get('update_source') or 'portal'
    return {
        'batch_id': event.get('batch_id'),
        'update_type': event.get('update_type'),
        'updated_by': event.get('updated_by') or '',
        'updated_at': updated_at.strftime('%d-%m-%Y %I:%M %p') if updated_at else '',
        'update_source': src,
        'update_source_label': source_display_name(src),
        'field_count': event.get('field_count', 0),
        'summary': event.get('summary') or '',
        'is_deletable': bool(event.get('is_deletable')),
        'fields': [_serialize_field(f) for f in event.get('fields') or []],
    }


def fetch_driver_doc_history_counts(session, driver_id: int) -> dict[str, int]:
    ensure_driver_doc_history_schema(session)
    counts = {'cnic': 0, 'license': 0, 'bank_uniform': 0}
    rows = (
        session.query(
            DriverDocumentHistory.update_type,
            func.count(func.distinct(DriverDocumentHistory.batch_id)).label('cnt'),
        )
        .filter(
            DriverDocumentHistory.driver_id == driver_id,
            DriverDocumentHistory.batch_id.isnot(None),
        )
        .group_by(DriverDocumentHistory.update_type)
        .all()
    )
    for ut, cnt in rows:
        if ut in counts:
            counts[ut] = int(cnt or 0)
    return counts


def fetch_driver_doc_events(
    session,
    driver_id: int,
    limit: int = 15,
    update_type: str | None = None,
) -> list[dict[str, Any]]:
    ensure_driver_doc_history_schema(session)
    q = (
        session.query(
            DriverDocumentHistory.batch_id.label('batch_id'),
            func.max(DriverDocumentHistory.update_type).label('update_type'),
            func.max(DriverDocumentHistory.updated_by).label('updated_by'),
            func.max(DriverDocumentHistory.updated_at).label('updated_at'),
            func.max(DriverDocumentHistory.update_source).label('update_source'),
            func.count(DriverDocumentHistory.id).label('field_count'),
        )
        .filter(
            DriverDocumentHistory.driver_id == driver_id,
            DriverDocumentHistory.batch_id.isnot(None),
        )
    )
    if update_type:
        q = q.filter(DriverDocumentHistory.update_type == update_type)
    rows = (
        q.group_by(DriverDocumentHistory.batch_id)
        .order_by(desc(func.max(DriverDocumentHistory.updated_at)))
        .limit(limit)
        .all()
    )
    batch_ids = [r.batch_id for r in rows]
    fields_by_batch = load_fields_by_batch(session, batch_ids)
    latest_batches = get_latest_batch_ids_for_drivers(session, [driver_id], update_type=update_type)
    return [
        _event_from_row(
            r,
            fields_by_batch.get(r.batch_id, []),
            is_deletable=r.batch_id in latest_batches,
        )
        for r in rows
    ]


def fetch_driver_doc_events_json(
    session,
    driver_id: int,
    update_type: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    events = fetch_driver_doc_events(session, driver_id, limit=limit, update_type=update_type)
    return [_serialize_event(ev) for ev in events]
