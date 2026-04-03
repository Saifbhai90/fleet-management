from flask import Flask
from models import db
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
from datetime import timedelta
import os
import sys

# Load .env from app folder (so it works even when run from another directory)
_app_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_app_dir, '.env'))

print("Starting app...")
app = Flask(__name__)

# When running as a script, this file is loaded as '__main__'.
# routes.py imports 'app', which would otherwise cause this file to execute twice.
# Map the current module to 'app' to avoid double initialization.
sys.modules.setdefault('app', sys.modules[__name__])

# When behind a reverse proxy (e.g. Render), trust X-Forwarded-Proto and X-Forwarded-Host
# so redirects and session cookies use the correct scheme (https) and host. Fixes ERR_TOO_MANY_REDIRECTS.
try:
    from werkzeug.middleware.proxy_fix import ProxyFix
    # Use depth 2 in case Render has multiple proxy hops (e.g. edge -> app server)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=2, x_host=2)
except ImportError:
    pass

# Secret key — MUST be set via environment variable. No fallback allowed (prevents session forgery).
_secret_key = os.environ.get('SECRET_KEY', '').strip()
if not _secret_key:
    raise RuntimeError(
        "SECRET_KEY environment variable is not set. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\" "
        "and add it to your .env file or deployment environment."
    )
app.config['SECRET_KEY'] = _secret_key
# Session lifetime: 30 days rolling. Web inactivity timer (JS) handles forced logout at 30 min.
# Mobile: biometric lock overlay re-authenticates on every app foreground event.
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=int(os.environ.get('SESSION_DAYS', '30')))
app.config['SESSION_REFRESH_EACH_REQUEST'] = True  # Roll the session cookie on every request

# Database URL: Render (and some hosts) give postgres:// but SQLAlchemy 1.4+ requires postgresql://
database_url = os.environ.get('DATABASE_URL', 'sqlite:///company_management.db')
if database_url:
    database_url = database_url.strip()
    if database_url.startswith('postgres://'):
        database_url = 'postgresql://' + database_url[9:]
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///company_management.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'max_overflow': 20,
    'pool_pre_ping': True,
    'pool_recycle': 300,
}
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max upload
app.config['TEMPLATES_AUTO_RELOAD'] = os.environ.get('FLASK_DEBUG', '0') == '1'

# Backup: optional path to save backups; email via env MAIL_*
app.config['BACKUP_PATH'] = os.environ.get('BACKUP_PATH', '')  # empty = no save-to-path
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', '')
app.config['MAIL_PORT'] = os.environ.get('MAIL_PORT', '587')
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_FROM'] = os.environ.get('MAIL_FROM', '')
# Scheduled backup: time in 24h "HH:MM", email to send to
_app_schedule = (os.environ.get('BACKUP_SCHEDULE_ENABLED') or '').strip().lower()
app.config['BACKUP_SCHEDULE_ENABLED'] = _app_schedule in ('1', 'true', 'yes')
app.config['BACKUP_SCHEDULE_TIME'] = (os.environ.get('BACKUP_SCHEDULE_TIME') or '02:00').strip()
app.config['BACKUP_EMAIL_TO'] = (os.environ.get('BACKUP_EMAIL_TO') or '').strip()

