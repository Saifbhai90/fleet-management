"""
User login & role-based access control.
- Permission codes used in sidebar and route checks.
- Map endpoint -> required permission.
- Seed default permissions, Admin role, and admin user.
"""
from werkzeug.security import generate_password_hash, check_password_hash

# All permission codes (must match DB after seed)
PERMISSION_DASHBOARD = 'dashboard'
PERMISSION_MASTER = 'master'
PERMISSION_ASSIGNMENT = 'assignment'
PERMISSION_TRANSFER = 'transfer'
PERMISSION_DRIVER_STATUS = 'driver_status'  # Workforce (Resignation, Rejoin, Penalties)
PERMISSION_ATTENDANCE = 'attendance'        # Attendance (Check-in/out, list, etc.)
PERMISSION_TASK_REPORT = 'task_report'
PERMISSION_EXPENSES = 'expenses'
PERMISSION_ACCOUNTS = 'accounts'
PERMISSION_WORKSPACE = 'workspace'
PERMISSION_REPORTS = 'reports'
PERMISSION_PAYROLL = 'payroll'
PERMISSION_BOOKS = 'books'
PERMISSION_BACKUP = 'backup'
PERMISSION_USERS_MANAGE = 'users_manage'

ALL_PERMISSION_CODES = [
    (PERMISSION_DASHBOARD, 'Dashboard', 'General'),
    (PERMISSION_MASTER, 'Master (Companies, Projects, Drivers, etc.)', 'Master'),
    (PERMISSION_ASSIGNMENT, 'Assignment', 'Assignment'),
    (PERMISSION_TRANSFER, 'Transfer', 'Transfer'),
    (PERMISSION_DRIVER_STATUS, 'Workforce (Driver Status, Penalties)', 'Driver Status'),
    (PERMISSION_ATTENDANCE, 'Attendance', 'Attendance'),
    (PERMISSION_TASK_REPORT, 'Task Report', 'Task Report'),
    (PERMISSION_EXPENSES, 'Expenses (Fuel, Oil, Maintenance, Employee)', 'Expenses'),
    (PERMISSION_ACCOUNTS, 'Accounts', 'Accounts'),
    (PERMISSION_WORKSPACE, 'Employee Financial Workspace', 'Workspace'),
    (PERMISSION_REPORTS, 'Reports', 'Reports'),
    (PERMISSION_PAYROLL, 'Payroll (Salary & Wages)', 'Payroll'),
    (PERMISSION_BOOKS, 'Book Management', 'Books'),
    (PERMISSION_BACKUP, 'Backup', 'General'),
    (PERMISSION_USERS_MANAGE, 'User & Role Management', 'Admin'),
    ('role_delete', 'Roles – Delete', 'Admin'),
]

