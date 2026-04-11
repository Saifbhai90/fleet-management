"""
Hierarchical permission tree: Section -> Page (form/list) -> Actions (buttons).
Used for Role form display and for sidebar/link visibility.
"""
from auth_utils import (
    PERMISSION_MASTER, PERMISSION_ASSIGNMENT, PERMISSION_TRANSFER,
    PERMISSION_DRIVER_STATUS, PERMISSION_ATTENDANCE, PERMISSION_TASK_REPORT,
    PERMISSION_EXPENSES, PERMISSION_ACCOUNTS, PERMISSION_WORKSPACE, PERMISSION_PAYROLL, PERMISSION_BOOKS,
    PERMISSION_REPORTS, PERMISSION_BACKUP, PERMISSION_USERS_MANAGE, PERMISSION_DASHBOARD,
)

# Section code -> list of (permission_code, display_name)
PERMISSION_TREE = {
    PERMISSION_DASHBOARD: [
        ('dashboard', 'Dashboard (full)'),
        ('global_search', 'Global Search (Navbar)'),
        ('view_fleet_map', 'Fleet Map – Live GPS'),
        # Dashboard KPI cards
        ('dashboard_card_drivers',     'Dashboard – Active Drivers Card'),
        ('dashboard_card_vehicles',    'Dashboard – Fleet Deployed Card'),
        ('dashboard_card_attendance',  'Dashboard – Today\'s Attendance Card'),
        ('dashboard_card_transfers',   'Dashboard – Today\'s Transfers Card'),
        ('dashboard_card_projects',    'Dashboard – Projects Card'),
        ('dashboard_card_districts',   'Dashboard – Districts Card'),
        ('dashboard_card_parking',     'Dashboard – Parking Stations Card'),
        ('dashboard_card_companies',   'Dashboard – Companies Card'),
        # Dashboard charts & alerts
        ('dashboard_card_fuel',        'Dashboard – Fuel Trend Chart'),
        ('dashboard_card_utilization', 'Dashboard – Vehicle Utilization Chart'),
        ('dashboard_card_finance',     'Dashboard – Financial Health Chart'),
        ('dashboard_card_doc_health',  'Dashboard – Document Health Alert'),
    ],
    PERMISSION_MASTER: [
        ('master', 'Master Data (full)'),
        ('companies_list', 'Companies – List / View'),
        ('companies_add', 'Companies – Add New'),
        ('companies_edit', 'Companies – Edit'),
        ('companies_delete', 'Companies – Delete'),
        ('company_report', 'Companies – Report'),
        ('projects_list', 'Projects – List / View'),
        ('projects_add', 'Projects – Add New'),
        ('projects_edit', 'Projects – Edit'),
        ('projects_delete', 'Projects – Delete'),
        ('project_detail', 'Projects – Detail'),
        ('projects_export', 'Projects – Export'),
        ('projects_print', 'Projects – Print / Preview'),
        ('districts_list', 'Districts – List / View'),
        ('districts_add', 'Districts – Add New'),
        ('districts_edit', 'Districts – Edit'),
        ('districts_delete', 'Districts – Delete'),
        ('vehicles_list', 'Vehicles – List / View'),
        ('vehicles_add', 'Vehicles – Add New'),
        ('vehicles_edit', 'Vehicles – Edit'),
        ('vehicles_delete', 'Vehicles – Delete'),
        ('vehicles_export', 'Vehicles – Export'),
        ('vehicles_print', 'Vehicles – Print / Preview'),
        ('parking_list', 'Parking Stations – List / View'),
        ('parking_add', 'Parking Stations – Add New'),
        ('parking_edit', 'Parking Stations – Edit'),
        ('parking_delete', 'Parking Stations – Delete'),
        ('parking_export', 'Parking Stations – Export'),
        ('parking_print', 'Parking Stations – Print / Preview'),
        ('drivers_list', 'Drivers – List / View'),
        ('drivers_add', 'Drivers – Add New'),
        ('drivers_edit', 'Drivers – Edit'),
        ('drivers_delete', 'Drivers – Delete'),
        ('drivers_export', 'Drivers – Export'),
        ('drivers_print', 'Drivers – Print / Preview'),
        ('employees_list', 'Employees – List / View'),
        ('employees_add', 'Employees – Add New'),
        ('employees_edit', 'Employees – Edit'),
        ('employees_delete', 'Employees – Delete'),
        ('employees_export', 'Employees – Export'),
        ('employees_print', 'Employees – Print / Preview'),
        ('employee_lifecycle', 'Employee Lifecycle – Assign / Deassign / Left / Rejoin'),
        ('vehicles_import', 'Vehicles – Import'),
        ('drivers_import', 'Drivers – Import'),
        ('employees_import', 'Employees – Import'),
        ('parking_import', 'Parking Stations – Import'),
        ('party_import', 'Parties – Import'),
        ('product_import', 'Products – Import'),
        ('view_documents', 'Documents – View Uploaded Files'),
        ('driver_post_list', 'Designations – List / View'),
        ('driver_post_add', 'Designations – Add New'),
        ('driver_post_edit', 'Designations – Edit'),
        ('driver_post_delete', 'Designations – Delete'),
        ('party_list', 'Parties – List / View'),
        ('party_add', 'Parties – Add New'),
        ('party_edit', 'Parties – Edit'),
        ('party_delete', 'Parties – Delete'),
        ('product_list', 'Products – List / View'),
        ('product_add', 'Products – Add New'),
        ('product_edit', 'Products – Edit'),
        ('product_delete', 'Products – Delete'),
    ],
    PERMISSION_ASSIGNMENT: [
        ('assignment', 'Assignment (full)'),
        # Project → Company
        ('assign_project_to_company', 'Project to Company – List / View'),
        ('assign_project_to_company_add', 'Project to Company – Add New'),
        ('assign_project_to_company_edit', 'Project to Company – Edit'),
        ('assign_project_to_company_desassign', 'Project to Company – Deassign'),
        # District → Project
        ('assign_project_to_district', 'District to Project – List / View'),
        ('assign_project_to_district_add', 'District to Project – Add New'),
        ('assign_project_to_district_edit', 'District to Project – Edit'),
        ('assign_project_to_district_desassign', 'District to Project – Deassign'),
        # Vehicle → District
        ('assign_vehicle_to_district', 'Vehicle to District – List / View'),
        ('assign_vehicle_to_district_add', 'Vehicle to District – Add New'),
        ('assign_vehicle_to_district_edit', 'Vehicle to District – Edit'),
        ('assign_vehicle_to_district_desassign', 'Vehicle to District – Deassign'),
        # Vehicle → Parking
        ('assign_vehicle_to_parking', 'Vehicle to Parking – List / View'),
        ('assign_vehicle_to_parking_add', 'Vehicle to Parking – Add New'),
        ('assign_vehicle_to_parking_edit', 'Vehicle to Parking – Edit'),
        ('assign_vehicle_to_parking_desassign', 'Vehicle to Parking – Deassign'),
        # Driver → Vehicle
        ('assign_driver_to_vehicle', 'Driver to Vehicle – List / View'),
        ('assign_driver_to_vehicle_add', 'Driver to Vehicle – Add New'),
        ('assign_driver_to_vehicle_edit', 'Driver to Vehicle – Edit'),
        ('assign_driver_to_vehicle_desassign', 'Driver to Vehicle – Deassign'),
    ],
    PERMISSION_TRANSFER: [
        ('transfer', 'Transfer (full)'),
        # Project Transfer
        ('project_transfers', 'Project Transfer – List / View'),
        ('project_transfers_add', 'Project Transfer – Add New'),
        ('project_transfers_edit', 'Project Transfer – Edit'),
        ('project_transfers_delete', 'Project Transfer – Delete'),
        # Vehicle Transfer
        ('vehicle_transfers', 'Vehicle Transfer – List / View'),
        ('vehicle_transfers_add', 'Vehicle Transfer – Add New'),
        ('vehicle_transfers_edit', 'Vehicle Transfer – Edit'),
        ('vehicle_transfers_delete', 'Vehicle Transfer – Delete'),
        # Driver Transfer
        ('driver_transfers', 'Driver Transfer – List / View'),
        ('driver_transfers_add', 'Driver Transfer – Add New'),
        ('driver_transfers_edit', 'Driver Transfer – Edit'),
        ('driver_transfers_delete', 'Driver Transfer – Delete'),
    ],
    PERMISSION_DRIVER_STATUS: [
        ('driver_status', 'Driver Status (full)'),
        # Resignation / Exit
        ('driver_job_left', 'Resignation / Exit – Add New'),
        ('driver_job_left_list', 'Resignation / Exit – List / View'),
        ('driver_job_left_edit', 'Resignation / Exit – Edit'),
        ('driver_job_left_delete', 'Resignation / Exit – Delete'),
        # Re-employment
        ('driver_rejoin', 'Re-employment – Add New'),
        ('driver_rejoin_list', 'Re-employment – List / View'),
        ('driver_rejoin_view', 'Re-employment – View Detail'),
        # Penalties
        ('penalty_record', 'Penalties – List / View'),
        ('penalty_record_add', 'Penalties – Add New'),
        ('penalty_record_edit', 'Penalties – Edit'),
        ('penalty_record_delete', 'Penalties – Delete'),
    ],
    PERMISSION_ATTENDANCE: [
        ('driver_attendance', 'Attendance – All'),
        ('driver_attendance_checkin', 'Attendance – Check In (GPS + Camera)'),
        ('driver_attendance_checkout', 'Attendance – Check Out (GPS + Camera)'),
        ('driver_attendance_pending', 'Attendance – Missing Check IN'),
        ('driver_attendance_missing_checkout', 'Attendance – Missing Check Out'),
        ('driver_attendance_mark', 'Attendance – Leave / Late / Half Day / Off'),
        ('driver_attendance_bulk_off', 'Attendance – Bulk Off'),
        ('driver_attendance_list', 'Attendance – Attendance List'),
    ],
    PERMISSION_TASK_REPORT: [
        ('task_report', 'Task & Logbook (full)'),
        ('task_report_upload', 'Workbook Upload'),
        # Daily Task Report
        ('task_report_list', 'Daily Task – List / View'),
        ('task_report_add', 'Daily Task – Add New'),
        # Red Task
        ('red_task', 'Red Task – List / View'),
        ('red_task_add', 'Red Task – Add New'),
        ('red_task_edit', 'Red Task – Edit'),
        # Movement without Task
        ('without_task', 'Movement without Task – List / View'),
        ('without_task_add', 'Movement without Task – Add New'),
        ('without_task_edit', 'Movement without Task – Edit'),
        # Logbook
        ('task_report_logbook', 'Logbook Covers – List / View'),
    ],
    PERMISSION_EXPENSES: [
        ('expenses', 'Expenses (full)'),
        # Fuel
        ('fuel_expense', 'Fuel – List / View'),
        ('fuel_expense_add', 'Fuel – Add New'),
        ('fuel_expense_edit', 'Fuel – Edit'),
        ('fuel_expense_delete', 'Fuel – Delete'),
        # Oil & Lubricants
        ('oil_expense', 'Oil & Lubricants – List / View'),
        ('oil_expense_add', 'Oil & Lubricants – Add New'),
        ('oil_expense_edit', 'Oil & Lubricants – Edit'),
        ('oil_expense_delete', 'Oil & Lubricants – Delete'),
        # Maintenance
        ('maintenance_expense', 'Maintenance – List / View'),
        ('maintenance_expense_add', 'Maintenance – Add New'),
        ('maintenance_expense_edit', 'Maintenance – Edit'),
        ('maintenance_expense_delete', 'Maintenance – Delete'),
        # Employee Expenses
        ('employee_expense', 'Employee Expenses – List / View'),
        ('employee_expense_add', 'Employee Expenses – Add New'),
        ('employee_expense_edit', 'Employee Expenses – Edit'),
        ('employee_expense_delete', 'Employee Expenses – Delete'),
    ],
    PERMISSION_ACCOUNTS: [
        ('accounts', 'Accounts (full)'),
        ('wallet_dashboard', 'Wallet Dashboard'),
        ('chart_of_accounts', 'Chart of Accounts'),
        ('fund_transfer', 'Fund Transfer'),
        ('accounts_quick_payment', 'Payment Voucher'),
        ('accounts_quick_receipt', 'Receipt Voucher'),
        ('accounts_bank_entry', 'Bank Entry'),
        ('accounts_jv', 'Journal Voucher'),
        ('accounts_balance_sheet', 'Balance Sheet'),
        ('accounts_account_ledger', 'Account Ledger'),
    ],
    PERMISSION_WORKSPACE: [
        ('workspace', 'Employee Workspace (full)'),
        ('workspace_dashboard', 'Workspace Dashboard'),
        ('workspace_party_list', 'Workspace Parties - List / View'),
        ('workspace_party_add', 'Workspace Parties - Add'),
        ('workspace_party_edit', 'Workspace Parties - Edit'),
        ('workspace_party_delete', 'Workspace Parties - Delete'),
        ('workspace_product_list', 'Workspace Products - List / View'),
        ('workspace_product_add', 'Workspace Products - Add'),
        ('workspace_product_edit', 'Workspace Products - Edit'),
        ('workspace_product_delete', 'Workspace Products - Delete'),
        ('workspace_account_list', 'Workspace COA - List / View'),
        ('workspace_account_add', 'Workspace COA - Add'),
        ('workspace_account_edit', 'Workspace COA - Edit'),
        ('workspace_expense_list', 'Workspace Expenses - List / View'),
        ('workspace_expense_add', 'Workspace Expenses - Add'),
        ('workspace_expense_edit', 'Workspace Expenses - Edit'),
        ('workspace_expense_delete', 'Workspace Expenses - Delete'),
        ('workspace_transfer_list', 'Workspace Transfers - List / View'),
        ('workspace_transfer_add', 'Workspace Transfers - Add'),
        ('workspace_transfer_edit', 'Workspace Transfers - Edit'),
        ('workspace_transfer_delete', 'Workspace Transfers - Delete'),
        ('workspace_ledger', 'Workspace Ledger'),
        ('workspace_month_close', 'Workspace Month Close'),
        ('workspace_reports', 'Workspace Reports'),
    ],
    PERMISSION_PAYROLL: [
        ('payroll', 'Payroll (full)'),
        ('payroll_config_list', 'Salary Config – List / View'),
        ('payroll_config_add', 'Salary Config – Add New'),
        ('payroll_config_edit', 'Salary Config – Edit'),
        ('payroll_config_delete', 'Salary Config – Delete'),
        ('payroll_list', 'Payroll Records – List / View'),
        ('payroll_generate', 'Payroll – Generate / Bulk Generate'),
        ('payroll_edit', 'Payroll – Edit Draft'),
        ('payroll_finalize', 'Payroll – Finalize / Revert'),
        ('payroll_pay', 'Payroll – Record Payment'),
        ('payroll_delete', 'Payroll – Delete'),
        ('payroll_pending', 'Pending Salaries – View'),
    ],
    PERMISSION_BOOKS: [
        ('books', 'Book Management (full)'),
        ('book_inventory_list', 'Book Inventory – List / View'),
        ('book_stock_add', 'Book Inventory – Add / Edit / Mark Lost'),
        ('book_stock_delete', 'Book Inventory – Delete'),
        ('book_issue', 'Issue Book to Vehicle'),
        ('book_assignment_list', 'Book Assignments – List / View'),
        ('book_return', 'Mark Book as Returned'),
        ('book_pending_returns', 'Pending Returns – Report'),
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
        ('driver_attendance_tra_report', 'TRA Attendance Sheet'),
        ('activity_log_report', 'Activity Log'),
        ('activity_logs_geo_report', 'Activity Logs Geo'),
        ('active_drivers_report', 'Active Driver Summary'),
        ('driver_seat_available_report', 'Driver Seat Available'),
        ('oil_change_alert_report', 'Oil Change Alert Report'),
        ('missing_documents_report', 'Missing Documents Report'),
    ],
    PERMISSION_BACKUP: [
        ('backup', 'Backup'),
        ('system_backup', 'Backup – Download / Email / Save'),
    ],
    PERMISSION_USERS_MANAGE: [
        ('users_manage', 'User & Role Management (full)'),
        ('user_list', 'Users – List / Sync'),
        ('user_add', 'Users – Add'),
        ('user_edit', 'Users – Edit'),
        ('user_delete', 'Users – Delete'),
        ('role_list', 'Roles – List'),
        ('role_add', 'Roles – Add'),
        ('role_edit', 'Roles – Edit'),
        ('role_delete', 'Roles – Delete'),
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
    PERMISSION_DRIVER_STATUS: 'Workforce',
    PERMISSION_ATTENDANCE: 'Attendance',
    PERMISSION_TASK_REPORT: 'Task & Logbook',
    PERMISSION_EXPENSES: 'Expense Management',
    PERMISSION_ACCOUNTS: 'Finance',
    PERMISSION_WORKSPACE: 'Employee Workspace',
    PERMISSION_PAYROLL: 'Payroll',
    PERMISSION_BOOKS: 'Book Management',
    PERMISSION_REPORTS: 'Reports & Analytics',
    PERMISSION_BACKUP: 'Backup',
    PERMISSION_USERS_MANAGE: 'Administration',
}

# Section "full" permission code -> SECTION_PAGE_GROUPS key (for login expansion)
SECTION_FULL_TO_GROUP = {
    'dashboard': PERMISSION_DASHBOARD,
    'master': PERMISSION_MASTER,
    'assignment': PERMISSION_ASSIGNMENT,
    'transfer': PERMISSION_TRANSFER,
    'driver_status': PERMISSION_DRIVER_STATUS,
    'driver_attendance': PERMISSION_ATTENDANCE,
    'expenses': PERMISSION_EXPENSES,
    'accounts': PERMISSION_ACCOUNTS,
    'workspace': PERMISSION_WORKSPACE,
    'payroll': PERMISSION_PAYROLL,
    'books': PERMISSION_BOOKS,
    'reports': PERMISSION_REPORTS,
    'backup': PERMISSION_BACKUP,
    'users_manage': PERMISSION_USERS_MANAGE,
}


def expand_login_permissions(perm_codes):
    """
    When a user has a section-level "full" code (e.g. 'assignment'), add all
    granular permission codes from that section so they can access pages and
    assign those permissions to other roles. Returns expanded list (no duplicates).
    """
    if not perm_codes:
        return list(perm_codes) if perm_codes else []
    codes = set(perm_codes)
    for section_full, section_key in SECTION_FULL_TO_GROUP.items():
        if section_full not in codes:
            continue
        for _page_label, items in SECTION_PAGE_GROUPS.get(section_key, []):
            for code, _name in items:
                codes.add(code)
    return list(codes)


# Permission code -> list of required permission codes (e.g. Add New requires List/View so user doesn't get error)
PERMISSION_DEPENDENCIES = {
    'companies_add': ['companies_list'],
    'companies_edit': ['companies_list'],
    'companies_delete': ['companies_list'],
    'company_report': ['companies_list'],
    'projects_add': ['projects_list'],
    'projects_edit': ['projects_list'],
    'projects_delete': ['projects_list'],
    'project_detail': ['projects_list'],
    'projects_export': ['projects_list'],
    'projects_print': ['projects_list'],
    'districts_add': ['districts_list'],
    'districts_edit': ['districts_list'],
    'districts_delete': ['districts_list'],
    'vehicles_add': ['vehicles_list'],
    'vehicles_edit': ['vehicles_list'],
    'vehicles_delete': ['vehicles_list'],
    'vehicles_export': ['vehicles_list'],
    'vehicles_print': ['vehicles_list'],
    'parking_add': ['parking_list'],
    'parking_edit': ['parking_list'],
    'parking_delete': ['parking_list'],
    'parking_export': ['parking_list'],
    'parking_print': ['parking_list'],
    'drivers_add': ['drivers_list'],
    'drivers_edit': ['drivers_list'],
    'drivers_delete': ['drivers_list'],
    'drivers_export': ['drivers_list'],
    'drivers_print': ['drivers_list'],
    'employees_add': ['employees_list'],
    'employees_edit': ['employees_list'],
    'employees_delete': ['employees_list'],
    'employees_export': ['employees_list'],
    'employees_print': ['employees_list'],
    'employee_lifecycle': ['employees_list'],
    # Payroll
    'payroll_config_add': ['payroll_config_list'],
    'payroll_config_edit': ['payroll_config_list'],
    'payroll_config_delete': ['payroll_config_list'],
    'payroll_generate': ['payroll_list'],
    'payroll_edit': ['payroll_list'],
    'payroll_finalize': ['payroll_list'],
    'payroll_pay': ['payroll_list'],
    'payroll_delete': ['payroll_list'],
    'payroll_pending': ['payroll_list'],
    'vehicles_import': ['vehicles_list'],
    'drivers_import': ['drivers_list'],
    'employees_import': ['employees_list'],
    'parking_import': ['parking_list'],
    'party_import': ['party_list'],
    'product_import': ['product_list'],
    'driver_post_add': ['driver_post_list'],
    'driver_post_edit': ['driver_post_list'],
    'driver_post_delete': ['driver_post_list'],
    'party_add': ['party_list'],
    'party_edit': ['party_list'],
    'party_delete': ['party_list'],
    'product_add': ['product_list'],
    'product_edit': ['product_list'],
    'product_delete': ['product_list'],
    # Assignments: List/View per feature, plus granular buttons (no section full auto-add)
    'assign_project_to_company': [],
    'assign_project_to_company_add': ['assign_project_to_company'],
    'assign_project_to_company_edit': ['assign_project_to_company'],
    'assign_project_to_company_desassign': ['assign_project_to_company'],
    'assign_project_to_district': [],
    'assign_project_to_district_add': ['assign_project_to_district'],
    'assign_project_to_district_edit': ['assign_project_to_district'],
    'assign_project_to_district_desassign': ['assign_project_to_district'],
    'assign_vehicle_to_district': [],
    'assign_vehicle_to_district_add': ['assign_vehicle_to_district'],
    'assign_vehicle_to_district_edit': ['assign_vehicle_to_district'],
    'assign_vehicle_to_district_desassign': ['assign_vehicle_to_district'],
    'assign_vehicle_to_parking': [],
    'assign_vehicle_to_parking_add': ['assign_vehicle_to_parking'],
    'assign_vehicle_to_parking_edit': ['assign_vehicle_to_parking'],
    'assign_vehicle_to_parking_desassign': ['assign_vehicle_to_parking'],
    'assign_driver_to_vehicle': [],
    'assign_driver_to_vehicle_add': ['assign_driver_to_vehicle'],
    'assign_driver_to_vehicle_edit': ['assign_driver_to_vehicle'],
    'assign_driver_to_vehicle_desassign': ['assign_driver_to_vehicle'],
    # Transfers – list per feature, buttons depend on list (no section full auto-add)
    'project_transfers': [],
    'project_transfers_add': ['project_transfers'],
    'project_transfers_edit': ['project_transfers'],
    'project_transfers_delete': ['project_transfers'],
    'vehicle_transfers': [],
    'vehicle_transfers_add': ['vehicle_transfers'],
    'vehicle_transfers_edit': ['vehicle_transfers'],
    'vehicle_transfers_delete': ['vehicle_transfers'],
    'driver_transfers': [],
    'driver_transfers_add': ['driver_transfers'],
    'driver_transfers_edit': ['driver_transfers'],
    'driver_transfers_delete': ['driver_transfers'],
    # Workforce / Driver Status – child features independent of section "full"
    'driver_job_left': [],
    'driver_job_left_list': [],
    'driver_job_left_edit': ['driver_job_left_list'],
    'driver_job_left_delete': ['driver_job_left_list'],
    'driver_rejoin': [],
    'driver_rejoin_list': [],
    'driver_rejoin_view': ['driver_rejoin_list'],
    'penalty_record': [],
    'penalty_record_add': ['penalty_record'],
    'penalty_record_edit': ['penalty_record'],
    # Attendance – each action independent; some depend on List only (not "full")
    'driver_attendance_checkin': [],
    'driver_attendance_checkout': [],
    'driver_attendance_pending': ['driver_attendance_list'],
    'driver_attendance_missing_checkout': ['driver_attendance_list'],
    'driver_attendance_mark': ['driver_attendance_list'],
    'driver_attendance_bulk_off': ['driver_attendance_list'],
    'driver_attendance_list': [],
    # Expenses – list per feature, buttons depend on list, which depend on section
    'fuel_expense': ['expenses'],
    'fuel_expense_add': ['fuel_expense'],
    'fuel_expense_edit': ['fuel_expense'],
    'fuel_expense_delete': ['fuel_expense'],
    'oil_expense': ['expenses'],
    'oil_expense_add': ['oil_expense'],
    'oil_expense_edit': ['oil_expense'],
    'oil_expense_delete': ['oil_expense'],
    'maintenance_expense': ['expenses'],
    'maintenance_expense_add': ['maintenance_expense'],
    'maintenance_expense_edit': ['maintenance_expense'],
    'maintenance_expense_delete': ['maintenance_expense'],
    'employee_expense': ['expenses'],
    'employee_expense_add': ['employee_expense'],
    'employee_expense_edit': ['employee_expense'],
    'employee_expense_delete': ['employee_expense'],
    # Employee Workspace
    'workspace_dashboard': ['workspace'],
    'workspace_party_list': ['workspace'],
    'workspace_party_add': ['workspace_party_list'],
    'workspace_party_edit': ['workspace_party_list'],
    'workspace_party_delete': ['workspace_party_list'],
    'workspace_product_list': ['workspace'],
    'workspace_product_add': ['workspace_product_list'],
    'workspace_product_edit': ['workspace_product_list'],
    'workspace_product_delete': ['workspace_product_list'],
    'workspace_account_list': ['workspace'],
    'workspace_account_add': ['workspace_account_list'],
    'workspace_account_edit': ['workspace_account_list'],
    'workspace_expense_list': ['workspace'],
    'workspace_expense_add': ['workspace_expense_list'],
    'workspace_expense_edit': ['workspace_expense_list'],
    'workspace_expense_delete': ['workspace_expense_list'],
    'workspace_transfer_list': ['workspace'],
    'workspace_transfer_add': ['workspace_transfer_list'],
    'workspace_transfer_edit': ['workspace_transfer_list'],
    'workspace_transfer_delete': ['workspace_transfer_list'],
    'workspace_ledger': ['workspace'],
    'workspace_month_close': ['workspace'],
    'workspace_reports': ['workspace'],
    # Task & Logbook – list per feature, buttons depend on list, which depend on section
    'task_report_upload': ['task_report'],
    'task_report_list': ['task_report'],
    'task_report_add': ['task_report_list'],
    'red_task': ['task_report'],
    'red_task_add': ['red_task'],
    'red_task_edit': ['red_task'],
    'without_task': ['task_report'],
    'without_task_add': ['without_task'],
    'without_task_edit': ['without_task'],
    'task_report_logbook': ['task_report'],
    'user_add': ['user_list'],
    'user_edit': ['user_list'],
    'user_delete': ['user_list'],
    'role_add': ['role_list'],
    'role_edit': ['role_list'],
    'role_delete': ['role_list'],
    'notification_add': ['notification_list'],
    # Security lockdown additions
    'system_backup': ['backup'],
    'view_documents': [],
    # Dashboard features: standalone – no cross-module dependencies
    # (Route guard handles dashboard access; expand_login_permissions handles 'dashboard' full expansion)
    'global_search': [],
    'view_fleet_map': [],
    # Dashboard KPI cards: standalone visibility permissions – granting a card does NOT
    # auto-grant 'dashboard' (which would expand to ALL dashboard features via SECTION_FULL_TO_GROUP)
    'dashboard_card_drivers':     [],
    'dashboard_card_vehicles':    [],
    'dashboard_card_attendance':  [],
    'dashboard_card_transfers':   [],
    'dashboard_card_projects':    [],
    'dashboard_card_districts':   [],
    'dashboard_card_parking':     [],
    'dashboard_card_companies':   [],
    'dashboard_card_fuel':        [],
    'dashboard_card_utilization': [],
    'dashboard_card_finance':     [],
    'dashboard_card_doc_health':  [],
    'penalty_record_delete': ['penalty_record'],
}

# Section -> list of (page_label, list of (code, display_name)) for hierarchical UI (Section → Page → Buttons)
SECTION_PAGE_GROUPS = {
    PERMISSION_DASHBOARD: [
        ('Dashboard', [('dashboard', 'Dashboard (full)')]),
        ('Dashboard Features', [
            ('global_search', 'Global Search (Navbar)'),
            ('view_fleet_map', 'Fleet Map – Live GPS'),
        ]),
        ('Dashboard Cards – KPI', [
            ('dashboard_card_drivers',    'Active Drivers Card'),
            ('dashboard_card_vehicles',   'Fleet Deployed Card'),
            ('dashboard_card_attendance', "Today's Attendance Card"),
            ('dashboard_card_transfers',  "Today's Transfers Card"),
            ('dashboard_card_projects',   'Projects Card'),
            ('dashboard_card_districts',  'Districts Card'),
            ('dashboard_card_parking',    'Parking Stations Card'),
            ('dashboard_card_companies',  'Companies Card'),
        ]),
        ('Dashboard Cards – Charts & Alerts', [
            ('dashboard_card_fuel',        'Fuel Trend Chart'),
            ('dashboard_card_utilization', 'Vehicle Utilization Chart'),
            ('dashboard_card_finance',     'Financial Health Chart'),
            ('dashboard_card_doc_health',  'Document Health Alert'),
        ]),
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
            ('projects_add', 'Add New'),
            ('projects_edit', 'Edit'),
            ('projects_delete', 'Delete'),
            ('project_detail', 'Detail'),
            ('projects_export', 'Export'),
            ('projects_print', 'Print / Preview'),
        ]),
        ('Districts', [
            ('districts_list', 'List / View'),
            ('districts_add', 'Add New'),
            ('districts_edit', 'Edit'),
            ('districts_delete', 'Delete'),
        ]),
        ('Vehicles', [
            ('vehicles_list', 'List / View'),
            ('vehicles_add', 'Add New'),
            ('vehicles_edit', 'Edit'),
            ('vehicles_delete', 'Delete'),
            ('vehicles_import', 'Import'),
            ('vehicles_export', 'Export'),
            ('vehicles_print', 'Print / Preview'),
        ]),
        ('Parking Stations', [
            ('parking_list', 'List / View'),
            ('parking_add', 'Add New'),
            ('parking_edit', 'Edit'),
            ('parking_delete', 'Delete'),
            ('parking_import', 'Import'),
            ('parking_export', 'Export'),
            ('parking_print', 'Print / Preview'),
        ]),
        ('Designations', [
            ('driver_post_list', 'List / View'),
            ('driver_post_add', 'Add New'),
            ('driver_post_edit', 'Edit'),
            ('driver_post_delete', 'Delete'),
        ]),
        ('Employees', [
            ('employees_list', 'List / View'),
            ('employees_add', 'Add New'),
            ('employees_edit', 'Edit'),
            ('employees_delete', 'Delete'),
            ('employees_import', 'Import'),
            ('employees_export', 'Export'),
            ('employees_print', 'Print / Preview'),
            ('employee_lifecycle', 'Lifecycle (Assign/Deassign/Left/Rejoin)'),
        ]),
        ('Drivers', [
            ('drivers_list', 'List / View'),
            ('drivers_add', 'Add New'),
            ('drivers_edit', 'Edit'),
            ('drivers_delete', 'Delete'),
            ('drivers_import', 'Import'),
            ('drivers_export', 'Export'),
            ('drivers_print', 'Print / Preview'),
        ]),
        ('Parties', [
            ('party_list', 'List / View'),
            ('party_add', 'Add New'),
            ('party_edit', 'Edit'),
            ('party_delete', 'Delete'),
            ('party_import', 'Import'),
        ]),
        ('Products', [
            ('product_list', 'List / View'),
            ('product_add', 'Add New'),
            ('product_edit', 'Edit'),
            ('product_delete', 'Delete'),
            ('product_import', 'Import'),
        ]),
        ('System', [
            ('view_documents', 'Documents – View Uploaded Files'),
        ]),
    ],
    PERMISSION_ASSIGNMENT: [
        ('Assignment (full)', [('assignment', 'Assignment (full)')]),
        ('Project to Company', [
            ('assign_project_to_company', 'List / View'),
            ('assign_project_to_company_add', 'Add New'),
            ('assign_project_to_company_edit', 'Edit'),
            ('assign_project_to_company_desassign', 'Deassign'),
        ]),
        ('District to Project', [
            ('assign_project_to_district', 'List / View'),
            ('assign_project_to_district_add', 'Add New'),
            ('assign_project_to_district_edit', 'Edit'),
            ('assign_project_to_district_desassign', 'Deassign'),
        ]),
        ('Vehicle to District', [
            ('assign_vehicle_to_district', 'List / View'),
            ('assign_vehicle_to_district_add', 'Add New'),
            ('assign_vehicle_to_district_edit', 'Edit'),
            ('assign_vehicle_to_district_desassign', 'Deassign'),
        ]),
        ('Vehicle to Parking', [
            ('assign_vehicle_to_parking', 'List / View'),
            ('assign_vehicle_to_parking_add', 'Add New'),
            ('assign_vehicle_to_parking_edit', 'Edit'),
            ('assign_vehicle_to_parking_desassign', 'Deassign'),
        ]),
        ('Driver to Vehicle', [
            ('assign_driver_to_vehicle', 'List / View'),
            ('assign_driver_to_vehicle_add', 'Add New'),
            ('assign_driver_to_vehicle_edit', 'Edit'),
            ('assign_driver_to_vehicle_desassign', 'Deassign'),
        ]),
    ],
    PERMISSION_TRANSFER: [
        ('Transfer (full)', [('transfer', 'Transfer (full)')]),
        ('Project Transfer', [
            ('project_transfers', 'List / View'),
            ('project_transfers_add', 'Add New'),
            ('project_transfers_edit', 'Edit'),
            ('project_transfers_delete', 'Delete'),
        ]),
        ('Vehicle Transfer', [
            ('vehicle_transfers', 'List / View'),
            ('vehicle_transfers_add', 'Add New'),
            ('vehicle_transfers_edit', 'Edit'),
            ('vehicle_transfers_delete', 'Delete'),
        ]),
        ('Driver Transfer', [
            ('driver_transfers', 'List / View'),
            ('driver_transfers_add', 'Add New'),
            ('driver_transfers_edit', 'Edit'),
            ('driver_transfers_delete', 'Delete'),
        ]),
    ],
    PERMISSION_DRIVER_STATUS: [
        ('Driver Status (full)', [('driver_status', 'Driver Status (full)')]),
        ('Resignation / Exit', [
            ('driver_job_left', 'Add New'),
            ('driver_job_left_list', 'List / View'),
            ('driver_job_left_edit', 'Edit'),
            ('driver_job_left_delete', 'Delete'),
        ]),
        ('Re-employment', [
            ('driver_rejoin', 'Add New'),
            ('driver_rejoin_list', 'List / View'),
            ('driver_rejoin_view', 'View Detail'),
        ]),
        ('Penalties', [
            ('penalty_record', 'List / View'),
            ('penalty_record_add', 'Add New'),
            ('penalty_record_edit', 'Edit'),
            ('penalty_record_delete', 'Delete'),
        ]),
    ],
    PERMISSION_ATTENDANCE: [
        ('Attendance (full)', [('driver_attendance', 'Attendance – All')]),
        ('Check In (GPS + Camera)', [
            ('driver_attendance_checkin', 'Check In (GPS + Camera)'),
        ]),
        ('Check Out (GPS + Camera)', [
            ('driver_attendance_checkout', 'Check Out (GPS + Camera)'),
        ]),
        ('Missing Check IN', [
            ('driver_attendance_pending', 'Missing Check IN'),
        ]),
        ('Missing Check Out', [
            ('driver_attendance_missing_checkout', 'Missing Check Out'),
        ]),
        ('Leave / Late / Half Day / Off', [
            ('driver_attendance_mark', 'Leave / Late / Half Day / Off'),
        ]),
        ('Bulk Off', [
            ('driver_attendance_bulk_off', 'Bulk Off'),
        ]),
        ('Attendance List', [
            ('driver_attendance_list', 'Attendance List'),
        ]),
    ],
    PERMISSION_TASK_REPORT: [
        ('Task & Logbook (full)', [('task_report', 'Task & Logbook (full)')]),
        ('Workbook Upload', [
            ('task_report_upload', 'Workbook Upload'),
        ]),
        ('Daily Task Report', [
            ('task_report_list', 'List / View'),
            ('task_report_add', 'Add New'),
        ]),
        ('Red Task', [
            ('red_task', 'List / View'),
            ('red_task_add', 'Add New'),
            ('red_task_edit', 'Edit'),
        ]),
        ('Movement without Task', [
            ('without_task', 'List / View'),
            ('without_task_add', 'Add New'),
            ('without_task_edit', 'Edit'),
        ]),
        ('Logbook Covers', [
            ('task_report_logbook', 'List / View'),
        ]),
    ],
    PERMISSION_EXPENSES: [
        ('Expenses (full)', [('expenses', 'Expenses (full)')]),
        ('Fuel', [
            ('fuel_expense', 'List / View'),
            ('fuel_expense_add', 'Add New'),
            ('fuel_expense_edit', 'Edit'),
            ('fuel_expense_delete', 'Delete'),
        ]),
        ('Oil & Lubricants', [
            ('oil_expense', 'List / View'),
            ('oil_expense_add', 'Add New'),
            ('oil_expense_edit', 'Edit'),
            ('oil_expense_delete', 'Delete'),
        ]),
        ('Maintenance', [
            ('maintenance_expense', 'List / View'),
            ('maintenance_expense_add', 'Add New'),
            ('maintenance_expense_edit', 'Edit'),
            ('maintenance_expense_delete', 'Delete'),
        ]),
        ('Employee Expenses', [
            ('employee_expense', 'List / View'),
            ('employee_expense_add', 'Add New'),
            ('employee_expense_edit', 'Edit'),
            ('employee_expense_delete', 'Delete'),
        ]),
    ],
    PERMISSION_ACCOUNTS: [
        ('Accounts (full)', [('accounts', 'Accounts (full)')]),
        ('Wallet Dashboard', [('wallet_dashboard', 'Wallet Dashboard')]),
        ('Chart of Accounts', [('chart_of_accounts', 'Chart of Accounts')]),
        ('Fund Transfer', [('fund_transfer', 'Fund Transfer')]),
        ('Payment Voucher', [('accounts_quick_payment', 'Payment Voucher')]),
        ('Receipt Voucher', [('accounts_quick_receipt', 'Receipt Voucher')]),
        ('Bank Entry', [('accounts_bank_entry', 'Bank Entry')]),
        ('Journal Voucher', [('accounts_jv', 'Journal Voucher')]),
        ('Balance Sheet', [('accounts_balance_sheet', 'Balance Sheet')]),
        ('Account Ledger', [('accounts_account_ledger', 'Account Ledger')]),
    ],
    PERMISSION_WORKSPACE: [
        ('Workspace (full)', [('workspace', 'Employee Workspace (full)')]),
        ('Dashboard', [('workspace_dashboard', 'Workspace Dashboard')]),
        ('Parties', [
            ('workspace_party_list', 'List / View'),
            ('workspace_party_add', 'Add'),
            ('workspace_party_edit', 'Edit'),
            ('workspace_party_delete', 'Delete'),
        ]),
        ('Products', [
            ('workspace_product_list', 'List / View'),
            ('workspace_product_add', 'Add'),
            ('workspace_product_edit', 'Edit'),
            ('workspace_product_delete', 'Delete'),
        ]),
        ('Workspace COA', [
            ('workspace_account_list', 'List / View'),
            ('workspace_account_add', 'Add'),
            ('workspace_account_edit', 'Edit'),
        ]),
        ('Expenses', [
            ('workspace_expense_list', 'List / View'),
            ('workspace_expense_add', 'Add'),
            ('workspace_expense_edit', 'Edit'),
            ('workspace_expense_delete', 'Delete'),
        ]),
        ('Transfers', [
            ('workspace_transfer_list', 'List / View'),
            ('workspace_transfer_add', 'Add'),
            ('workspace_transfer_edit', 'Edit'),
            ('workspace_transfer_delete', 'Delete'),
        ]),
        ('Reports & Close', [
            ('workspace_ledger', 'Ledger'),
            ('workspace_month_close', 'Month Close'),
            ('workspace_reports', 'Reports'),
        ]),
    ],
    PERMISSION_PAYROLL: [
        ('Payroll (full)', [('payroll', 'Payroll (full)')]),
        ('Salary Configuration', [
            ('payroll_config_list', 'List / View'),
            ('payroll_config_add', 'Add New'),
            ('payroll_config_edit', 'Edit'),
            ('payroll_config_delete', 'Delete'),
        ]),
        ('Payroll Records', [
            ('payroll_list', 'List / View'),
            ('payroll_generate', 'Generate / Bulk Generate'),
            ('payroll_edit', 'Edit Draft'),
            ('payroll_finalize', 'Finalize / Revert'),
            ('payroll_pay', 'Record Payment'),
            ('payroll_delete', 'Delete'),
        ]),
        ('Pending Salaries', [
            ('payroll_pending', 'View Pending'),
        ]),
    ],
    PERMISSION_BOOKS: [
        ('Book Management (full)', [('books', 'Book Management (full)')]),
        ('Book Inventory', [
            ('book_inventory_list', 'List / View'),
            ('book_stock_add', 'Add / Edit / Mark Lost'),
            ('book_stock_delete', 'Delete'),
        ]),
        ('Book Issuance', [
            ('book_issue', 'Issue Book to Vehicle'),
            ('book_assignment_list', 'Assignments – List / View'),
            ('book_return', 'Mark as Returned'),
        ]),
        ('Pending Returns', [
            ('book_pending_returns', 'Pending Returns Report'),
        ]),
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
        ('TRA Attendance Sheet', [('driver_attendance_tra_report', 'TRA Attendance Sheet')]),
        ('Active Driver Summary', [('active_drivers_report', 'Active Driver Summary')]),
        ('Driver Seat Available', [('driver_seat_available_report', 'Driver Seat Available')]),
        ('Oil Change Alert Report', [('oil_change_alert_report', 'Oil Change Alert Report')]),
        ('Missing Documents Report', [('missing_documents_report', 'Missing Documents Report')]),
        ('Activity Log', [('activity_log_report', 'Activity Log')]),
        ('Activity Logs Geo', [('activity_logs_geo_report', 'Activity Logs Geo')]),
    ],
    PERMISSION_BACKUP: [
        ('Backup', [
            ('backup', 'Backup'),
            ('system_backup', 'Download / Email / Save'),
        ]),
    ],
    PERMISSION_USERS_MANAGE: [
        ('User & Role Management (full)', [('users_manage', 'User & Role Management (full)')]),
        ('Users', [
            ('user_list', 'List / Sync'),
            ('user_add', 'Add'),
            ('user_edit', 'Edit'),
            ('user_delete', 'Delete'),
        ]),
        ('Roles', [
            ('role_list', 'List'),
            ('role_add', 'Add'),
            ('role_edit', 'Edit'),
            ('role_delete', 'Delete'),
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
    # Per-action visibility keys for use in templates (buttons on list screens)
    'companies_add': ['companies_add'],
    'companies_edit': ['companies_edit'],
    'companies_delete': ['companies_delete'],
    'company_report': ['company_report'],
    'projects_add': ['projects_add'],
    'projects_edit': ['projects_edit'],
    'projects_delete': ['projects_delete'],
    'districts': ['master', 'districts_list', 'districts_add'],
    'vehicles': ['master', 'vehicles_list', 'vehicles_add'],
    'parking': ['master', 'parking_list', 'parking_add'],
    'drivers': ['master', 'drivers_list', 'drivers_add'],
    'employees': ['master', 'employees_list', 'employees_add'],
    'employees_add': ['employees_add'],
    'employees_edit': ['employees_edit'],
    'employees_delete': ['employees_delete'],
    'driver_post': ['master', 'driver_post_list', 'driver_post_add'],
    'driver_post_add': ['driver_post_add'],
    'driver_post_edit': ['driver_post_edit'],
    'driver_post_delete': ['driver_post_delete'],
    'party': ['master', 'party_list', 'party_add'],
    'product': ['master', 'product_list', 'product_add'],
    # Per-action visibility keys for list buttons (Add/Edit/Delete/etc.)
    'districts_add': ['districts_add'],
    'districts_edit': ['districts_edit'],
    'districts_delete': ['districts_delete'],
    'vehicles_add': ['vehicles_add'],
    'vehicles_edit': ['vehicles_edit'],
    'vehicles_delete': ['vehicles_delete'],
    'parking_add': ['parking_add'],
    'parking_edit': ['parking_edit'],
    'parking_delete': ['parking_delete'],
    'drivers_add': ['drivers_add'],
    'drivers_edit': ['drivers_edit'],
    'drivers_delete': ['drivers_delete'],
    # Per-action visibility keys for Export / Print buttons
    'vehicles_export': ['vehicles_export', 'master'],
    'vehicles_print': ['vehicles_print', 'master'],
    'projects_export': ['projects_export', 'master'],
    'projects_print': ['projects_print', 'master'],
    'parking_export': ['parking_export', 'master'],
    'parking_print': ['parking_print', 'master'],
    'drivers_export': ['drivers_export', 'master'],
    'drivers_print': ['drivers_print', 'master'],
    'employees_export': ['employees_export', 'master'],
    'employees_print': ['employees_print', 'master'],
    'employee_lifecycle': ['employee_lifecycle', 'master', 'employees_list'],
    # Per-action visibility keys for Import buttons
    'vehicles_import': ['vehicles_import'],
    'drivers_import': ['drivers_import'],
    'employees_import': ['employees_import'],
    'parking_import': ['parking_import'],
    'party_import': ['party_import'],
    'product_import': ['product_import'],
    # Assignments (sidebar links)
    'assign_project_to_company': ['assignment', 'assign_project_to_company'],
    'assign_project_to_district': ['assignment', 'assign_project_to_district'],
    'assign_vehicle_to_district': ['assignment', 'assign_vehicle_to_district'],
    'assign_vehicle_to_parking': ['assignment', 'assign_vehicle_to_parking'],
    'assign_driver_to_vehicle': ['assignment', 'assign_driver_to_vehicle'],
    # Administration – role actions
    'role_delete': ['role_delete'],
    # Assignments – per-action buttons on list screens
    'assign_project_to_company_add': ['assign_project_to_company_add'],
    'assign_project_to_company_edit': ['assign_project_to_company_edit'],
    'assign_project_to_company_desassign': ['assign_project_to_company_desassign'],
    'assign_project_to_district_add': ['assign_project_to_district_add'],
    'assign_project_to_district_edit': ['assign_project_to_district_edit'],
    'assign_project_to_district_desassign': ['assign_project_to_district_desassign'],
    'assign_vehicle_to_district_add': ['assign_vehicle_to_district_add'],
    'assign_vehicle_to_district_edit': ['assign_vehicle_to_district_edit'],
    'assign_vehicle_to_district_desassign': ['assign_vehicle_to_district_desassign'],
    'assign_vehicle_to_parking_add': ['assign_vehicle_to_parking_add'],
    'assign_vehicle_to_parking_edit': ['assign_vehicle_to_parking_edit'],
    'assign_vehicle_to_parking_desassign': ['assign_vehicle_to_parking_desassign'],
    'assign_driver_to_vehicle_add': ['assign_driver_to_vehicle_add'],
    'assign_driver_to_vehicle_edit': ['assign_driver_to_vehicle_edit'],
    'assign_driver_to_vehicle_desassign': ['assign_driver_to_vehicle_desassign'],
    # Transfers
    'project_transfers': ['transfer', 'project_transfers'],
    'vehicle_transfers': ['transfer', 'vehicle_transfers'],
    'vehicle_transfers_add': ['vehicle_transfers_add'],
    'vehicle_transfers_edit': ['vehicle_transfers_edit'],
    'vehicle_transfers_delete': ['vehicle_transfers_delete'],
    'driver_transfers': ['transfer', 'driver_transfers'],
    'driver_transfers_add': ['driver_transfers_add'],
    'driver_transfers_edit': ['driver_transfers_edit'],
    'driver_transfers_delete': ['driver_transfers_delete'],
    # Workforce
    'driver_job_left': ['driver_status', 'driver_job_left', 'driver_job_left_list'],
    'driver_job_left_add': ['driver_job_left'],
    'driver_rejoin': ['driver_status', 'driver_rejoin', 'driver_rejoin_list'],
    'driver_rejoin_add': ['driver_rejoin'],
    'penalty_record': ['driver_status', 'penalty_record'],
    # Attendance
    'driver_attendance_checkin': ['attendance', 'driver_attendance', 'driver_attendance_checkin'],
    'driver_attendance_checkout': ['attendance', 'driver_attendance', 'driver_attendance_checkout'],
    'driver_attendance_pending': ['attendance', 'driver_attendance', 'driver_attendance_pending'],
    'driver_attendance_missing_checkout': ['attendance', 'driver_attendance', 'driver_attendance_missing_checkout'],
    'driver_attendance_mark': ['attendance', 'driver_attendance', 'driver_attendance_mark'],
    'driver_attendance_bulk_off': ['attendance', 'driver_attendance', 'driver_attendance_bulk_off'],
    'driver_attendance_list': ['attendance', 'driver_attendance', 'driver_attendance_list'],
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
    # Payroll
    'payroll_config_list': ['payroll', 'payroll_config_list'],
    'payroll_config_add': ['payroll', 'payroll_config_add'],
    'payroll_config_edit': ['payroll', 'payroll_config_edit'],
    'payroll_config_delete': ['payroll', 'payroll_config_delete'],
    'payroll_list': ['payroll', 'payroll_list'],
    'payroll_generate': ['payroll', 'payroll_generate'],
    'payroll_edit': ['payroll', 'payroll_edit'],
    'payroll_finalize': ['payroll', 'payroll_finalize'],
    'payroll_pay': ['payroll', 'payroll_pay'],
    'payroll_delete': ['payroll', 'payroll_delete'],
    'payroll_pending': ['payroll', 'payroll_pending'],
    # Book Management
    'book_inventory_list': ['books', 'book_inventory_list'],
    'book_stock_add': ['books', 'book_stock_add'],
    'book_stock_delete': ['books', 'book_stock_delete'],
    'book_issue': ['books', 'book_issue'],
    'book_assignment_list': ['books', 'book_assignment_list'],
    'book_return': ['books', 'book_return'],
    'book_pending_returns': ['books', 'book_pending_returns'],
    # Finance
    'wallet_dashboard': ['accounts', 'wallet_dashboard'],
    'chart_of_accounts': ['accounts', 'chart_of_accounts'],
    'fund_transfer': ['accounts', 'fund_transfer'],
    'accounts_quick_payment': ['accounts', 'accounts_quick_payment'],
    'accounts_quick_receipt': ['accounts', 'accounts_quick_receipt'],
    'accounts_bank_entry': ['accounts', 'accounts_bank_entry'],
    'accounts_jv': ['accounts', 'accounts_jv'],
    'accounts_balance_sheet': ['accounts', 'accounts_balance_sheet'],
    'accounts_account_ledger': ['accounts', 'accounts_account_ledger'],
    # Employee Workspace
    'workspace_dashboard': ['workspace', 'workspace_dashboard'],
    'workspace_party_list': ['workspace', 'workspace_party_list'],
    'workspace_product_list': ['workspace', 'workspace_product_list'],
    'workspace_account_list': ['workspace', 'workspace_account_list'],
    'workspace_expense_list': ['workspace', 'workspace_expense_list'],
    'workspace_transfer_list': ['workspace', 'workspace_transfer_list'],
    'workspace_ledger': ['workspace', 'workspace_ledger'],
    'workspace_month_close': ['workspace', 'workspace_month_close'],
    'workspace_reports': ['workspace', 'workspace_reports'],
    # Reports
    'reports_index': ['reports', 'reports_index'],
    'report_company_profile': ['reports', 'reports_index'],
    'driver_attendance_report': ['reports', 'driver_attendance_report'],
    'driver_attendance_tra_report': ['reports', 'driver_attendance_tra_report'],
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
    'active_drivers_report': ['reports', 'active_drivers_report'],
    'driver_seat_available_report': ['reports', 'driver_seat_available_report'],
    'oil_change_alert_report': ['reports', 'oil_change_alert_report'],
    'missing_documents_report': ['reports', 'missing_documents_report'],
    # Administration
    'user_list': ['users_manage', 'user_list', 'user_add', 'user_edit'],
    'role_list': ['users_manage', 'role_list', 'role_add', 'role_edit'],
    'form_control': ['users_manage', 'form_control'],
    'notification_list': ['notification_list', 'notification_add'],
    'notification_add': ['notification_list', 'notification_add'],
    'whats_new': ['whats_new'],
    # Dashboard section-level guards
    # view_fleet_map: ONLY the specific permission (or 'dashboard' full which expands to it via expand_login_permissions)
    'view_fleet_map': ['dashboard', 'view_fleet_map'],
    'driver_attendance': ['attendance', 'driver_attendance', 'driver_attendance_list'],
    # Dashboard card-specific permissions — STRICT: only 'dashboard' (full) OR the exact card code.
    # DO NOT add module-level fallbacks (master, vehicles_list, attendance, etc.) here —
    # that would let any user with Master Data permissions see all dashboard cards regardless of assignment.
    'dashboard_card_drivers':     ['dashboard', 'dashboard_card_drivers'],
    'dashboard_card_vehicles':    ['dashboard', 'dashboard_card_vehicles'],
    'dashboard_card_attendance':  ['dashboard', 'dashboard_card_attendance'],
    'dashboard_card_transfers':   ['dashboard', 'dashboard_card_transfers'],
    'dashboard_card_projects':    ['dashboard', 'dashboard_card_projects'],
    'dashboard_card_districts':   ['dashboard', 'dashboard_card_districts'],
    'dashboard_card_parking':     ['dashboard', 'dashboard_card_parking'],
    'dashboard_card_companies':   ['dashboard', 'dashboard_card_companies'],
    'dashboard_card_fuel':        ['dashboard', 'dashboard_card_fuel'],
    'dashboard_card_utilization': ['dashboard', 'dashboard_card_utilization'],
    'dashboard_card_finance':     ['dashboard', 'dashboard_card_finance'],
    'dashboard_card_doc_health':  ['dashboard', 'dashboard_card_doc_health'],
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