# Session timeout (web inactivity): 15 minutes. Mobile uses /mobile-init to force login on every open.
app.config['SESSION_TIMEOUT_MINUTES'] = int(os.environ.get('SESSION_TIMEOUT_MINUTES', '15'))
# Secure by default (HTTPS only). Set SESSION_COOKIE_SECURE=false in .env for local HTTP development only.
_cookie_secure_env = os.environ.get('SESSION_COOKIE_SECURE', 'true').lower()
app.config['SESSION_COOKIE_SECURE'] = _cookie_secure_env not in ('0', 'false', 'no')
# HttpOnly: JS cannot read the session cookie (XSS mitigation)
app.config['SESSION_COOKIE_HTTPONLY'] = True
# Avoid redirect/cookie issues behind HTTPS proxy (Render)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# Render terminates SSL at proxy; disabling strict Referer check prevents CSRF token mismatch on HTTPS POST.
# Token validation itself still works — only the Referer header comparison is skipped.
app.config['WTF_CSRF_SSL_STRICT'] = False
# Extend CSRF token lifetime to 8 hours so long-running sessions don't get 400 Bad Request errors.
app.config['WTF_CSRF_TIME_LIMIT'] = 28800
# Attendance time control: timezone for comparing current time with Morning/Night windows (e.g. Asia/Karachi)
app.config['APP_TIMEZONE'] = os.environ.get('APP_TIMEZONE', 'Asia/Karachi').strip() or 'Asia/Karachi'
csrf = CSRFProtect(app)

# Initialize SQLAlchemy
print("Connecting to database...")
db.init_app(app)
Migrate(app, db)

# SQLite: FK constraints are OFF by default. Enable them for every new connection.
from sqlalchemy import event
from sqlalchemy.engine import Engine
import sqlite3

@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    if isinstance(dbapi_conn, sqlite3.Connection):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# Jinja filters: date dd-mm-yyyy, CNIC, phone
from utils import format_date_ddmmyyyy, format_cnic, format_phone
app.jinja_env.filters['ddmmyyyy'] = format_date_ddmmyyyy
app.jinja_env.filters['cnic_fmt'] = format_cnic
app.jinja_env.filters['phone_fmt'] = format_phone

from urllib.parse import quote as _url_quote
app.jinja_env.filters['url_quote'] = lambda s: _url_quote(str(s), safe='')

_notif_cache = {}

@app.context_processor
def inject_notification_badge():
    """Unread notification count for current user. Cached 60s per user to avoid per-request queries."""
    import time as _time
    try:
        from flask import session
        from sqlalchemy import and_, or_
        from models import db, Notification, NotificationRead
        user_id = session.get('user_id')
        if not user_id:
            return dict(unread_notification_count=0)
        cache_key = f'notif_{user_id}'
        cached = _notif_cache.get(cache_key)
        if cached and (_time.time() - cached[1]) < 60:
            return dict(unread_notification_count=cached[0])
        subq = db.session.query(NotificationRead.notification_id).filter(NotificationRead.user_id == user_id)
        parking_full = and_(
            Notification.title.ilike('%parking%'),
            or_(Notification.title.ilike('%full%'), db.func.coalesce(Notification.message, '').ilike('%full%'))
        )
        count = Notification.query.filter(~Notification.id.in_(subq)).filter(~parking_full).count()
        _notif_cache[cache_key] = (count, _time.time())
    except Exception as e:
        app.logger.warning('Notification badge error: %s', e)
        count = 0
    return dict(unread_notification_count=count)


@app.context_processor
def inject_current_permissions():
    """Make current user's permission codes, is_master, can_see_page and can_see_section available in templates."""
    from flask import session
    perms = session.get('permissions') or []
    is_master = session.get('is_master', False)
    try:
        from permissions_config import can_see_page, can_see_section
        # Master ke liye role ki value nahi: hamesha sab dikhe, koi permission miss na ho
        can_see_p = (lambda key: True) if is_master else (lambda key: can_see_page(perms, key))
        can_see_s = (lambda key: True) if is_master else (lambda key: can_see_section(perms, key))
    except Exception:
        can_see_p = lambda key: True
        can_see_s = lambda key: True
    return dict(current_permissions=perms, current_user_is_master=is_master, can_see_page=can_see_p, can_see_section=can_see_s)


_districts_cache = {'data': None, 'ts': 0}