# Endpoint -> required permission code (granular where defined)
ENDPOINT_PERMISSION_MAP = [
    ('dashboard', PERMISSION_DASHBOARD),
    ('companies', 'companies_list'),
    ('company_form', 'companies_add'),
    ('company_report', 'company_report'),
    ('delete_company', 'companies_delete'),
    ('projects_list', 'projects_list'),
    ('project_detail', 'project_detail'),
    ('project_form', 'projects_add'),
    ('delete_project', 'projects_delete'),
    ('toggle_project_status', 'projects_edit'),
    ('districts_list', 'districts_list'),
    ('district_form', 'districts_add'),
    ('delete_district', 'districts_delete'),
    ('vehicles_list', 'vehicles_list'),
    ('vehicle_form', 'vehicles_add'),
    ('delete_vehicle', 'vehicles_delete'),
    ('vehicles_import', 'vehicles_import'),
    ('parking_list', 'parking_list'),
    ('parking_form', 'parking_add'),
    ('delete_parking', 'parking_delete'),
    ('parking_import', 'parking_import'),
    ('drivers_list', 'drivers_list'),
    ('driver_form', 'drivers_add'),
    ('delete_driver', 'drivers_delete'),
    ('drivers_import', 'drivers_import'),
    ('employees_list', 'employees_list'),
    ('employee_form', 'employees_add'),
    ('employee_delete', 'employees_delete'),
    ('employees_import', 'employees_import'),
    ('role_delete', 'role_delete'),
    ('driver_post_list', 'driver_post_list'),
    ('driver_post_form', 'driver_post_add'),
    ('driver_post_delete', 'driver_post_delete'),
    ('party_list', 'party_list'),
    ('party_form', 'party_add'),
    ('party_delete', 'party_delete'),
    ('party_import', 'party_import'),
    ('product_list', 'product_list'),
    ('product_form', 'product_add'),
    ('product_delete', 'product_delete'),
    ('product_import', 'product_import'),
    # Assignments – granular per feature
    # Project → Company
    ('assign_project_to_company_edit', 'assign_project_to_company_edit'),
    ('assign_project_to_company_new', 'assign_project_to_company_add'),
    ('desassign_project_from_company', 'assign_project_to_company_desassign'),
    ('assign_project_to_company_export', 'assign_project_to_company'),
    ('assign_project_to_company_print', 'assign_project_to_company'),
    ('assign_project_to_company', 'assign_project_to_company'),
    # District → Project
    ('assign_project_to_district_edit', 'assign_project_to_district_edit'),
    ('assign_project_to_district_new', 'assign_project_to_district_add'),
    ('desassign_district_from_project', 'assign_project_to_district_desassign'),
    ('assign_project_to_district_export', 'assign_project_to_district'),
    ('assign_project_to_district_print', 'assign_project_to_district'),
    ('assign_project_to_district', 'assign_project_to_district'),
    # Vehicle → District
    ('assign_vehicle_to_district_edit', 'assign_vehicle_to_district_edit'),
    ('assign_vehicle_to_district_new', 'assign_vehicle_to_district_add'),
    ('desassign_vehicle_from_district', 'assign_vehicle_to_district_desassign'),
    ('assign_vehicle_to_district_export', 'assign_vehicle_to_district'),
    ('assign_vehicle_to_district_print', 'assign_vehicle_to_district'),
    ('assign_vehicle_to_district', 'assign_vehicle_to_district'),
    # Vehicle → Parking
    ('assign_vehicle_to_parking_edit', 'assign_vehicle_to_parking_edit'),
    ('assign_vehicle_to_parking_new', 'assign_vehicle_to_parking_add'),
    ('desassign_vehicle_from_parking', 'assign_vehicle_to_parking_desassign'),
    ('assign_vehicle_to_parking_export', 'assign_vehicle_to_parking'),
    ('assign_vehicle_to_parking_print', 'assign_vehicle_to_parking'),
    ('assign_vehicle_to_parking_list', 'assign_vehicle_to_parking'),
    # Driver → Vehicle
    ('assign_driver_to_vehicle_edit', 'assign_driver_to_vehicle_edit'),
    ('assign_driver_to_vehicle_new', 'assign_driver_to_vehicle_add'),
    ('desassign_driver_from_vehicle', 'assign_driver_to_vehicle_desassign'),
    ('assign_driver_to_vehicle_export', 'assign_driver_to_vehicle'),
    ('assign_driver_to_vehicle_print', 'assign_driver_to_vehicle'),
    ('assign_driver_to_vehicle_list', 'assign_driver_to_vehicle'),
    # Transfers – granular
    # Project Transfer
    ('project-transfers', 'project_transfers'),
    ('project_transfer_new', 'project_transfers_add'),
    ('project_transfer_edit', 'project_transfers_edit'),
    ('project_transfer_delete', 'project_transfers_delete'),
    # Vehicle Transfer
    ('vehicle-transfers', 'vehicle_transfers'),
    ('vehicle_transfer_new', 'vehicle_transfers_add'),
    ('vehicle_transfer_edit', 'vehicle_transfers_edit'),
    ('vehicle_transfer_delete', 'vehicle_transfers_delete'),
    # Driver Transfer
    ('driver-transfers', 'driver_transfers'),
    ('driver_transfer_new', 'driver_transfers_add'),
    ('driver_transfer_edit', 'driver_transfers_edit'),
    ('driver_transfer_delete', 'driver_transfers_delete'),
    # Workforce / Driver Status
    ('driver_job_left_new', 'driver_job_left'),
    ('driver_job_left_list', 'driver_job_left_list'),
    ('driver_job_left_view', 'driver_job_left_list'),
    ('driver_job_left_edit', 'driver_job_left_edit'),
    ('driver_job_left_delete', 'driver_job_left_delete'),
    ('driver_rejoin_new', 'driver_rejoin'),
    ('driver_rejoin_list', 'driver_rejoin_list'),
    ('driver_rejoin_view', 'driver_rejoin_view'),
    ('penalty_record_list', 'penalty_record'),
    ('penalty_record_export', 'penalty_record'),
    ('penalty_record_print', 'penalty_record'),
    ('penalty_record_new', 'penalty_record_add'),
    ('penalty_record_edit', 'penalty_record_edit'),
    # Attendance – GPS + Camera + manual list/mark
    ('driver_attendance_checkin', 'driver_attendance_checkin'),
    ('driver_attendance_checkout', 'driver_attendance_checkout'),
    ('driver_attendance_list', 'driver_attendance_list'),
    ('driver_attendance_export', 'driver_attendance_list'),
    ('driver_attendance_print', 'driver_attendance_list'),
    ('driver_attendance_mark', 'driver_attendance_mark'),
    ('driver_attendance_bulk_off', 'driver_attendance_bulk_off'),
    ('driver_attendance_pending', 'driver_attendance_pending'),
    ('driver_attendance_missing_checkout', 'driver_attendance_missing_checkout'),
    ('driver_attendance_manual_checkin', 'driver_attendance_list'),
    ('driver_attendance_manual_checkout', 'driver_attendance_list'),
    # Task & Logbook
    ('task_report_upload', 'task_report_upload'),
    ('task_report_upload_emergency', 'task_report_upload'),
    ('task_report_upload_mileage', 'task_report_upload'),
    # Daily Task Report
    ('task-report', 'task_report_list'),
    ('task_report_list', 'task_report_list'),
    ('task_report_new', 'task_report_add'),
    # Red Task
    ('red_task_list', 'red_task'),
    ('red_task_new', 'red_task_add'),
    ('red_task_edit', 'red_task_edit'),
    # Movement without Task
    ('without_task_list', 'without_task'),
    ('without_task_new', 'without_task_add'),
    ('without_task_edit', 'without_task_edit'),
    # Logbook Covers
    ('task_report_logbook_cover', 'task_report_logbook'),
    ('task_report_logbook_view', 'task_report_logbook'),
    ('task_report_logbook_view_all', 'task_report_logbook'),
    # Expense Management
    # Fuel
    ('fuel_expense_list', 'fuel_expense'),
    ('fuel_expense_add', 'fuel_expense_add'),
    ('fuel_expense_edit', 'fuel_expense_edit'),
    ('fuel_expense_view', 'fuel_expense'),
    ('fuel_expense_media', 'fuel_expense'),
    ('fuel_expense_media_download', 'fuel_expense'),
    ('fuel_expense_media_download_all', 'fuel_expense'),
    ('fuel_expense_delete', 'fuel_expense_delete'),
    # Oil & Lubricants
    ('oil_expense_list', 'oil_expense'),
    ('oil_expense_form', 'oil_expense_add'),
    ('oil_expense_view', 'oil_expense'),
    ('oil_expense_media', 'oil_expense'),
    ('oil_expense_media_download', 'oil_expense'),
    ('oil_expense_media_download_all', 'oil_expense'),
    ('oil_expense_delete', 'oil_expense_delete'),
    # Maintenance
    ('maintenance_expense_list', 'maintenance_expense'),
    ('maintenance_expense_form', 'maintenance_expense_add'),
    ('maintenance_expense_view', 'maintenance_expense'),
    ('maintenance_expense_media', 'maintenance_expense'),
    ('maintenance_expense_media_download', 'maintenance_expense'),
    ('maintenance_expense_media_download_all', 'maintenance_expense'),
    ('maintenance_expense_delete', 'maintenance_expense_delete'),
    ('maintenance_work_order_list', 'maintenance_expense'),
    ('maintenance_work_order_export', 'maintenance_expense'),
    ('maintenance_work_order_form', 'maintenance_expense_add'),
    ('maintenance_work_order_detail', 'maintenance_expense'),
    ('maintenance_work_order_invoices', 'maintenance_expense'),
    ('maintenance_work_order_invoices_export', 'maintenance_expense'),
    ('maintenance_work_order_unified_media', 'maintenance_expense'),
    ('maintenance_work_order_job_media', 'maintenance_expense'),
    ('maintenance_work_order_media_download', 'maintenance_expense'),
    ('maintenance_work_order_delete', 'maintenance_expense_delete'),
    ('expense_delete_cleanup_retry', 'workspace_dashboard'),
    # Employee Expenses
    ('employee_expense_list', 'employee_expense'),
    ('employee_expense_view', 'employee_expense'),
    # Employee Workspace
    ('workspace_dashboard', 'workspace_dashboard'),
    ('workspace_home', 'workspace_dashboard'),
    ('workspace_select_employee', 'workspace_dashboard'),
    ('workspace_clear_employee', 'workspace_dashboard'),
    ('workspace_parties_list', 'workspace_party_list'),
    ('workspace_party_new', 'workspace_party_add'),
    ('workspace_party_edit', 'workspace_party_edit'),
    ('workspace_party_delete', 'workspace_party_delete'),
    ('workspace_products_list', 'workspace_product_list'),
    ('workspace_party_names_api', 'workspace_party_list'),
    ('workspace_product_names_api', 'workspace_product_list'),
    ('workspace_product_new', 'workspace_product_add'),
    ('workspace_product_edit', 'workspace_product_edit'),
    ('workspace_product_delete', 'workspace_product_delete'),
    ('workspace_accounts_list', 'workspace_account_list'),
    ('workspace_account_new', 'workspace_account_add'),
    ('workspace_account_edit', 'workspace_account_edit'),
    ('workspace_expenses_list', 'workspace_expense_list'),
    ('workspace_expense_new', 'workspace_expense_add'),
    ('workspace_expense_edit', 'workspace_expense_edit'),
    ('workspace_expense_delete', 'workspace_expense_delete'),
    ('workspace_fund_transfers_list', 'workspace_transfer_list'),
    ('workspace_fund_transfer_new', 'workspace_transfer_add'),
    ('workspace_fund_transfer_view', 'workspace_transfer_list'),
    ('workspace_fund_transfer_media', 'workspace_transfer_list'),
    ('workspace_fund_transfer_edit', 'workspace_transfer_edit'),
    ('workspace_fund_transfer_delete', 'workspace_transfer_delete'),
    ('fund_transfers_list', 'fund_transfer'),
    ('fund_transfer_add', 'fund_transfer'),
    ('fund_transfer_view', 'fund_transfer'),
    ('fund_transfer_media', 'fund_transfer'),
    ('fund_transfer_edit', 'fund_transfer'),
    ('fund_transfer_delete', 'fund_transfer'),
    ('workspace_ledger', 'workspace_ledger'),
    ('workspace_ledger_transfer_detail', 'workspace_ledger'),
    ('workspace_ledger_journal_detail', 'workspace_ledger'),
    ('workspace_balance_sheet', 'workspace_reports'),
    ('workspace_mpg_report', 'workspace_reports'),
    ('workspace_dashboard_financial_report', 'workspace_dashboard'),
    ('workspace_month_close', 'workspace_month_close'),
    ('workspace_reports', 'workspace_reports'),
    # Finance
    ('accounts_quick_payment', 'accounts_quick_payment'),
    ('accounts_quick_receipt', 'accounts_quick_receipt'),
    ('accounts_bank_entry', 'accounts_bank_entry'),
    ('accounts_jv', 'accounts_jv'),
    ('accounts_future_entry', 'accounts_future_entry'),
    ('accounts_balance_sheet', 'accounts_balance_sheet'),
    ('accounts_account_ledger', 'accounts_account_ledger'),
    # Reports & analytics: map each endpoint to its own granular permission
    ('reports_index', 'reports_index'),
    ('report_vehicle_summary', 'report_vehicle_summary'),
    ('report_project_summary', 'report_project_summary'),
    ('report_district_summary', 'report_district_summary'),
    ('report_parking_utilization', 'report_parking_utilization'),
    ('report_vehicle_profile', 'report_vehicle_profile'),
    ('report_driver_profile', 'report_driver_profile'),
    ('report_expiry', 'report_expiry'),
    ('report_ai', 'report_ai'),
    ('driver_attendance_report', 'driver_attendance_report'),
    ('active_drivers_report', 'active_drivers_report'),
    ('driver_salary_slip', 'driver_salary_slip'),
    ('api_salary_slip_driver', 'driver_salary_slip'),
    ('api_salary_slip_drivers_for_vehicle', 'driver_salary_slip'),
    ('api_filter_projects_by_district', 'driver_salary_slip'),
    ('driver_seat_available_report', 'driver_seat_available_report'),
    ('oil_change_alert_report', 'oil_change_alert_report'),
    ('activity_log_report', 'activity_log_report'),
    ('activity_logs_geo_report', 'activity_logs_geo_report'),
    # Payroll Module
    ('payroll_salary_config_list', 'payroll_config_list'),
    ('payroll_salary_config_form', 'payroll_config_add'),
    ('payroll_salary_config_edit', 'payroll_config_edit'),
    ('payroll_salary_config_delete', 'payroll_config_delete'),
    ('payroll_driver_bulk_salary', 'payroll_config_add'),
    ('book_inventory_list', 'book_inventory_list'),
    ('book_stock_entry', 'book_stock_add'),
    ('book_stock_edit', 'book_stock_add'),
    ('book_stock_delete', 'book_stock_delete'),
    ('book_mark_lost', 'book_stock_add'),
    ('book_issue', 'book_issue'),
    ('book_assignment_list', 'book_assignment_list'),
    ('book_return', 'book_return'),
    ('book_pending_returns', 'book_pending_returns'),
    ('payroll_list', 'payroll_list'),
    ('payroll_generate', 'payroll_generate'),
    ('payroll_bulk_generate', 'payroll_generate'),
    ('payroll_view', 'payroll_list'),
    ('payroll_edit', 'payroll_edit'),
    ('payroll_recalc_attendance', 'payroll_edit'),
    ('payroll_finalize', 'payroll_finalize'),
    ('payroll_pay', 'payroll_pay'),
    ('payroll_revert', 'payroll_finalize'),
    ('payroll_delete', 'payroll_delete'),
    ('payroll_pending', 'payroll_pending'),
    ('payroll_payslip', 'payroll_list'),
    ('api_payroll_attendance_preview', 'payroll_generate'),
    ('backup', PERMISSION_BACKUP),
    ('whats_new', 'whats_new'),
    ('user_list', 'user_list'),
    ('user_form', 'user_add'),
    ('user_edit', 'user_edit'),
    ('user_delete', 'user_delete'),
    ('users_sync_from_employees_drivers', 'user_list'),
    ('role_list', 'role_list'),
    ('role_form', 'role_add'),
    ('role_edit', 'role_edit'),
    ('form_control', 'form_control'),
    ('form_control_delete_override', 'form_control'),
    ('form_control_edit_override', 'form_control'),
    ('notification_list', 'notification_list'),
    ('notification_add', 'notification_add'),
    ('notification_mark_read', 'notification_list'),
    # Master data – Print / Export (dedicated permission codes)
    ('companies_print', 'companies_list'),
    ('company_projects', 'projects_list'),
    ('projects_print', 'projects_print'),
    ('projects_export', 'projects_export'),
    ('vehicles_print', 'vehicles_print'),
    ('vehicles_export', 'vehicles_export'),
    ('drivers_print', 'drivers_print'),
    ('drivers_export', 'drivers_export'),
    ('employees_print', 'employees_print'),
    ('employees_export', 'employees_export'),
    ('parking_print', 'parking_print'),
    ('parking_export', 'parking_export'),
    # Internal API helpers – tied to their feature permissions
    ('api_check_cnic', 'drivers_list'),
    ('api_check_license', 'drivers_list'),
    ('api_parties', 'party_list'),
    ('get_left_drivers_by_vehicle', 'driver_rejoin_list'),
    ('check_vehicle_shifts', 'assign_driver_to_vehicle'),
    # Fuel expense helper APIs
    ('api_fuel_expense_location_cascade', 'fuel_expense'),
    ('api_fuel_expense_last_reading', 'fuel_expense'),
    ('api_fuel_expense_task_readings', 'fuel_expense'),
    ('api_fuel_expense_suggested_price', 'fuel_expense'),
    ('api_fuel_expense_price_hint', 'fuel_expense'),
    ('api_fuel_expense_upload_status', 'fuel_expense'),
    ('fuel_expense_upload_resume', 'fuel_expense'),
    # Oil expense helper APIs
    ('api_oil_expense_last_reading', 'oil_expense'),
    ('api_oil_expense_products_for_oil', 'oil_expense'),
    ('api_oil_expense_product_balance', 'oil_expense'),
    ('api_oil_expense_product_price_history', 'oil_expense'),
    ('api_oil_expense_upload_status', 'oil_expense'),
    ('oil_expense_upload_resume', 'oil_expense'),
    # Maintenance expense helper APIs
    ('api_maintenance_expense_last_reading', 'maintenance_expense'),
    ('api_maintenance_expense_products', 'maintenance_expense'),
    ('api_maintenance_expense_product_price_history', 'maintenance_expense'),
    ('api_maintenance_expense_approval_text', 'maintenance_expense'),
    ('api_maintenance_work_order_approval_text', 'maintenance_expense'),
    ('api_maintenance_expense_upload_status', 'maintenance_expense'),
    ('maintenance_expense_upload_resume', 'maintenance_expense'),
    # Attendance helper APIs
    ('api_parking_stations_with_coords', 'driver_attendance_checkin'),
    ('api_attendance_projects', 'driver_attendance_checkin'),
    ('api_attendance_vehicles', 'driver_attendance_checkin'),
    ('api_attendance_drivers', 'driver_attendance_checkin'),
    ('api_attendance_filtered_drivers', 'driver_attendance_list'),
    ('api_attendance_time_window', 'driver_attendance_checkin'),
    ('api_attendance_has_gps_checkin', 'driver_attendance_checkout'),
    # ── Security Lockdown: previously unprotected routes ─────────────────
    # Backup sub-routes (same section as /backup index; require system_backup)
    ('backup_download', 'system_backup'),
    ('backup_email', 'system_backup'),
    ('backup_save', 'system_backup'),
    # Uploaded documents / photos (require view_documents)
    ('uploaded_file', 'view_documents'),
    # Global search and fleet map APIs
    ('api_global_search', 'global_search'),
    ('api_fleet_map_pins', 'view_fleet_map'),
    # Import download templates (require same permission as the import action)
    ('vehicles_import_template', 'vehicles_import'),
    ('drivers_import_template', 'drivers_import'),
    ('parking_import_template', 'parking_import'),
    # Notification mark-as-read (require notification_list)
    ('notification_read', 'notification_list'),
    # Finance sub-routes (voucher list / edit / delete)
    ('payment_vouchers_list', 'accounts_quick_payment'),
    ('payment_voucher_edit', 'accounts_quick_payment'),
    ('payment_voucher_delete', 'accounts_quick_payment'),
    ('receipt_vouchers_list', 'accounts_quick_receipt'),
    ('bank_entries_list', 'accounts_bank_entry'),
    # Employee expense (correct granular codes replacing phantom employee_expense_form)
    ('employee_expense_form', 'employee_expense_add'),
    ('employee_expense_form_edit', 'employee_expense_edit'),
    ('employee_expense_receipt_push_cloud', 'employee_expense_edit'),
    ('employee_expense_delete', 'employee_expense_delete'),
    # Transfer Print / Export routes
    ('vehicle_transfers_print', 'vehicle_transfers'),
    ('vehicle_transfers_export', 'vehicle_transfers'),
    ('driver_transfers_print', 'driver_transfers'),
    ('driver_transfers_export', 'driver_transfers'),
    ('project_transfers_print', 'project_transfers'),
    ('project_transfers_export', 'project_transfers'),
    # Penalty Delete
    ('penalty_record_delete', 'penalty_record_delete'),
]


