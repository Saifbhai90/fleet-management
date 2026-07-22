# -*- coding: utf-8 -*-
"""
Emergency Task Record — unified upsert (Option B)
=================================================
One task = one row in emergency_task_record, keyed by (task_id_ext, task_date).

Excel upload and Ufone API sync both upsert the SAME row:
  • Excel and getAmbulanceTaskReport expose the same 57 columns.
  • API sync writes all 57 report fields (same as Excel upload).
  • source tracks origin: 'excel' | 'api' | 'both'
  • excel_uploaded_at set only when Excel touches the row (upload tracker).
"""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

SOURCE_EXCEL = 'excel'
SOURCE_API = 'api'
SOURCE_BOTH = 'both'

# getAmbulanceTaskReport / Excel export — identical 57 API keys -> DB columns.
REPORT_API_TO_EMG = {
    'TaskId': 'task_id_ext',
    'RequestFrom': 'request_from',
    'Phone': 'phone',
    'CLI': 'cli',
    'Name': 'name',
    'Husband': 'husband',
    'Address': 'address',
    'Location': 'location',
    'HouseColor': 'house_color',
    'DoorColor': 'door_color',
    'NearestLandmark': 'nearest_landmark',
    'EDD': 'edd',
    'ClinicalDetails': 'clinical_details',
    'DistrictName': 'district_name',
    'TehsilName': 'tehsil_name',
    'UCname': 'uc_name',
    'ambRegNo': 'amb_reg_no',
    'Status': 'status',
    'ReceivedBy': 'received_by',
    'Category': 'category',
    'SubCategory': 'sub_category',
    'FacilityName': 'facility_name',
    'FacilityCode': 'facility_code',
    'facilityType': 'facility_type',
    'ChangeFacilityComments': 'change_facility_comments',
    'CreatedDate': 'excel_created_date',
    'CompletedDateTime': 'completed_date_time',
    'FirstTranferCreatedDate': 'first_transfer_created_date',
    'FirstTranferClinicalDetails': 'first_transfer_clinical_details',
    'FirstTranferFacilityName': 'first_transfer_facility_name',
    'FirstTranferfacilityType': 'first_transfer_facility_type',
    'FirstTranferDoctorDetail': 'first_transfer_doctor_detail',
    'SecondTranferCreatedDate': 'second_transfer_created_date',
    'SecondTranferClinicalDetails': 'second_transfer_clinical_details',
    'SecondTranferFacilityName': 'second_transfer_facility_name',
    'SecondTranferfacilityType': 'second_transfer_facility_type',
    'SecondTranferDoctorDetail': 'second_transfer_doctor_detail',
    'CreatedBy': 'created_by',
    'CreatedDate1': 'created_date1',
    'CreatedTime': 'created_time',
    'PregnancyMonth': 'pregnancy_month',
    'ClosingRemarks': 'closing_remarks',
    'PregnancyMonthClosing': 'pregnancy_month_closing',
    'cliClosing': 'cli_closing',
    'TaskClosedBy': 'task_closed_by',
    'PatientCNIC': 'patient_cnic',
    'PatientAdmissionNo': 'patient_admission_no',
    'RequestFor': 'request_for',
    'Closed_By': 'closed_by',
    'CallerName': 'caller_name',
    'taskStartLat': 'task_start_lat',
    'taskStartLon': 'task_start_lon',
    'taskEndLat': 'task_end_lat',
    'taskEndLon': 'task_end_lon',
    'rasCow': 'ras_cow',
    'distanceInKM': 'distance_in_km',
    'nearrestHealthFacility': 'nearrest_health_facility',
}

API_SYNC_FIELDS = frozenset(REPORT_API_TO_EMG.values())

# Backward-compatible alias used by merge logic.
API_OVERLAP_FIELDS = API_SYNC_FIELDS


def _coerce_report_api_value(db_col: str, val):
    """Normalize one API report value for EmergencyTaskRecord string columns."""
    if val is None:
        return None
    if isinstance(val, float) and val != val:  # NaN
        return None
    if isinstance(val, (int, float)):
        return str(val)
    return val