@app.context_processor
def inject_all_districts():
    """Provide all district names to templates. Cached 120s to avoid per-request DB hit."""
    import time as _time
    try:
        if _districts_cache['data'] is not None and (_time.time() - _districts_cache['ts']) < 120:
            return dict(all_districts=_districts_cache['data'])
        from models import District
        districts = District.query.order_by(District.name).all()
        _districts_cache['data'] = districts
        _districts_cache['ts'] = _time.time()
    except Exception as e:
        app.logger.warning('Districts injection error: %s', e)
        districts = _districts_cache.get('data') or []
    return dict(all_districts=districts)

@app.context_processor
def inject_server_time():
    """Inject Pakistan server time for the frontend clock."""
    from utils import pk_now
    return dict(server_pk_now=pk_now().strftime('%Y-%m-%dT%H:%M:%S'))

# Create all tables if not exist (backward compatibility; new changes use migrations)
_run_startup_tasks = (not app.debug) or (os.environ.get('WERKZEUG_RUN_MAIN') == 'true')
if _run_startup_tasks:
    with app.app_context():
        print("Creating tables if needed...")
        try:
            db.create_all()
        except Exception as _e:
            print(f"db.create_all() warning (non-fatal): {_e}")
        # Auto-add missing columns to existing tables
        try:
            from sqlalchemy import inspect as _sa_inspect, text as _sa_text
            _inspector = _sa_inspect(db.engine)
            _col_additions = [
                ('driver_transfer', 'is_shift_only', 'BOOLEAN DEFAULT FALSE'),
                ('vehicle_mileage_record', 'selected_km', 'NUMERIC(12,2)'),
                ('red_task', 'fine_amount', 'NUMERIC(12,2) DEFAULT 0'),
                ('red_task', 'driver_id', 'INTEGER REFERENCES driver(id)'),
                ('vehicle_move_without_task', 'fine_amount', 'NUMERIC(12,2) DEFAULT 0'),
                ('vehicle_move_without_task', 'driver_id', 'INTEGER REFERENCES driver(id)'),
                ('penalty_record', 'source_type', 'VARCHAR(30)'),
                ('penalty_record', 'source_id', 'INTEGER'),
                ('vehicle_daily_task', 'start_reading', 'NUMERIC(12,2)'),
                ('employee', 'wallet_account_id', 'INTEGER REFERENCES account(id)'),
                ('driver', 'wallet_account_id', 'INTEGER REFERENCES account(id)'),
                ('account', 'entity_type', 'VARCHAR(30)'),
                ('account', 'entity_id', 'INTEGER'),
                ('fund_transfer', 'from_party_id', 'INTEGER REFERENCES party(id)'),
                ('fund_transfer', 'from_company_id', 'INTEGER REFERENCES company(id)'),
                ('fund_transfer', 'to_party_id', 'INTEGER REFERENCES party(id)'),
                ('fund_transfer', 'to_company_id', 'INTEGER REFERENCES company(id)'),
            ]
            for _tbl, _col, _coltype in _col_additions:
                if _tbl in _inspector.get_table_names():
                    _existing = [c['name'] for c in _inspector.get_columns(_tbl)]
                    if _col not in _existing:
                        db.session.execute(_sa_text(f'ALTER TABLE {_tbl} ADD COLUMN {_col} {_coltype}'))
                        db.session.commit()
                        print(f"Added column {_tbl}.{_col}")
        except Exception as _e:
            print(f"Column migration warning (non-fatal): {_e}")

        # Recreate emergency_task_record / vehicle_mileage_record when schema changed
        try:
            from sqlalchemy import inspect as _sa_inspect2, text as _sa_text2
            _insp = _sa_inspect2(db.engine)
            _tables_to_recreate = {
                'emergency_task_record': {'amb_reg_no', 'task_id_ext', 'request_from'},
                'vehicle_mileage_record': {'reg_no', 'mileage', 'ptop'},
            }
            for _tname, _required_cols in _tables_to_recreate.items():
                if _tname in _insp.get_table_names():
                    _existing_cols = {c['name'] for c in _insp.get_columns(_tname)}
                    if not _required_cols.issubset(_existing_cols):
                        db.session.execute(_sa_text2(f'DROP TABLE IF EXISTS {_tname}'))
                        db.session.commit()
                        print(f"Dropped outdated table {_tname} (will be recreated by create_all)")
            db.create_all()
        except Exception as _e:
            print(f"Table recreation warning (non-fatal): {_e}")
        # Auto-run pending Alembic migrations so Render PostgreSQL stays in sync
        try:
            from flask_migrate import upgrade as _migrate_upgrade
            _migrate_upgrade()
            print("Migrations applied (flask db upgrade).")
        except Exception as _e:
            print(f"Migration upgrade skip: {_e}")
        # Ensure notification.created_by_user_id and related tables exist (SQLite fallback if migration not run)
        try:
            uri = (app.config.get('SQLALCHEMY_DATABASE_URI') or '').strip()
            if uri and 'sqlite' in uri:
                with db.engine.connect() as conn:
                    r = conn.execute(db.text("PRAGMA table_info(notification)"))
                    cols = [row[1] for row in r]
                    if 'created_by_user_id' not in cols:
                        conn.execute(db.text("ALTER TABLE notification ADD COLUMN created_by_user_id INTEGER REFERENCES user(id)"))
                        conn.commit()
                        print("Added notification.created_by_user_id.")
                with db.engine.connect() as conn:
                    conn.execute(db.text("""
                        CREATE TABLE IF NOT EXISTS notification_read (
                            notification_id INTEGER NOT NULL,
                            user_id INTEGER NOT NULL,
                            read_at DATETIME NOT NULL,
                            PRIMARY KEY (notification_id, user_id),
                            FOREIGN KEY(notification_id) REFERENCES notification(id) ON DELETE CASCADE,
                            FOREIGN KEY(user_id) REFERENCES user(id) ON DELETE CASCADE
                        )
                    """))
                    conn.commit()
                with db.engine.connect() as conn:
                    conn.execute(db.text("""
                        CREATE TABLE IF NOT EXISTS reminder (
                            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            title VARCHAR(200) NOT NULL,
                            message TEXT,
                            reminder_date DATE NOT NULL,
                            reminder_time TIME,
                            is_completed BOOLEAN NOT NULL DEFAULT 0,
                            created_at DATETIME,
                            FOREIGN KEY(user_id) REFERENCES user(id) ON DELETE CASCADE
                        )
                    """))
                    conn.commit()
        except Exception as e:
            print("DB schema fallback skip:", e)
        print("Database ready.")
        # Create indexes (IF NOT EXISTS = safe for both SQLite and PostgreSQL)
        try:
            with db.engine.connect() as conn:
                indexes = [
                    "CREATE INDEX IF NOT EXISTS ix_project_start_date ON project (start_date)",
                    "CREATE INDEX IF NOT EXISTS ix_project_status ON project (status)",
                    "CREATE INDEX IF NOT EXISTS ix_driver_phone1 ON driver (phone1)",
                    "CREATE INDEX IF NOT EXISTS ix_driver_district ON driver (driver_district)",
                    "CREATE INDEX IF NOT EXISTS ix_vehicle_model ON vehicle (model)",
                    "CREATE INDEX IF NOT EXISTS ix_vehicle_type ON vehicle (vehicle_type)",
                    "CREATE INDEX IF NOT EXISTS ix_vehicle_active_date ON vehicle (active_date)",
                    "CREATE INDEX IF NOT EXISTS ix_parking_district ON parking_station (district)",
                    "CREATE INDEX IF NOT EXISTS ix_parking_tehsil ON parking_station (tehsil)",
                    "CREATE INDEX IF NOT EXISTS ix_parking_capacity ON parking_station (capacity)",
                    "CREATE INDEX IF NOT EXISTS ix_parking_create_date ON parking_station (create_date)",
                    "CREATE INDEX IF NOT EXISTS ix_district_province ON district (province)",
                    "CREATE INDEX IF NOT EXISTS ix_district_created_at ON district (created_at)",
                    "CREATE INDEX IF NOT EXISTS ix_driver_status ON driver (status)",
                    "CREATE INDEX IF NOT EXISTS ix_fuel_expense_fueling_date ON fuel_expense (fueling_date)",
                    "CREATE INDEX IF NOT EXISTS ix_fuel_expense_vehicle_id ON fuel_expense (vehicle_id)",
                    "CREATE INDEX IF NOT EXISTS ix_journal_entry_project_id ON journal_entry (project_id)",
                    "CREATE INDEX IF NOT EXISTS ix_journal_entry_entry_type ON journal_entry (entry_type)",
                    "CREATE INDEX IF NOT EXISTS ix_driver_attendance_date ON driver_attendance (attendance_date)",
                    "CREATE INDEX IF NOT EXISTS ix_driver_attendance_driver_id ON driver_attendance (driver_id)",
                    "CREATE INDEX IF NOT EXISTS ix_account_account_type ON account (account_type)",
                    "CREATE INDEX IF NOT EXISTS ix_activity_log_created_at ON activity_log (created_at)",
                    "CREATE INDEX IF NOT EXISTS ix_emergency_task_record_task_date ON emergency_task_record (task_date)",
                    "CREATE INDEX IF NOT EXISTS ix_emergency_task_record_amb_reg_no ON emergency_task_record (amb_reg_no)",
                    "CREATE INDEX IF NOT EXISTS ix_vehicle_mileage_record_task_date ON vehicle_mileage_record (task_date)",
                    "CREATE INDEX IF NOT EXISTS ix_vehicle_mileage_record_reg_no ON vehicle_mileage_record (reg_no)",
                    "CREATE INDEX IF NOT EXISTS ix_notification_created_at ON notification (created_at)",
                ]
                for idx_sql in indexes:
                    try:
                        conn.execute(db.text(idx_sql))
                        conn.commit()
                    except Exception:
                        conn.rollback()
                print("Sorting indexes created/verified.")
        except Exception as e:
            print("Index creation skip:", e)
        # Seed default permissions, Admin role, and admin user (if none exist)
        try:
            from auth_utils import seed_auth_tables
            seed_auth_tables(app)
            print("Auth seed done.")
        except Exception as e:
            print("Auth seed skip or error:", e)
        # Seed Chart of Accounts default heads + auto-create accounts for existing entities
        try:
            from routes_finance import seed_chart_of_accounts
            _coa_created = seed_chart_of_accounts()
            if _coa_created:
                print(f"Chart of Accounts: {_coa_created} account(s) seeded/auto-created.")
            else:
                print("Chart of Accounts: already up to date.")
        except Exception as e:
            print(f"CoA seed skip or error: {e}")

