from datetime import date

from flask import Request

from models import SystemSetting
from utils import parse_date, pk_date


# Global always-safe endpoints (auth/session/report/settings).
FREEZE_EXEMPT_ENDPOINTS = {
    'login',
    'logout',
    'app_logout',
    'biometric_login',
    'set_new_password',
    'form_control',
    'freeze_data_settings',
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


# Enterprise-style catalog: operations forms where freeze validation can apply.
FREEZE_FORM_CATALOG = [
    ('Master - Companies', 'company_form'),
    ('Master - Projects', 'project_form'),
    ('Master - Districts', 'district_form'),
    ('Master - Vehicles', 'vehicle_form'),
    ('Master - Drivers', 'driver_form'),
    ('Master - Parking', 'parking_form'),
    ('Master - Employees', 'employee_form'),
    ('Master - Party', 'party_form'),
    ('Master - Product', 'product_form'),
    ('Master - Driver Post', 'driver_post_form'),
    ('Assignment - Employee Assignment', 'employee_assignment_form'),
    ('Assignment - Lifecycle Assign', 'employee_lifecycle_assign'),
    ('Assignment - Lifecycle Deassign', 'employee_lifecycle_deassign'),
    ('Assignment - Lifecycle Left', 'employee_lifecycle_left'),
    ('Assignment - Lifecycle Rejoin', 'employee_lifecycle_rejoin'),
    ('Assignment - Project to Company', 'assign_project_to_company_new'),
    ('Assignment - Project to District', 'assign_project_to_district_new'),
    ('Assignment - Vehicle to District', 'assign_vehicle_to_district_new'),
    ('Assignment - Vehicle to Parking', 'assign_vehicle_to_parking_new'),
    ('Assignment - Driver to Vehicle', 'assign_driver_to_vehicle_new'),
    ('Transfers - Project Transfer', 'project_transfer_new'),
    ('Transfers - Vehicle Transfer', 'vehicle_transfer_new'),
    ('Transfers - Driver Transfer', 'driver_transfer_new'),
    ('Transfers - Driver Job Left', 'driver_job_left_new'),
    ('Transfers - Driver Rejoin', 'driver_rejoin_new'),
    ('Tasks - Daily Task Upload', 'task_report_upload'),
    ('Tasks - Daily Task Form', 'task_report_new'),
    ('Tasks - Red Task Form', 'red_task_new'),
    ('Tasks - Red Task Edit', 'red_task_edit'),
    ('Tasks - Without Task Form', 'without_task_new'),
    ('Tasks - Without Task Edit', 'without_task_edit'),
    ('Tasks - Penalty Record', 'penalty_record_new'),
    ('Tasks - Penalty Record Edit', 'penalty_record_edit'),
    ('Attendance - Checkin', 'driver_attendance_checkin'),
    ('Attendance - Checkout', 'driver_attendance_checkout'),
    ('Attendance - Manual Checkin', 'driver_attendance_manual_checkin'),
    ('Attendance - Manual Checkout', 'driver_attendance_manual_checkout'),
    ('Attendance - Mark Attendance', 'driver_attendance_mark'),
    ('Attendance - Bulk OFF', 'driver_attendance_bulk_off'),
    ('Attendance - Leave Request', 'leave_request_new'),
    ('Finance - Fund Transfer Add', 'fund_transfer_add'),
    ('Finance - Fund Transfer Edit', 'fund_transfer_edit'),
    ('Finance - Payment Voucher', 'accounts_quick_payment'),
    ('Finance - Payment Voucher Edit', 'payment_voucher_edit'),
    ('Finance - Receipt Voucher', 'accounts_quick_receipt'),
    ('Finance - Bank Entry', 'accounts_bank_entry'),
    ('Finance - Journal Voucher', 'accounts_jv'),
    ('Finance - Employee Expense Add', 'employee_expense_form'),
    ('Finance - Employee Expense Edit', 'employee_expense_form_edit'),
    ('Finance - Chart of Accounts Add', 'chart_of_accounts_add'),
    ('Finance - Chart of Accounts Edit', 'chart_of_accounts_edit'),
    ('Finance - Bank Directory Add API', 'bank_directory_add'),
    ('Finance - Bank Directory Update API', 'bank_directory_update'),
    ('Finance - Fund Category Add API', 'ft_categories_add'),
    ('Payroll - Salary Config Form', 'payroll_salary_config_form'),
    ('Payroll - Payroll Generate', 'payroll_generate'),
    ('Payroll - Payroll Bulk Generate', 'payroll_bulk_generate'),
    ('Payroll - Payroll Edit', 'payroll_edit'),
    ('Payroll - Payroll Recalc', 'payroll_recalc_attendance'),
    ('Payroll - Payroll Finalize', 'payroll_finalize'),
    ('Payroll - Payroll Pay', 'payroll_pay'),
    ('Payroll - Driver Bulk Salary', 'payroll_driver_bulk_salary'),
    ('Expenses - Fuel Add', 'fuel_expense_add'),
    ('Expenses - Fuel Edit', 'fuel_expense_edit'),
    ('Expenses - Fuel Delete', 'fuel_expense_delete'),
    ('Expenses - Oil Add', 'oil_expense_form:add'),
    ('Expenses - Oil Edit', 'oil_expense_form:edit'),
    ('Expenses - Oil Delete', 'oil_expense_delete'),
    ('Expenses - Maintenance Add', 'maintenance_expense_form:add'),
    ('Expenses - Maintenance Edit', 'maintenance_expense_form:edit'),
    ('Expenses - Maintenance Delete', 'maintenance_expense_delete'),
    ('Books - Stock Entry', 'book_stock_entry'),
    ('Books - Stock Edit', 'book_stock_edit'),
    ('Books - Book Issue', 'book_issue'),
    ('Books - Book Return', 'book_return'),
    ('Workspace - Select Employee', 'workspace_select_employee'),
    ('Workspace - Party Add', 'workspace_party_new'),
    ('Workspace - Party Edit', 'workspace_party_edit'),
    ('Workspace - Product Add', 'workspace_product_new'),
    ('Workspace - Product Edit', 'workspace_product_edit'),
    ('Workspace - Account Add', 'workspace_account_new'),
    ('Workspace - Account Edit', 'workspace_account_edit'),
    ('Workspace - Expense Add', 'workspace_expense_new'),
    ('Workspace - Expense Edit', 'workspace_expense_edit'),
    ('Workspace - Transfer Add', 'workspace_fund_transfer_new'),
    ('Workspace - Transfer Edit', 'workspace_fund_transfer_edit'),
    ('Workspace - Month Close', 'workspace_month_close'),
]

# Legacy endpoint codes used in older freeze settings. Keep a compatibility map
# so previously saved checkbox selections continue to work after endpoint cleanup.
FREEZE_ENDPOINT_ALIASES = {
    'fuel_expense_new': 'fuel_expense_add',
    'oil_expense_new': 'oil_expense_form:add',
    'oil_expense_edit': 'oil_expense_form:edit',
    'oil_expense_form': ('oil_expense_form:add', 'oil_expense_form:edit'),
    'maintenance_expense_new': 'maintenance_expense_form:add',
    'maintenance_expense_edit': 'maintenance_expense_form:edit',
    'maintenance_expense_form': ('maintenance_expense_form:add', 'maintenance_expense_form:edit'),
}


def _normalize_endpoint_tokens(values: set) -> set:
    normalized = set()
    for ep in set(values or set()):
        mapped = FREEZE_ENDPOINT_ALIASES.get(ep, ep)
        if isinstance(mapped, (tuple, list, set)):
            normalized.update({str(x).strip() for x in mapped if str(x).strip()})
        else:
            val = str(mapped).strip()
            if val:
                normalized.add(val)
    return normalized


def _to_bool(v) -> bool:
    return str(v or '').strip().lower() in ('1', 'true', 'yes', 'y', 'on')


def _parse_csv_set(raw: str) -> set:
    txt = (raw or '').strip()
    if not txt:
        return set()
    return {x.strip() for x in txt.split(',') if x.strip()}


def _set_to_csv(values: set) -> str:
    if not values:
        return ''
    return ','.join(sorted(values))


def get_freeze_form_catalog():
    return list(FREEZE_FORM_CATALOG)


def get_freeze_config() -> dict:
    enabled = _to_bool(SystemSetting.get('freeze_data_enabled', '0'))
    allow_future_entries = _to_bool(SystemSetting.get('freeze_data_allow_future_entries', '1'))
    before_raw = SystemSetting.get('freeze_data_before_date')
    after_raw = SystemSetting.get('freeze_data_after_date')
    before_date = parse_date(before_raw)
    after_date = parse_date(after_raw)
    reason = (SystemSetting.get('freeze_data_reason', '') or '').strip()
    updated_by = (SystemSetting.get('freeze_data_updated_by', '') or '').strip()
    updated_at = (SystemSetting.get('freeze_data_updated_at', '') or '').strip()
    raw_allowed = _parse_csv_set(SystemSetting.get('freeze_data_allowed_endpoints', ''))
    allowed_endpoints = _normalize_endpoint_tokens(raw_allowed)
    catalog_endpoints = {ep for _, ep in FREEZE_FORM_CATALOG}
    effective_allowed = {ep for ep in allowed_endpoints if ep in catalog_endpoints}
    return {
        'enabled': enabled,
        'allow_future_entries': allow_future_entries,
        'future_lock_active': not allow_future_entries,
        'before_date': before_date,
        'before_raw': before_raw or '',
        'before_display': before_date.strftime('%d-%m-%Y') if before_date else '',
        'after_date': after_date,
        'after_raw': after_raw or '',
        'after_display': after_date.strftime('%d-%m-%Y') if after_date else '',
        'reason': reason,
        'updated_by': updated_by,
        'updated_at': updated_at,
        'allowed_endpoints': sorted(effective_allowed),
        'allowed_set': effective_allowed,
        'is_effective': bool((enabled and (before_date or after_date)) or (not allow_future_entries)),
    }


def save_freeze_config(*, enabled: bool, before_date: date, after_date: date, allow_future_entries: bool, reason: str, allowed_endpoints: set, updated_by: str, updated_at: str) -> None:
    SystemSetting.set('freeze_data_enabled', '1' if enabled else '0')
    SystemSetting.set('freeze_data_allow_future_entries', '1' if allow_future_entries else '0')
    SystemSetting.set('freeze_data_before_date', before_date.isoformat() if before_date else '')
    SystemSetting.set('freeze_data_after_date', after_date.isoformat() if after_date else '')
    SystemSetting.set('freeze_data_reason', (reason or '').strip())
    normalized_allowed = _normalize_endpoint_tokens(set(allowed_endpoints or set()))
    SystemSetting.set('freeze_data_allowed_endpoints', _set_to_csv(normalized_allowed))
    SystemSetting.set('freeze_data_updated_by', (updated_by or '').strip())
    SystemSetting.set('freeze_data_updated_at', (updated_at or '').strip())


def get_freeze_request_codes(req: Request, endpoint: str) -> list:
    endpoint = (endpoint or '').strip()
    if not endpoint:
        return []
    codes = []
    view_args = getattr(req, 'view_args', None) or {}
    if endpoint == 'oil_expense_form':
        op = 'edit' if view_args.get('pk') else 'add'
        codes.append(f'oil_expense_form:{op}')
    elif endpoint == 'maintenance_expense_form':
        op = 'edit' if view_args.get('pk') else 'add'
        codes.append(f'maintenance_expense_form:{op}')
    codes.append(endpoint)
    return codes


def is_freeze_protected_request(req: Request, endpoint: str, cfg: dict = None) -> bool:
    if req.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return False
    if not endpoint or endpoint.startswith('static'):
        return False
    if endpoint in FREEZE_EXEMPT_ENDPOINTS:
        return False
    if any(tok in endpoint for tok in FREEZE_SAFE_ENDPOINT_TOKENS):
        return False
    cfg = cfg or {}
    allowed = cfg.get('allowed_set') or set()
    request_codes = get_freeze_request_codes(req, endpoint)
    if any(code in allowed for code in request_codes):
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
        dt = parse_date(payload.get(key))
        if dt:
            return dt

    for key in payload.keys():
        if 'date' not in str(key).lower():
            continue
        dt = parse_date(payload.get(key))
        if dt:
            return dt

    return pk_date()


def evaluate_freeze(cfg: dict, effective_date: date):
    if not effective_date:
        return False, ''
    if not cfg.get('allow_future_entries', True) and effective_date > pk_date():
        return True, 'future dates are disabled'
    if not cfg.get('is_effective'):
        return False, ''
    before_date = cfg.get('before_date')
    after_date = cfg.get('after_date')
    if before_date and effective_date <= before_date:
        return True, f'on or before {before_date.strftime("%d-%m-%Y")}'
    if after_date and effective_date >= after_date:
        return True, f'on or after {after_date.strftime("%d-%m-%Y")}'
    return False, ''
