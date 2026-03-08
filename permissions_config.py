"""
Hierarchical permission tree: Section -> Page (form/list) -> Actions (buttons).
Used for Role form display and for sidebar/link visibility.
"""
from auth_utils import (
    PERMISSION_MASTER, PERMISSION_ASSIGNMENT, PERMISSION_TRANSFER,
    PERMISSION_DRIVER_STATUS, PERMISSION_TASK_REPORT, PERMISSION_EXPENSES,
    PERMISSION_ACCOUNTS, PERMISSION_REPORTS, PERMISSION_BACKUP,
    PERMISSION_USERS_MANAGE, PERMISSION_DASHBOARD,
)

# Section code -> list of (permission_code, display_name)
PERMISSION_TREE = {
    PERMISSION_DASHBOARD: [
        ('dashboard', 'Dashboard (full)'),
    ],
    PERMISSION_MASTER: [
        ('master', 'Master Data (full)'),
        ('companies_list', 'Companies – List / View'),
        ('companies_add', 'Companies – Add New'),
        ('companies_edit', 'Companies – Edit'),
        ('companies_delete', 'Companies – Delete'),
        ('company_report', 'Companies – Report'),
        ('projects_list', 'Projects – List / View'),
        ('projects_add', 'Projects – Add / Edit'),
        ('project_detail', 'Projects – Detail'),
        ('districts_list', 'Districts – List / View'),
        ('districts_add', 'Districts – Add / Edit'),
        ('vehicles_list', 'Vehicles – List / View'),
        ('vehicles_add', 'Vehicles – Add / Edit'),
        ('parking_list', 'Parking Stations – List / View'),
        ('parking_add', 'Parking – Add / Edit'),
        ('drivers_list', 'Drivers – List / View'),
        ('drivers_add', 'Drivers – Add / Edit'),
        ('employees_list', 'Employees – List / View'),
        ('employees_add', 'Employees – Add / Edit'),
        ('driver_post_list', 'Designations – List / View'),
        ('driver_post_add', 'Designations – Add / Edit'),
        ('party_list', 'Parties – List / View'),
        ('party_add', 'Parties – Add / Edit'),
        ('product_list', 'Products – List / View'),
        ('product_add', 'Products – Add / Edit'),
    ],
    PERMISSION_ASSIGNMENT: [
        ('assignment', 'Assignment (full)'),
        ('assign_project_to_company', 'Project to Company'),
        ('assign_project_to_district', 'District to Project'),
        ('assign_vehicle_to_district', 'Vehicle to District'),
        ('assign_vehicle_to_parking', 'Vehicle to Parking'),
        ('assign_driver_to_vehicle', 'Driver to Vehicle'),
    ],
    PERMISSION_TRANSFER: [
        ('transfer', 'Transfer (full)'),
        ('project_transfers', 'Project Transfer'),
        ('vehicle_transfers', 'Vehicle Transfer'),
        ('driver_transfers', 'Driver Transfer'),
    ],
    PERMISSION_DRIVER_STATUS: [
        ('driver_status', 'Driver Status (full)'),
        ('driver_job_left', 'Resignation / Exit'),
        ('driver_rejoin', 'Re-employment'),
        ('driver_attendance', 'Attendance – All'),
        ('driver_attendance_checkin', 'Check In'),
        ('driver_attendance_checkout', 'Check Out'),
        ('driver_attendance_list', 'Attendance List / Mark'),
        ('penalty_record', 'Penalties'),
    ],
    PERMISSION_TASK_REPORT: [
        ('task_report', 'Task & Logbook (full)'),
        ('task_report_upload', 'Workbook Upload'),
        ('task_report_list', 'Daily Task Report'),
        ('red_task', 'Red Task'),
        ('without_task', 'Movement without Task'),
        ('task_report_logbook', 'Logbook Covers'),
    ],
    PERMISSION_EXPENSES: [
        ('expenses', 'Expenses (full)'),
        ('fuel_expense', 'Fuel'),
        ('oil_expense', 'Oil & Lubricants'),
        ('maintenance_expense', 'Maintenance'),
        ('employee_expense', 'Employee Expenses'),
    ],
    PERMISSION_ACCOUNTS: [
        ('accounts', 'Accounts (full)'),
        ('accounts_quick_payment', 'Payment Voucher'),
        ('accounts_quick_receipt', 'Receipt Voucher'),
        ('accounts_bank_entry', 'Bank Entry'),
        ('accounts_jv', 'Journal Voucher'),
        ('accounts_future_entry', 'Future Dated Entries'),
        ('accounts_balance_sheet', 'Balance Sheet'),
        ('accounts_account_ledger', 'Account Ledger'),
    ],
    PERMISSION_REPORTS: [
        ('reports', 'Reports (full)'),
        ('reports_index', 'Report Centre'),
        ('report_expiry', 'License / CNIC Expiry'),
        ('report_vehicle_summary', 'Vehicle Summary'),
        ('report_project_summary', 'Project Summary'),
        ('report_district_summary', 'District Summary'),
        ('report_parking_utilization', 'Parking Utilization'),
        ('report_vehicle_profile', 'Vehicle Profile'),
        ('report_driver_profile', 'Driver Profile'),
        ('report_ai', 'Create Report with AI'),
        ('driver_attendance_report', 'Attendance Report'),
        ('activity_log_report', 'Activity Log'),
        ('activity_logs_geo_report', 'Activity Logs Geo'),
    ],
    PERMISSION_BACKUP: [
        ('backup', 'Backup'),
    ],
    PERMISSION_USERS_MANAGE: [
        ('users_manage', 'User & Role Management (full)'),
        ('user_list', 'Users – List / Sync'),
        ('user_add', 'Users – Add'),
        ('user_edit', 'Users – Edit'),
        ('role_list', 'Roles – List'),
        ('role_add', 'Roles – Add'),
        ('role_edit', 'Roles – Edit'),
        ('form_control', 'Setting'),
        ('notification_list', 'Notifications – List / View'),
        ('notification_add', 'Notifications – Create'),
        ('whats_new', "What's New"),
    ],
}