# Import routes after app & db are ready
from routes import *  # noqa: E402,F401

# Book management: explicit registration so endpoints always exist (avoids BuildError if routes.py tail not loaded)
from routes_books import register_book_routes  # noqa: E402
register_book_routes(app)

# Import and register finance routes
from routes_finance import (
    accounts_quick_payment, payment_vouchers_list, payment_voucher_edit, payment_voucher_delete,
    accounts_quick_receipt, receipt_vouchers_list,
    accounts_bank_entry, bank_entries_list,
    accounts_account_ledger, accounts_balance_sheet,
    employee_expense_form, employee_expense_list, employee_expense_delete,
    chart_of_accounts_list, chart_of_accounts_add, chart_of_accounts_edit, chart_of_accounts_toggle,
    fund_transfer_add, fund_transfer_edit, fund_transfer_delete, fund_transfers_list,
    wallet_dashboard,
    journal_voucher_add, journal_vouchers_list,
)  # noqa: E402

from routes_payroll import (
    payroll_salary_config_list, payroll_salary_config_form, payroll_salary_config_delete,
    payroll_list, payroll_generate, payroll_view, payroll_edit, payroll_recalc_attendance,
    payroll_finalize, payroll_pay, payroll_revert, payroll_delete,
    payroll_pending, payroll_bulk_generate,
    api_payroll_attendance_preview, payroll_payslip,
    payroll_driver_bulk_salary, api_driver_bulk_preview,
)  # noqa: E402

