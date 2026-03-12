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
PERMISSION_REPORTS = 'reports'
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
    (PERMISSION_REPORTS, 'Reports', 'Reports'),
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
    ('fuel_expense_delete', 'fuel_expense_delete'),
    # Oil & Lubricants
    ('oil_expense_list', 'oil_expense'),
    ('oil_expense_form', 'oil_expense_add'),
    ('oil_expense_delete', 'oil_expense_delete'),
    # Maintenance
    ('maintenance_expense_list', 'maintenance_expense'),
    ('maintenance_expense_form', 'maintenance_expense_add'),
    ('maintenance_expense_delete', 'maintenance_expense_delete'),
    # Employee Expenses
    ('employee_expense_list', 'employee_expense'),
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
    ('activity_log_report', 'activity_log_report'),
    ('activity_logs_geo_report', 'activity_logs_geo_report'),
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
    ('notification_list', 'notification_list'),
    ('notification_add', 'notification_add'),
    ('notification_mark_read', 'notification_list'),
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

        # Create Master role (Developer) with all permissions if missing
        master_role = Role.query.filter_by(name='Master').first()
        if not master_role:
            master_role = Role(name='Master', description='Developer only – full access; only Master can assign Admin role to users')
            db.session.add(master_role)
            db.session.commit()
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
                is_active=True
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
                is_active=True
            )
            db.session.add(admin_user)
            db.session.commit()


def check_password(user, password):
    """Return True if password matches user's password_hash."""
    return check_password_hash(user.password_hash, password)
