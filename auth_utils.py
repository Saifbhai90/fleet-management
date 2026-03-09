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
PERMISSION_DRIVER_STATUS = 'driver_status'
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
    (PERMISSION_DRIVER_STATUS, 'Driver Status (Attendance, Penalty, etc.)', 'Driver Status'),
    (PERMISSION_TASK_REPORT, 'Task Report', 'Task Report'),
    (PERMISSION_EXPENSES, 'Expenses (Fuel, Oil, Maintenance, Employee)', 'Expenses'),
    (PERMISSION_ACCOUNTS, 'Accounts', 'Accounts'),
    (PERMISSION_REPORTS, 'Reports', 'Reports'),
    (PERMISSION_BACKUP, 'Backup', 'General'),
    (PERMISSION_USERS_MANAGE, 'User & Role Management', 'Admin'),
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
    ('districts_list', 'districts_list'),
    ('district_form', 'districts_add'),
    ('vehicles_list', 'vehicles_list'),
    ('vehicle_form', 'vehicles_add'),
    ('parking_list', 'parking_list'),
    ('parking_form', 'parking_add'),
    ('drivers_list', 'drivers_list'),
    ('driver_form', 'drivers_add'),
    ('employees_list', 'employees_list'),
    ('employee_form', 'employees_add'),
    ('driver_post_list', 'driver_post_list'),
    ('driver_post_form', 'driver_post_add'),
    ('party_list', 'party_list'),
    ('party_form', 'party_add'),
    ('product_list', 'product_list'),
    ('product_form', 'product_add'),
    ('assign_project_to_company', 'assign_project_to_company'),
    ('assign_project_to_district', 'assign_project_to_district'),
    ('assign_vehicle_to_district', 'assign_vehicle_to_district'),
    ('assign_vehicle_to_parking', 'assign_vehicle_to_parking'),
    ('assign_driver_to_vehicle', 'assign_driver_to_vehicle'),
    ('project_transfers', 'project_transfers'),
    ('project_transfer', 'project_transfers'),
    ('vehicle_transfers', 'vehicle_transfers'),
    ('vehicle_transfer', 'vehicle_transfers'),
    ('driver_transfers', 'driver_transfers'),
    ('driver_transfer', 'driver_transfers'),
    ('driver_job_left', 'driver_job_left'),
    ('driver_rejoin', 'driver_rejoin'),
    ('driver_attendance', 'driver_attendance'),
    ('penalty_record', 'penalty_record'),
    ('task_report', 'task_report'),
    ('red_task', 'red_task'),
    ('without_task', 'without_task'),
    ('task_report_logbook', 'task_report_logbook'),
    ('fuel_expense', 'fuel_expense'),
    ('oil_expense', 'oil_expense'),
    ('maintenance_expense', 'maintenance_expense'),
    ('employee_expense', 'employee_expense'),
    ('accounts_', 'accounts'),
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
    """Return permission code required for this endpoint, or None if no restriction."""
    if not endpoint:
        return None
    endpoint = endpoint.lower()
    for key, perm in ENDPOINT_PERMISSION_MAP:
        if key in endpoint:
            return perm
    return None


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
    """True if user has required_code OR the section that grants it (e.g. master grants companies_list)."""
    if not required_code:
        return True
    codes = permission_codes or []
    if required_code in codes:
        return True
    section = SECTION_FOR_PERMISSION.get(required_code)
    if section and section in codes:
        return True
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
            admin_role = Role(name='Admin', description='Full access; can assign other roles (except Master/Admin) to users')
            db.session.add(admin_role)
            db.session.commit()
            admin_role.permissions = all_perms
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