SECTION_LABELS = {
    PERMISSION_DASHBOARD: 'Dashboard',
    PERMISSION_MASTER: 'Master Data',
    PERMISSION_ASSIGNMENT: 'Assignments',
    PERMISSION_TRANSFER: 'Transfers',
    PERMISSION_DRIVER_STATUS: 'Workforce & Attendance',
    PERMISSION_TASK_REPORT: 'Task & Logbook',
    PERMISSION_EXPENSES: 'Expense Management',
    PERMISSION_ACCOUNTS: 'Finance',
    PERMISSION_REPORTS: 'Reports & Analytics',
    PERMISSION_BACKUP: 'Backup',
    PERMISSION_USERS_MANAGE: 'Administration',
}

# Permission code -> list of required permission codes (e.g. Add New requires List/View so user doesn't get error)
PERMISSION_DEPENDENCIES = {
    'companies_add': ['companies_list'],
    'companies_edit': ['companies_list'],
    'companies_delete': ['companies_list'],
    'company_report': ['companies_list'],
    'projects_add': ['projects_list'],
    'project_detail': ['projects_list'],
    'districts_add': ['districts_list'],
    'vehicles_add': ['vehicles_list'],
    'parking_add': ['parking_list'],
    'drivers_add': ['drivers_list'],
    'employees_add': ['employees_list'],
    'driver_post_add': ['driver_post_list'],
    'party_add': ['party_list'],
    'product_add': ['product_list'],
    'user_add': ['user_list'],
    'user_edit': ['user_list'],
    'role_add': ['role_list'],
    'role_edit': ['role_list'],
    'notification_add': ['notification_list'],
}