def get_required_permission(endpoint):
    """Return permission code required for this endpoint, or None if no restriction.
    Uses longest matching key so e.g. assign_vehicle_to_parking_list matches before parking_list."""
    if not endpoint:
        return None
    endpoint = endpoint.lower()
    best_perm = None
    best_key_len = 0
    for key, perm in ENDPOINT_PERMISSION_MAP:
        if key in endpoint and len(key) > best_key_len:
            best_perm = perm
            best_key_len = len(key)
    return best_perm


# Section that grants full access to a permission (e.g. master grants companies_list)
def _build_section_for_permission():
    try:
        from permissions_config import PERMISSION_TREE
        d = {}
        for section_code, items in PERMISSION_TREE.items():
            for code, _ in items:
                d[code] = section_code
        return d
    except Exception:
        return {}

SECTION_FOR_PERMISSION = _build_section_for_permission()


def user_has_permission(permission_codes, code):
    """Check if list of permission codes includes the given code."""
    return code in (permission_codes or [])


def user_can_access(permission_codes, required_code):
    """
    True if user has the exact required_code, or a section-level "full" code
    that includes this permission (e.g. 'assignment' grants assign_vehicle_to_parking).
    """
    if not required_code:
        return True
    codes = permission_codes or []
    if required_code in codes:
        return True
    # Section-level full codes: grant access to granular pages in that section
    try:
        from permissions_config import SECTION_FULL_TO_GROUP, SECTION_PAGE_GROUPS
        for section_full, section_key in SECTION_FULL_TO_GROUP.items():
            if section_full not in codes:
                continue
            for _page_label, items in SECTION_PAGE_GROUPS.get(section_key, []):
                for code, _name in items:
                    if code == required_code:
                        return True
    except Exception:
        pass
    return False


