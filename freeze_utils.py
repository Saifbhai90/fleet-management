from datetime import date

from flask import Request

from models import SystemSetting
from utils import parse_date, pk_date


FREEZE_EXEMPT_ENDPOINTS = {
    # Auth / session / static-safe paths.
    'login',
    'logout',
    'app_logout',
    'biometric_login',
    'set_new_password',
    # Freeze settings must always remain editable.
    'freeze_data_settings',
    # Reporting + filter posts (should remain open during freeze).
    'accounts_account_ledger',
    'accounts_balance_sheet',
    'fund_transfers_list',
    'journal_vouchers_list',
    'wallet_dashboard',
    'task_report_list',
    'task_report_logbook_cover',
    'red_task_list',
    'without_task_list',
    'penalty_record_list',
    'driver_attendance_report',
    'driver_attendance_tra_report',
    'report_ai',
}

FREEZE_SAFE_ENDPOINT_TOKENS = (
    '_list',
    '_report',
    'dashboard',
    'ledger',
    'balance_sheet',
    'health',
    'global_search',
    'print',
    'view',
)

DATE_FIELD_PRIORITY = (
    'date',
    'transfer_date',
    'entry_date',
    'voucher_date',
    'journal_date',
    'task_date',
    'attendance_date',
    'fueling_date',
    'expense_date',
    'leave_date',
    'from_date',
    'to_date',
    'start_date',
    'end_date',
)


def _to_bool(v) -> bool:
    return str(v or '').strip().lower() in ('1', 'true', 'yes', 'y', 'on')


def get_freeze_config() -> dict:
    enabled = _to_bool(SystemSetting.get('freeze_data_enabled', '0'))
    lock_before = _to_bool(SystemSetting.get('freeze_data_lock_before', '0'))
    lock_after = _to_bool(SystemSetting.get('freeze_data_lock_after', '1'))
    anchor_raw = SystemSetting.get('freeze_data_anchor_date')
    anchor_date = parse_date(anchor_raw)
    reason = (SystemSetting.get('freeze_data_reason', '') or '').strip()
    updated_by = (SystemSetting.get('freeze_data_updated_by', '') or '').strip()
    updated_at = (SystemSetting.get('freeze_data_updated_at', '') or '').strip()
    return {
        'enabled': enabled,
        'lock_before': lock_before,
        'lock_after': lock_after,
        'anchor_date': anchor_date,
        'anchor_raw': anchor_raw or '',
        'anchor_display': anchor_date.strftime('%d-%m-%Y') if anchor_date else '',
        'reason': reason,
        'updated_by': updated_by,
        'updated_at': updated_at,
        'is_effective': bool(enabled and anchor_date and (lock_before or lock_after)),
    }


def save_freeze_config(*, enabled: bool, anchor_date: date, lock_before: bool, lock_after: bool, reason: str, updated_by: str, updated_at: str) -> None:
    SystemSetting.set('freeze_data_enabled', '1' if enabled else '0')
    SystemSetting.set('freeze_data_anchor_date', anchor_date.isoformat() if anchor_date else '')
    SystemSetting.set('freeze_data_lock_before', '1' if lock_before else '0')
    SystemSetting.set('freeze_data_lock_after', '1' if lock_after else '0')
    SystemSetting.set('freeze_data_reason', (reason or '').strip())
    SystemSetting.set('freeze_data_updated_by', (updated_by or '').strip())
    SystemSetting.set('freeze_data_updated_at', (updated_at or '').strip())


def is_freeze_protected_request(req: Request, endpoint: str) -> bool:
    if req.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return False
    if not endpoint or endpoint.startswith('static'):
        return False
    if endpoint in FREEZE_EXEMPT_ENDPOINTS:
        return False
    # Non-mutating report/list posts should pass.
    if any(tok in endpoint for tok in FREEZE_SAFE_ENDPOINT_TOKENS):
        return False
    return True


def extract_effective_date(req: Request) -> date:
    payload = {}
    if req.is_json:
        payload = req.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            payload = {}
    elif req.form:
        payload = req.form

    for key in DATE_FIELD_PRIORITY:
        val = payload.get(key)
        dt = parse_date(val)
        if dt:
            return dt

    # Fallback: pick first parseable *date-ish* field.
    for key in payload.keys():
        if 'date' not in str(key).lower():
            continue
        dt = parse_date(payload.get(key))
        if dt:
            return dt

    # If the endpoint doesn't submit a business date, fallback to today's date.
    return pk_date()


def evaluate_freeze(cfg: dict, effective_date: date):
    if not cfg.get('is_effective') or not effective_date:
        return False, ''
    anchor = cfg.get('anchor_date')
    if not anchor:
        return False, ''
    if cfg.get('lock_before') and effective_date <= anchor:
        return True, f'on or before {anchor.strftime("%d-%m-%Y")}'
    if cfg.get('lock_after') and effective_date >= anchor:
        return True, f'on or after {anchor.strftime("%d-%m-%Y")}'
    return False, ''