# Section -> list of (page_label, list of (code, display_name)) for hierarchical UI (Section → Page → Buttons)
SECTION_PAGE_GROUPS = {
    PERMISSION_DASHBOARD: [
        ('Dashboard', [('dashboard', 'Dashboard (full)')]),
    ],
    PERMISSION_MASTER: [
        ('Master Data (full)', [('master', 'Master Data (full)')]),
        ('Companies', [
            ('companies_list', 'List / View'),
            ('companies_add', 'Add New'),
            ('companies_edit', 'Edit'),
            ('companies_delete', 'Delete'),
            ('company_report', 'Report'),
        ]),
        ('Projects', [
            ('projects_list', 'List / View'),
            ('projects_add', 'Add / Edit'),
            ('project_detail', 'Detail'),
        ]),
        ('Districts', [
            ('districts_list', 'List / View'),
            ('districts_add', 'Add / Edit'),
        ]),
        ('Vehicles', [
            ('vehicles_list', 'List / View'),
            ('vehicles_add', 'Add / Edit'),
        ]),
        ('Parking Stations', [
            ('parking_list', 'List / View'),
            ('parking_add', 'Add / Edit'),
        ]),
        ('Designations', [
            ('driver_post_list', 'List / View'),
            ('driver_post_add', 'Add / Edit'),
        ]),
        ('Employees', [
            ('employees_list', 'List / View'),
            ('employees_add', 'Add / Edit'),
        ]),
        ('Drivers', [
            ('drivers_list', 'List / View'),
            ('drivers_add', 'Add / Edit'),
        ]),
        ('Parties', [
            ('party_list', 'List / View'),
            ('party_add', 'Add / Edit'),
        ]),
        ('Products', [
            ('product_list', 'List / View'),
            ('product_add', 'Add / Edit'),
        ]),
    ],
    PERMISSION_ASSIGNMENT: [
        ('Assignment (full)', [('assignment', 'Assignment (full)')]),
        ('Project to Company', [('assign_project_to_company', 'Project to Company')]),
        ('District to Project', [('assign_project_to_district', 'District to Project')]),
        ('Vehicle to District', [('assign_vehicle_to_district', 'Vehicle to District')]),
        ('Vehicle to Parking', [('assign_vehicle_to_parking', 'Vehicle to Parking')]),
        ('Driver to Vehicle', [('assign_driver_to_vehicle', 'Driver to Vehicle')]),
    ],
    PERMISSION_TRANSFER: [
        ('Transfer (full)', [('transfer', 'Transfer (full)')]),
        ('Project Transfer', [('project_transfers', 'Project Transfer')]),
        ('Vehicle Transfer', [('vehicle_transfers', 'Vehicle Transfer')]),
        ('Driver Transfer', [('driver_transfers', 'Driver Transfer')]),
    ],
    PERMISSION_DRIVER_STATUS: [
        ('Driver Status (full)', [('driver_status', 'Driver Status (full)')]),
        ('Resignation / Exit', [('driver_job_left', 'Resignation / Exit')]),
        ('Re-employment', [('driver_rejoin', 'Re-employment')]),
        ('Attendance', [
            ('driver_attendance', 'Attendance – All'),
            ('driver_attendance_checkin', 'Check In'),
            ('driver_attendance_checkout', 'Check Out'),
            ('driver_attendance_list', 'Attendance List / Mark'),
        ]),
        ('Penalties', [('penalty_record', 'Penalties')]),
    ],
    PERMISSION_TASK_REPORT: [
        ('Task & Logbook (full)', [('task_report', 'Task & Logbook (full)')]),
        ('Workbook Upload', [('task_report_upload', 'Workbook Upload')]),
        ('Daily Task Report', [('task_report_list', 'Daily Task Report')]),
        ('Red Task', [('red_task', 'Red Task')]),
        ('Movement without Task', [('without_task', 'Movement without Task')]),
        ('Logbook Covers', [('task_report_logbook', 'Logbook Covers')]),
    ],
    PERMISSION_EXPENSES: [
        ('Expenses (full)', [('expenses', 'Expenses (full)')]),
        ('Fuel', [('fuel_expense', 'Fuel')]),
        ('Oil & Lubricants', [('oil_expense', 'Oil & Lubricants')]),
        ('Maintenance', [('maintenance_expense', 'Maintenance')]),
        ('Employee Expenses', [('employee_expense', 'Employee Expenses')]),
    ],
    PERMISSION_ACCOUNTS: [
        ('Accounts (full)', [('accounts', 'Accounts (full)')]),
        ('Payment Voucher', [('accounts_quick_payment', 'Payment Voucher')]),
        ('Receipt Voucher', [('accounts_quick_receipt', 'Receipt Voucher')]),
        ('Bank Entry', [('accounts_bank_entry', 'Bank Entry')]),
        ('Journal Voucher', [('accounts_jv', 'Journal Voucher')]),
        ('Future Dated Entries', [('accounts_future_entry', 'Future Dated Entries')]),
        ('Balance Sheet', [('accounts_balance_sheet', 'Balance Sheet')]),
        ('Account Ledger', [('accounts_account_ledger', 'Account Ledger')]),
    ],
    PERMISSION_REPORTS: [
        ('Reports (full)', [('reports', 'Reports (full)')]),
        ('Report Centre', [('reports_index', 'Report Centre')]),
        ('License / CNIC Expiry', [('report_expiry', 'License / CNIC Expiry')]),
        ('Vehicle Summary', [('report_vehicle_summary', 'Vehicle Summary')]),
        ('Project Summary', [('report_project_summary', 'Project Summary')]),
        ('District Summary', [('report_district_summary', 'District Summary')]),
        ('Parking Utilization', [('report_parking_utilization', 'Parking Utilization')]),
        ('Vehicle Profile', [('report_vehicle_profile', 'Vehicle Profile')]),
        ('Driver Profile', [('report_driver_profile', 'Driver Profile')]),
        ('Create Report with AI', [('report_ai', 'Create Report with AI')]),
        ('Attendance Report', [('driver_attendance_report', 'Attendance Report')]),
        ('Activity Log', [('activity_log_report', 'Activity Log')]),
        ('Activity Logs Geo', [('activity_logs_geo_report', 'Activity Logs Geo')]),
    ],
    PERMISSION_BACKUP: [
        ('Backup', [('backup', 'Backup')]),
    ],
    PERMISSION_USERS_MANAGE: [
        ('User & Role Management (full)', [('users_manage', 'User & Role Management (full)')]),
        ('Users', [
            ('user_list', 'List / Sync'),
            ('user_add', 'Add'),
            ('user_edit', 'Edit'),
        ]),
        ('Roles', [
            ('role_list', 'List'),
            ('role_add', 'Add'),
            ('role_edit', 'Edit'),
        ]),
        ('Setting', [('form_control', 'Setting')]),
        ('Notifications', [
            ('notification_list', 'List / View'),
            ('notification_add', 'Create'),
        ]),
        ("What's New", [('whats_new', "What's New")]),
    ],
}