def emergency_report_api_to_fields(raw: dict) -> dict:
    """Map one getAmbulanceTaskReport row to EmergencyTaskRecord column dict."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for api_key, db_col in REPORT_API_TO_EMG.items():
        val = _coerce_report_api_value(db_col, raw.get(api_key))
        if val is not None:
            out[db_col] = val
    return out


def _norm_task_id(tid) -> str:
    return str(tid or '').strip()


def _has_task_id(tid) -> bool:
    return bool(_norm_task_id(tid))


def find_emergency_row(task_id_ext, task_date):
    """Lookup by natural key (task_id_ext, task_date). Returns None if no id."""
    from models import EmergencyTaskRecord
    tid = _norm_task_id(task_id_ext)
    if not tid or not task_date:
        return None
    return EmergencyTaskRecord.query.filter_by(
        task_id_ext=tid, task_date=task_date).first()


def _set_source(row, from_excel: bool, from_api: bool):
    if from_excel and from_api:
        row.source = SOURCE_BOTH
    elif from_api:
        row.source = SOURCE_API
    else:
        row.source = SOURCE_EXCEL


def _row_had_excel(row) -> bool:
    return (row.source or SOURCE_EXCEL) in (SOURCE_EXCEL, SOURCE_BOTH)


def upsert_emergency_from_excel(vals: dict, task_date, upload_date=None):
    """Upsert one Excel row. Returns the ORM row."""
    from models import EmergencyTaskRecord
    from app import db
    from utils import pk_date

    tid = _norm_task_id(vals.get('task_id_ext'))
    if not tid:
        # Legacy rows without TaskId — insert as-is (no natural key).
        row = EmergencyTaskRecord(task_date=task_date)
        db.session.add(row)
        for k, v in vals.items():
            if hasattr(row, k):
                setattr(row, k, v)
        row.upload_date = upload_date or pk_date()
        row.excel_uploaded_at = datetime.now()
        row.source = SOURCE_EXCEL if not row.synced_at else SOURCE_BOTH
        return row

    row = find_emergency_row(tid, task_date)
    had_api = bool(row and row.synced_at)
    if not row:
        row = EmergencyTaskRecord(task_id_ext=tid, task_date=task_date)
        db.session.add(row)

    for k, v in vals.items():
        if hasattr(row, k) and k not in ('id', 'source', 'account_id', 'synced_at',
                                          'excel_uploaded_at', 'created_at'):
            setattr(row, k, v)

    row.task_date = task_date
    row.upload_date = upload_date or pk_date()
    row.excel_uploaded_at = datetime.now()
    _set_source(row, from_excel=True, from_api=had_api or bool(row.synced_at))
    return row


def apply_api_fields_to_row(row, fields: dict, account_id: int, synced_at=None):
    """Merge all 57 report API fields into an existing/new row."""
    now = synced_at or datetime.now()
    had_excel = _row_had_excel(row) or bool(row.excel_uploaded_at)

    for k, v in fields.items():
        if k in API_SYNC_FIELDS and hasattr(row, k) and v is not None:
            setattr(row, k, v)

    row.account_id = account_id
    row.synced_at = now
    _set_source(row, from_excel=had_excel, from_api=True)
    return row


def merge_emergency_records(rows: list):
    """Merge duplicate ORM rows (same task_id_ext + task_date) into one keeper."""
    from app import db
    if len(rows) < 2:
        return rows[0] if rows else None

    # Prefer row with excel_uploaded_at, then oldest id
    rows = sorted(rows, key=lambda r: (
        0 if r.excel_uploaded_at else 1,
        r.id or 0,
    ))
    keeper = rows[0]
    others = rows[1:]

    for other in others:
        for col in API_SYNC_FIELDS:
            if not hasattr(keeper, col):
                continue
            ov = getattr(other, col, None)
            kv = getattr(keeper, col, None)
            if ov and not kv:
                setattr(keeper, col, ov)
        if (other.source or '') in (SOURCE_API, SOURCE_BOTH):
            for col in API_SYNC_FIELDS:
                if not hasattr(keeper, col):
                    continue
                ov = getattr(other, col, None)
                if ov is not None:
                    setattr(keeper, col, ov)
            if other.synced_at and (not keeper.synced_at or other.synced_at > keeper.synced_at):
                keeper.synced_at = other.synced_at
            if other.account_id:
                keeper.account_id = other.account_id
        if other.excel_uploaded_at and not keeper.excel_uploaded_at:
            keeper.excel_uploaded_at = other.excel_uploaded_at
        db.session.delete(other)

    had_excel = any(_row_had_excel(r) or r.excel_uploaded_at for r in rows)
    had_api = any((r.source or '') in (SOURCE_API, SOURCE_BOTH) or r.synced_at for r in rows)
    _set_source(keeper, from_excel=had_excel, from_api=had_api)
    return keeper


def dedupe_emergency_task_records() -> int:
    """One-time: merge duplicate (task_id_ext, task_date) rows. Returns merged count."""
    from models import EmergencyTaskRecord
    from app import db
    from sqlalchemy import func

    try:
        dup_groups = (
            db.session.query(
                EmergencyTaskRecord.task_id_ext,
                EmergencyTaskRecord.task_date,
                func.count(EmergencyTaskRecord.id),
            )
            .filter(
                EmergencyTaskRecord.task_id_ext.isnot(None),
                EmergencyTaskRecord.task_id_ext != '',
            )
            .group_by(EmergencyTaskRecord.task_id_ext, EmergencyTaskRecord.task_date)
            .having(func.count(EmergencyTaskRecord.id) > 1)
            .all()
        )
        if not dup_groups:
            return 0

        merged = 0
        for tid, tdate, _cnt in dup_groups:
            rows = EmergencyTaskRecord.query.filter_by(
                task_id_ext=tid, task_date=tdate).all()
            if len(rows) < 2:
                continue
            merge_emergency_records(rows)
            merged += len(rows) - 1

        # Backfill excel_uploaded_at for legacy excel-only rows
        legacy = EmergencyTaskRecord.query.filter(
            EmergencyTaskRecord.excel_uploaded_at.is_(None),
            EmergencyTaskRecord.source.in_([SOURCE_EXCEL, SOURCE_BOTH]),
        ).all()
        for r in legacy:
            r.excel_uploaded_at = r.created_at or datetime.now()

        db.session.commit()
        if merged:
            logger.info(f"dedupe_emergency_task_records: merged {merged} duplicate row(s)")
        return merged
    except Exception as e:
        db.session.rollback()
        logger.warning(f"dedupe_emergency_task_records failed (non-fatal): {e}")
        return 0


def ensure_emergency_unique_index():
    """Create partial unique index on (task_id_ext, task_date) when task id present."""
    from app import db
    from sqlalchemy import inspect, text

    try:
        dedupe_emergency_task_records()
        insp = inspect(db.engine)
        if 'emergency_task_record' not in insp.get_table_names():
            return
        existing = {idx['name'] for idx in insp.get_indexes('emergency_task_record')}
        if 'uq_emg_task_id_date' in existing:
            return
        dialect = db.engine.dialect.name
        with db.engine.connect() as conn:
            if dialect == 'sqlite':
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_emg_task_id_date "
                    "ON emergency_task_record (task_id_ext, task_date) "
                    "WHERE task_id_ext IS NOT NULL AND task_id_ext != ''"
                ))
            else:
                # PostgreSQL partial unique index
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_emg_task_id_date "
                    "ON emergency_task_record (task_id_ext, task_date) "
                    "WHERE task_id_ext IS NOT NULL AND task_id_ext <> ''"
                ))
            conn.commit()
    except Exception as e:
        logger.warning(f"ensure_emergency_unique_index failed (non-fatal): {e}")