def seed_auth_tables(app):
    """Create permissions from tree, Master/Admin roles, and default users if not present."""
    from models import db, Permission, Role, User
    try:
        from permissions_config import flatten_permission_tree
        tree_perms = list(flatten_permission_tree())
    except Exception:
        tree_perms = []

    with app.app_context():
        # Create permissions from tree (and legacy flat list for backward compat)
        for code, name, category in ALL_PERMISSION_CODES:
            p = Permission.query.filter_by(code=code).first()
            if not p:
                p = Permission(code=code, name=name, category=category)
                db.session.add(p)
        for code, name, category in tree_perms:
            if code in [x[0] for x in ALL_PERMISSION_CODES]:
                continue
            p = Permission.query.filter_by(code=code).first()
            if not p:
                p = Permission(code=code, name=name, category=category)
                db.session.add(p)
        db.session.commit()

        # Ensure assignment granular permissions exist (in case added to config after first seed)
        for code, name in [
            ('assign_vehicle_to_parking', 'Vehicle to Parking – List / View'),
            ('assign_vehicle_to_parking_add', 'Vehicle to Parking – Add New'),
            ('assign_vehicle_to_parking_edit', 'Vehicle to Parking – Edit'),
            ('assign_vehicle_to_parking_desassign', 'Vehicle to Parking – Deassign'),
        ]:
            if not Permission.query.filter_by(code=code).first():
                p = Permission(code=code, name=name, category='Assignments')
                db.session.add(p)
        db.session.commit()

        all_perms = Permission.query.all()

        # Create or update Master role (Developer) – always gets ALL permissions
        master_role = Role.query.filter_by(name='Master').first()
        if not master_role:
            master_role = Role(name='Master', description='Developer only – full access; only Master can assign Admin role to users')
            db.session.add(master_role)
            db.session.commit()
        if set(p.id for p in master_role.permissions) != set(p.id for p in all_perms):
            master_role.permissions = all_perms
            db.session.commit()

        # Create Admin role with all permissions if missing
        admin_role = Role.query.filter_by(name='Admin').first()
        if not admin_role:
            admin_role = Role(name='Admin', description='System admin – access limited to what Master assigns')
            db.session.add(admin_role)
            db.session.commit()
            # Default Admin permissions are intentionally limited.
            # Master (Developer) will grant additional permissions as needed.
            default_admin_codes = {
                PERMISSION_DASHBOARD,
                PERMISSION_USERS_MANAGE,
                'user_list', 'user_add', 'user_edit', 'user_delete',
                'role_list', 'role_add', 'role_edit', 'role_delete',
                'form_control',
                'notification_list', 'notification_add',
            }
            default_admin_perms = Permission.query.filter(Permission.code.in_(list(default_admin_codes))).all()
            admin_role.permissions = default_admin_perms
            db.session.commit()

        # Create default master (developer) user if no Master user exists
        if not User.query.join(Role).filter(Role.name == 'Master').first():
            master_user = User(
                username='master',
                password_hash=generate_password_hash('master'),
                full_name='Master (Developer)',
                role_id=master_role.id,
                is_active=True,
                force_password_change=True,
            )
            db.session.add(master_user)
            db.session.commit()

        # Create default admin user if no Admin user exists (for first-time setup)
        if not User.query.join(Role).filter(Role.name == 'Admin').first():
            admin_user = User(
                username='admin',
                password_hash=generate_password_hash('admin'),
                full_name='Administrator',
                role_id=admin_role.id,
                is_active=True,
                force_password_change=True,
            )
            db.session.add(admin_user)
            db.session.commit()