# Page key -> list of permission codes that grant visibility to that sidebar link
# Key = permission code (or short key). User sees link if they have any of these permissions.
PAGE_VISIBLE = {
    # Master Data
    'companies': ['master', 'companies_list', 'companies_add', 'companies_edit', 'companies_delete', 'company_report'],
    'projects': ['master', 'projects_list', 'projects_add', 'project_detail'],
    'districts': ['master', 'districts_list', 'districts_add'],
    'vehicles': ['master', 'vehicles_list', 'vehicles_add'],
    'parking': ['master', 'parking_list', 'parking_add'],
    'drivers': ['master', 'drivers_list', 'drivers_add'],
    'employees': ['master', 'employees_list', 'employees_add'],
    'driver_post': ['master', 'driver_post_list', 'driver_post_add'],
    'party': ['master', 'party_list', 'party_add'],
    'product': ['master', 'product_list', 'product_add'],
    # Assignments
    'assign_project_to_company': ['assignment', 'assign_project_to_company'],
    'assign_project_to_district': ['assignment', 'assign_project_to_district'],
    'assign_vehicle_to_district': ['assignment', 'assign_vehicle_to_district'],
    'assign_vehicle_to_parking': ['assignment', 'assign_vehicle_to_parking'],
    'assign_driver_to_vehicle': ['assignment', 'assign_driver_to_vehicle'],
    # Transfers
    'project_transfers': ['transfer', 'project_transfers'],
    'vehicle_transfers': ['transfer', 'vehicle_transfers'],
    'driver_transfers': ['transfer', 'driver_transfers'],
    # Workforce
    'driver_job_left': ['driver_status', 'driver_job_left'],
    'driver_rejoin': ['driver_status', 'driver_rejoin'],
    'penalty_record': ['driver_status', 'penalty_record'],
    # Attendance
    'driver_attendance_checkin': ['driver_status', 'driver_attendance', 'driver_attendance_checkin'],
    'driver_attendance_checkout': ['driver_status', 'driver_attendance', 'driver_attendance_checkout'],
    'driver_attendance_pending': ['driver_status', 'driver_attendance', 'driver_attendance_list'],
    'driver_attendance_missing_checkout': ['driver_status', 'driver_attendance', 'driver_attendance_list'],
    'driver_attendance_mark': ['driver_status', 'driver_attendance', 'driver_attendance_list'],
    'driver_attendance_bulk_off': ['driver_status', 'driver_attendance', 'driver_attendance_list'],
    'driver_attendance_list': ['driver_status', 'driver_attendance', 'driver_attendance_list'],
    # Task & Logbook
    'task_report_upload': ['task_report', 'task_report_upload'],
    'task_report_list': ['task_report', 'task_report_list'],
    'red_task': ['task_report', 'red_task'],
    'without_task': ['task_report', 'without_task'],
    'task_report_logbook': ['task_report', 'task_report_logbook'],
    # Expense Management
    'fuel_expense': ['expenses', 'fuel_expense'],
    'oil_expense': ['expenses', 'oil_expense'],
    'maintenance_expense': ['expenses', 'maintenance_expense'],
    'employee_expense': ['expenses', 'employee_expense'],
    # Finance
    'accounts_quick_payment': ['accounts', 'accounts_quick_payment'],
    'accounts_quick_receipt': ['accounts', 'accounts_quick_receipt'],
    'accounts_bank_entry': ['accounts', 'accounts_bank_entry'],
    'accounts_jv': ['accounts', 'accounts_jv'],
    'accounts_future_entry': ['accounts', 'accounts_future_entry'],
    'accounts_balance_sheet': ['accounts', 'accounts_balance_sheet'],
    'accounts_account_ledger': ['accounts', 'accounts_account_ledger'],
    # Reports
    'reports_index': ['reports', 'reports_index'],
    'report_company_profile': ['reports', 'reports_index'],
    'driver_attendance_report': ['reports', 'driver_attendance_report'],
    'report_expiry': ['reports', 'report_expiry'],
    'report_vehicle_summary': ['reports', 'report_vehicle_summary'],
    'report_project_summary': ['reports', 'report_project_summary'],
    'report_district_summary': ['reports', 'report_district_summary'],
    'report_parking_utilization': ['reports', 'report_parking_utilization'],
    'report_ai': ['reports', 'report_ai'],
    'activity_log_report': ['reports', 'activity_log_report'],
    'activity_logs_geo_report': ['reports', 'activity_logs_geo_report'],
    'report_vehicle_profile': ['reports', 'report_vehicle_profile'],
    'report_driver_profile': ['reports', 'report_driver_profile'],
    # Administration
    'user_list': ['users_manage', 'user_list', 'user_add', 'user_edit'],
    'role_list': ['users_manage', 'role_list', 'role_add', 'role_edit'],
    'form_control': ['users_manage', 'form_control'],
    'notification_list': ['notification_list', 'notification_add'],
    'notification_add': ['notification_list', 'notification_add'],
    'whats_new': ['whats_new'],
}