# Register finance routes
app.add_url_rule('/accounts/payment-voucher', 'accounts_quick_payment', accounts_quick_payment, methods=['GET', 'POST'])
app.add_url_rule('/accounts/payment-vouchers', 'payment_vouchers_list', payment_vouchers_list)
app.add_url_rule('/accounts/payment-voucher/<int:pk>/edit', 'payment_voucher_edit', payment_voucher_edit, methods=['GET', 'POST'])
app.add_url_rule('/accounts/payment-voucher/<int:pk>/delete', 'payment_voucher_delete', payment_voucher_delete, methods=['POST'])

app.add_url_rule('/accounts/receipt-voucher', 'accounts_quick_receipt', accounts_quick_receipt, methods=['GET', 'POST'])
app.add_url_rule('/accounts/receipt-vouchers', 'receipt_vouchers_list', receipt_vouchers_list)

app.add_url_rule('/accounts/bank-entry', 'accounts_bank_entry', accounts_bank_entry, methods=['GET', 'POST'])
app.add_url_rule('/accounts/bank-entries', 'bank_entries_list', bank_entries_list)

app.add_url_rule('/accounts/ledger', 'accounts_account_ledger', accounts_account_ledger, methods=['GET', 'POST'])
app.add_url_rule('/accounts/balance-sheet', 'accounts_balance_sheet', accounts_balance_sheet, methods=['GET', 'POST'])

