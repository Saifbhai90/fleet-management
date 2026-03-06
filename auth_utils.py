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

# Endpoint -> required permission code (first match wins; order matters for nested endpoints)
ENDPOINT_PERMISSION_MAP = [
    # (endpoint_prefix_or_exact, permission_code)
    ('dashboard', PERMISSION_DASHBOARD),
    ('companies', PERMISSION_MASTER),
    ('company_form', PERMISSION_MASTER),
    ('projects_list', PERMISSION_MASTER),
    ('project_detail', PERMISSION_MASTER),
    ('project_form', PERMISSION_MASTER),
    ('districts_list', PERMISSION_MASTER),
    ('district_form', PERMISSION_MASTER),
    ('vehicles_list', PERMISSION_MASTER),
    ('vehicle_form', PERMISSION_MASTER),
    ('parking_list', PERMISSION_MASTER),
    ('parking_form', PERMISSION_MASTER),
    ('drivers_list', PERMISSION_MASTER),
    ('driver_form', PERMISSION_MASTER),
    ('employees_list', PERMISSION_MASTER),
    ('employee_form', PERMISSION_MASTER),
    ('driver_post_list', PERMISSION_MASTER),
    ('driver_post_form', PERMISSION_MASTER),
    ('party_list', PERMISSION_MASTER),
    ('party_form', PERMISSION_MASTER),
    ('product_list', PERMISSION_MASTER),
    ('product_form', PERMISSION_MASTER),
    ('assign_project_to_company', PERMISSION_ASSIGNMENT),
    ('assign_project_to_district', PERMISSION_ASSIGNMENT),
    ('assign_vehicle_to_district', PERMISSION_ASSIGNMENT),
    ('assign_vehicle_to_parking', PERMISSION_ASSIGNMENT),
    ('assign_driver_to_vehicle', PERMISSION_ASSIGNMENT),
    ('project_transfers', PERMISSION_TRANSFER),
    ('project_transfer', PERMISSION_TRANSFER),
    ('vehicle_transfers', PERMISSION_TRANSFER),
    ('vehicle_transfer', PERMISSION_TRANSFER),
    ('driver_transfers', PERMISSION_TRANSFER),
    ('driver_transfer', PERMISSION_TRANSFER),
    ('driver_job_left', PERMISSION_DRIVER_STATUS),
    ('driver_rejoin', PERMISSION_DRIVER_STATUS),
    ('driver_attendance', PERMISSION_DRIVER_STATUS),
    ('penalty_record', PERMISSION_DRIVER_STATUS),
    ('task_report', PERMISSION_TASK_REPORT),
    ('red_task', PERMISSION_TASK_REPORT),
    ('without_task', PERMISSION_TASK_REPORT),
    ('task_report_logbook', PERMISSION_TASK_REPORT),
    ('fuel_expense', PERMISSION_EXPENSES),
    ('oil_expense', PERMISSION_EXPENSES),
    ('maintenance_expense', PERMISSION_EXPENSES),
    ('employee_expense', PERMISSION_EXPENSES),
    ('accounts_', PERMISSION_ACCOUNTS),  # accounts_quick_payment, etc.
    ('reports_index', PERMISSION_REPORTS),
    ('report_', PERMISSION_REPORTS),
    ('driver_attendance_report', PERMISSION_REPORTS),
    ('backup', PERMISSION_BACKUP),
    ('whats_new', PERMISSION_DASHBOARD),
    ('user_list', PERMISSION_USERS_MANAGE),
    ('user_', PERMISSION_USERS_MANAGE),
    ('role_list', PERMISSION_USERS_MANAGE),
    ('role_', PERMISSION_USERS_MANAGE),
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


def user_has_permission(permission_codes, code):
    """Check if list of permission codes includes the given code."""
    return code in (permission_codes or [])


def seed_auth_tables(app):
    """Create default Permission, Admin role, and admin user if not present."""
    from models import db, Permission, Role, User

    with app.app_context():
        # Create permissions if missing
        for code, name, category in ALL_PERMISSION_CODES:
            p = Permission.query.filter_by(code=code).first()
            if not p:
                p = Permission(code=code, name=name, category=category)
                db.session.add(p)
        db.session.commit()

        # Create Admin role with all permissions if missing
        admin_role = Role.query.filter_by(name='Admin').first()
        if not admin_role:
            admin_role = Role(name='Admin', description='Full access to all modules')
            db.session.add(admin_role)
            db.session.commit()
            perms = Permission.query.all()
            admin_role.permissions = perms
            db.session.commit()

        # Create default admin user if no users exist
        if User.query.count() == 0:
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