def flatten_permission_tree():
    """Yield (code, name, category) for all permissions (for seeding)."""
    for section_code, items in PERMISSION_TREE.items():
        category = SECTION_LABELS.get(section_code, section_code)
        for code, name in items:
            yield (code, name, category)


def get_permission_tree_with_ids(permission_by_code):
    """Return for template: list of (section_label, list of (id, code, name)). No filter."""
    return get_permission_tree_with_ids_filtered(permission_by_code, allowed_codes=None)


def get_permission_tree_with_ids_filtered(permission_by_code, allowed_codes=None):
    """Same as above but only include permissions in allowed_codes. None = show all (Master)."""
    out = []
    for section_code, items in PERMISSION_TREE.items():
        section_label = SECTION_LABELS.get(section_code, section_code)
        rows = []
        for code, name in items:
            if allowed_codes is not None and code not in allowed_codes:
                continue
            p = permission_by_code.get(code)
            if p:
                rows.append((p.id, p.code, name))
        if rows:
            out.append((section_label, rows))
    return out


def get_permission_tree_grouped_filtered(permission_by_code, allowed_codes=None):
    """Hierarchical tree for role form: Section → Page → Buttons. Returns (section_label, [(page_label, [(id, code, name)]), ...])."""
    out = []
    for section_code, page_list in SECTION_PAGE_GROUPS.items():
        section_label = SECTION_LABELS.get(section_code, section_code)
        pages_out = []
        for page_label, items in page_list:
            rows = []
            for code, name in items:
                if allowed_codes is not None and code not in allowed_codes:
                    continue
                p = permission_by_code.get(code)
                if p:
                    rows.append((p.id, p.code, name))
            if rows:
                pages_out.append((page_label, rows))
        if pages_out:
            out.append((section_label, pages_out))
    return out


def can_see_page(permission_codes, page_key):
    """True if user has any permission that grants visibility to this sidebar page."""
    if not permission_codes:
        return False
    codes = set(permission_codes)
    return bool(codes & set(PAGE_VISIBLE.get(page_key, [])))


def can_see_section(permission_codes, section_code):
    """True if user has section (full access) or any permission under that section."""
    if not permission_codes:
        return False
    codes = set(permission_codes)
    if section_code in codes:
        return True
    items = PERMISSION_TREE.get(section_code, [])
    return bool(codes & set(code for code, _ in items))


def expand_permission_dependencies(permission_codes):
    """Given set of permission codes, add all required dependencies (e.g. companies_list when companies_add is present)."""
    codes = set(permission_codes or [])
    changed = True
    while changed:
        changed = False
        for code in list(codes):
            for req in PERMISSION_DEPENDENCIES.get(code, []):
                if req not in codes:
                    codes.add(req)
                    changed = True
    return codes