def check_password(user, password):
    """Return True if password matches user's password_hash."""
    return check_password_hash(user.password_hash, password)


# ── Trusted Device cookie (web 30-day auto-login) ──────────────────────────
TRUSTED_DEVICE_COOKIE = 'fleet_trusted_device'
TRUSTED_DEVICE_DAYS   = 30

def make_trusted_device_token(username, secret_key):
    """Return a signed token: base64(username).HMAC-SHA256 for trusted-device cookie."""
    import hmac as _hmac, hashlib, base64
    sig = _hmac.new(
        secret_key.encode('utf-8'),
        f"{username}:trusted-device-v1".encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    user_b64 = base64.urlsafe_b64encode(username.encode('utf-8')).decode('ascii')
    return f"{user_b64}.{sig}"


def verify_trusted_device_token(token, secret_key):
    """Return username if token is valid, else None."""
    import hmac as _hmac, hashlib, base64
    try:
        user_b64, sig = token.rsplit('.', 1)
        username = base64.urlsafe_b64decode(user_b64.encode('ascii')).decode('utf-8')
        expected = _hmac.new(
            secret_key.encode('utf-8'),
            f"{username}:trusted-device-v1".encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        if _hmac.compare_digest(sig, expected):
            return username
    except Exception:
        pass
    return None


# ── Data Context & Auto-Fill Policy ────────────────────────────────────────
def get_user_context(user_id):
    """
    Fetch user's assigned Districts, Projects, Vehicles, Shifts based on Employee/Driver records.
    Returns dict with:
    - allowed_projects: set of project IDs
    - allowed_districts: set of district IDs
    - allowed_vehicles: set of vehicle IDs
    - allowed_shifts: set of shift names
    - allowed_parking: set of parking station IDs
    - is_employee: bool
    - is_driver: bool
    - is_master_or_admin: bool
    - employee_record: Employee object or None
    - driver_record: Driver object or None
    - latest_transfer: DriverTransfer or None (for drivers)
    """
    from models import User, Employee, Driver, DriverTransfer
    from sqlalchemy import func
    import traceback
    
    context = {
        'allowed_projects': set(),
        'allowed_districts': set(),
        'allowed_vehicles': set(),
        'allowed_shifts': set(),
        'allowed_parking': set(),
        'is_employee': False,
        'is_driver': False,
        'is_master_or_admin': False,
        'employee_record': None,
        'driver_record': None,
        'latest_transfer': None,
    }
    
    try:
        print(f"DEBUG: get_user_context called for user_id={user_id}")
        user = User.query.get(user_id)
        if not user:
            print(f"DEBUG: User not found for user_id={user_id}")
            return context
        print(f"DEBUG: User found: {user.username}, role={user.role.name if user.role else 'None'}")
        
        # Check if Master or Admin (no restrictions)
        role_name = (user.role.name if user.role else '').strip()
        if role_name in ['Master', 'Admin']:
            context['is_master_or_admin'] = True
            return context
        
        # CNIC variants for matching
        username = (user.username or '').strip()
        cnic_variants = [username, username.replace('-', '')]
        
        # Employee assignments (projects/districts)
        print(f"DEBUG: Checking Employee record for CNIC variants: {cnic_variants}")
        emp = None
        for c in cnic_variants:
            emp = Employee.query.filter(func.lower(Employee.cnic_no) == c.lower()).first()
            if emp:
                print(f"DEBUG: Employee found: {emp.name} (ID: {emp.id})")
                break
        
        if emp:
            context['is_employee'] = True
            context['employee_record'] = emp
            # Employee.projects and .districts are dynamic relationships - need .all()
            try:
                print(f"DEBUG: Fetching employee projects...")
                projects_list = emp.projects.all()
                print(f"DEBUG: Employee has {len(projects_list)} projects")
                for p in projects_list:
                    if p and p.id:
                        context['allowed_projects'].add(p.id)
                        print(f"DEBUG: Added project {p.id} ({p.name})")
            except Exception as e:
                print(f"DEBUG: Error fetching employee projects: {str(e)}")
                traceback.print_exc()
            try:
                print(f"DEBUG: Fetching employee districts...")
                districts_list = emp.districts.all()
                print(f"DEBUG: Employee has {len(districts_list)} districts")
                for d in districts_list:
                    if d and d.id:
                        context['allowed_districts'].add(d.id)
                        print(f"DEBUG: Added district {d.id} ({d.name})")
            except Exception as e:
                print(f"DEBUG: Error fetching employee districts: {str(e)}")
                traceback.print_exc()
        else:
            print(f"DEBUG: No Employee record found")
        
        # Driver assignments (CURRENT active assignment from latest transfer or Driver model)
        drv = None
        for c in cnic_variants:
            drv = Driver.query.filter(func.lower(Driver.cnic_no) == c.lower()).first()
            if drv:
                break
        
        if drv:
            context['is_driver'] = True
            context['driver_record'] = drv
            
            # Get latest transfer record to determine current assignment
            latest_transfer = DriverTransfer.query.filter_by(
                driver_id=drv.id
            ).order_by(DriverTransfer.transfer_date.desc()).first()
            
            if latest_transfer:
                context['latest_transfer'] = latest_transfer
                # Use new_ fields from latest transfer as current assignment
                if latest_transfer.new_project_id:
                    context['allowed_projects'].add(latest_transfer.new_project_id)
                if latest_transfer.new_district_id:
                    context['allowed_districts'].add(latest_transfer.new_district_id)
                if latest_transfer.new_vehicle_id:
                    context['allowed_vehicles'].add(latest_transfer.new_vehicle_id)
                if latest_transfer.new_shift:
                    context['allowed_shifts'].add(latest_transfer.new_shift)
            else:
                # No transfer history - use Driver model fields as current assignment
                if getattr(drv, 'project_id', None):
                    context['allowed_projects'].add(drv.project_id)
                if getattr(drv, 'district_id', None):
                    context['allowed_districts'].add(drv.district_id)
                if getattr(drv, 'vehicle_id', None):
                    context['allowed_vehicles'].add(drv.vehicle_id)
                if getattr(drv, 'shift', None) and drv.shift.strip():
                    context['allowed_shifts'].add(drv.shift.strip())
    
    except Exception as e:
        # Log the error for debugging
        import traceback
        print(f"ERROR in get_user_context for user_id={user_id}: {str(e)}")
        print(traceback.format_exc())
    
    return context