app.add_url_rule('/accounts/employee-expense/add', 'employee_expense_form', employee_expense_form, methods=['GET', 'POST'])
app.add_url_rule('/accounts/employee-expense/<int:pk>/edit', 'employee_expense_form_edit', employee_expense_form, methods=['GET', 'POST'])
app.add_url_rule('/accounts/employee-expenses', 'employee_expense_list', employee_expense_list)
app.add_url_rule('/accounts/employee-expense/<int:pk>/delete', 'employee_expense_delete', employee_expense_delete, methods=['POST'])

# Chart of Accounts
app.add_url_rule('/accounts/chart', 'chart_of_accounts_list', chart_of_accounts_list)
app.add_url_rule('/accounts/chart/add', 'chart_of_accounts_add', chart_of_accounts_add, methods=['GET', 'POST'])
app.add_url_rule('/accounts/chart/<int:pk>/edit', 'chart_of_accounts_edit', chart_of_accounts_edit, methods=['GET', 'POST'])
app.add_url_rule('/accounts/chart/<int:pk>/toggle', 'chart_of_accounts_toggle', chart_of_accounts_toggle, methods=['POST'])

# Fund Transfer
app.add_url_rule('/accounts/fund-transfer', 'fund_transfer_add', fund_transfer_add, methods=['GET', 'POST'])
app.add_url_rule('/accounts/fund-transfers', 'fund_transfers_list', fund_transfers_list, methods=['GET', 'POST'])
app.add_url_rule('/accounts/fund-transfer/<int:pk>/edit', 'fund_transfer_edit', fund_transfer_edit, methods=['GET', 'POST'])
app.add_url_rule('/accounts/fund-transfer/<int:pk>/delete', 'fund_transfer_delete', fund_transfer_delete, methods=['POST'])

# Wallet Dashboard
app.add_url_rule('/accounts/wallet-dashboard', 'wallet_dashboard', wallet_dashboard, methods=['GET', 'POST'])

# Journal Voucher (replace placeholder)
app.add_url_rule('/accounts/jv', 'accounts_jv', journal_voucher_add, methods=['GET', 'POST'])
app.add_url_rule('/accounts/jv/list', 'journal_vouchers_list', journal_vouchers_list, methods=['GET', 'POST'])

# ── Payroll Module ──────────────────────────────────────────────────────────
app.add_url_rule('/payroll/salary-config', 'payroll_salary_config_list', payroll_salary_config_list)
app.add_url_rule('/payroll/salary-config/new', 'payroll_salary_config_form', payroll_salary_config_form, methods=['GET', 'POST'])
app.add_url_rule('/payroll/salary-config/<int:pk>/edit', 'payroll_salary_config_edit', payroll_salary_config_form, methods=['GET', 'POST'])
app.add_url_rule('/payroll/salary-config/<int:pk>/delete', 'payroll_salary_config_delete', payroll_salary_config_delete, methods=['POST'])
app.add_url_rule('/payroll', 'payroll_list', payroll_list)
app.add_url_rule('/payroll/generate', 'payroll_generate', payroll_generate, methods=['GET', 'POST'])
app.add_url_rule('/payroll/bulk-generate', 'payroll_bulk_generate', payroll_bulk_generate, methods=['GET', 'POST'])
app.add_url_rule('/payroll/<int:pk>', 'payroll_view', payroll_view)
app.add_url_rule('/payroll/<int:pk>/edit', 'payroll_edit', payroll_edit, methods=['GET', 'POST'])
app.add_url_rule('/payroll/<int:pk>/recalc', 'payroll_recalc_attendance', payroll_recalc_attendance, methods=['POST'])
app.add_url_rule('/payroll/<int:pk>/finalize', 'payroll_finalize', payroll_finalize, methods=['POST'])
app.add_url_rule('/payroll/<int:pk>/pay', 'payroll_pay', payroll_pay, methods=['GET', 'POST'])
app.add_url_rule('/payroll/<int:pk>/revert', 'payroll_revert', payroll_revert, methods=['POST'])
app.add_url_rule('/payroll/<int:pk>/delete', 'payroll_delete', payroll_delete, methods=['POST'])
app.add_url_rule('/payroll/pending', 'payroll_pending', payroll_pending)
app.add_url_rule('/payroll/<int:pk>/payslip', 'payroll_payslip', payroll_payslip)
app.add_url_rule('/payroll/driver-bulk-salary', 'payroll_driver_bulk_salary', payroll_driver_bulk_salary, methods=['GET', 'POST'])
app.add_url_rule('/api/payroll/driver-bulk-preview', 'api_driver_bulk_preview', api_driver_bulk_preview)
app.add_url_rule('/api/payroll/attendance-preview', 'api_payroll_attendance_preview', api_payroll_attendance_preview)

# Register Mobile API Blueprint
from api import api_bp  # noqa: E402
app.register_blueprint(api_bp)

# Start backup scheduler if enabled
_backup_scheduler = None
if _run_startup_tasks and app.config.get('BACKUP_SCHEDULE_ENABLED'):
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from backup_utils import run_scheduled_backup
        time_str = (app.config.get('BACKUP_SCHEDULE_TIME') or '02:00').strip()
        parts = time_str.split(':')
        hour = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 2
        minute = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        _backup_scheduler = BackgroundScheduler()
        _backup_scheduler.add_job(
            lambda: run_scheduled_backup(app),
            'cron', hour=hour, minute=minute, id='fleet_backup'
        )
        _backup_scheduler.start()
    except Exception as e:
        app.logger.warning('Backup scheduler failed to start: %s', e)


if __name__ == '__main__':
    print("\n" + "="*50)
    port = int(os.environ.get('PORT', '5000'))
    print(f"Server starting at: http://127.0.0.1:{port}")
    print("Browser mein ye URL open karein. Band karne ke liye Ctrl+C")
    print("="*50 + "\n")
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1', host='0.0.0.0', port=port, use_reloader=False, threaded=True)