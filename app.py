import os
import sys

# ── Project Restructure: add package folders to sys.path ─────────────────────
# This allows moved files (routes/, services/, database/, config/) to keep using
# flat imports (e.g. `from models import ...`, `from app import ...`) without
# changing every import statement in every file.
_app_dir = os.path.dirname(os.path.abspath(__file__))
for _sub in ('routes', 'services', 'database', 'config'):
    _sub_path = os.path.join(_app_dir, _sub)
    if _sub_path not in sys.path:
        sys.path.insert(0, _sub_path)
# ── End path setup ───────────────────────────────────────────────────────────

from flask import Flask
from models import db
import models as _all_models  # force full import so db.create_all() sees every table
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
from datetime import timedelta
from freeze_utils import get_freeze_config

# Load .env from app folder (so it works even when run from another directory)
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
    # Normalize SQLite paths: resolve to absolute, use forward slashes only
    if database_url.startswith('sqlite:///'):
        _db_path_raw = database_url[10:]  # strip sqlite:///
        _db_path_raw = _db_path_raw.replace('\\', '/')
        if not os.path.isabs(_db_path_raw):
            _db_path_raw = os.path.join(_app_dir, _db_path_raw)
        _db_path_abs = os.path.abspath(_db_path_raw).replace('\\', '/')
        database_url = 'sqlite:///' + _db_path_abs
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///company_management.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Render (and any cloud host) silently drops idle PostgreSQL connections.
# pool_pre_ping: test every checked-out connection before use; recycle stale ones.
# pool_recycle: discard connections older than 270 s (below Render's ~300 s idle timeout).
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 270,
}

# ── DB Path Guarantee (local dev mode) ──────────────────────────────────────
if os.environ.get('LOCAL_DB_GUARANTEED'):
    _db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    _db_file = _db_uri.split('///')[-1] if 'sqlite' in _db_uri else _db_uri
    print(f"  [DB GUARANTEE] Using Database: {_db_uri}")
    # HARD BLOCK: must point to db/local.db — nothing else allowed
    if not _db_file.replace('\\', '/').endswith('db/local.db'):
        print("  [FATAL] LOCAL_DB_GUARANTEED is set but DATABASE_URL does not point to db/local.db!")
        print(f"  [FATAL] Got: {_db_uri}")
        print("  [FATAL] Set DATABASE_URL=sqlite:///db/local.db in your environment.")
        sys.exit(1)
    # Verify the file actually exists
    if not os.path.exists(_db_file):
        print(f"  [FATAL] Database file not found: {_db_file}")
        print("  [FATAL] Run FULL SYNC first to create the local database.")
        sys.exit(1)
    print(f"  [DB GUARANTEE] File size: {os.path.getsize(_db_file) / (1024*1024):.1f} MB")

# Engine options: SQLite doesn't support pool_size/max_overflow (uses StaticPool)
_is_sqlite = app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite')
if _is_sqlite:
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
    }
else:
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 10,
        'max_overflow': 20,
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max upload
app.config['TEMPLATES_AUTO_RELOAD'] = (
    os.environ.get('FLASK_DEBUG', '0') == '1'
    or os.environ.get('TEMPLATES_AUTO_RELOAD', '0') == '1'
)

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

# Session timeout (web inactivity): 15 minutes. Mobile Capacitor cold start uses /mobile-init → login.
# WebView may restore dashboard with a stale cookie; base.html redirects to /mobile-init on new process.
# Recent apps resume (same WebView process) keeps session; optional bio/PIN lock in appStateChange.
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
from utils import format_date_ddmmyyyy, format_cnic, format_phone, format_time_ampm, format_reading
app.jinja_env.filters['ddmmyyyy'] = format_date_ddmmyyyy
app.jinja_env.filters['reading'] = format_reading
app.jinja_env.filters['timeampm'] = format_time_ampm
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
        from notification_service import count_unread_inbox_for_user
        user_perms = set(session.get('permissions') or [])
        is_master = session.get('is_master', False)
        count = count_unread_inbox_for_user(user_id, user_perms, is_master)
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
        from permissions_config import (
            can_see_page,
            can_see_section,
            can_see_report_centre,
            can_see_administration_menu,
        )
        # Master ke liye role ki value nahi: hamesha sab dikhe, koi permission miss na ho
        can_see_p = (lambda key: True) if is_master else (lambda key: can_see_page(perms, key))
        can_see_s = (lambda key: True) if is_master else (lambda key: can_see_section(perms, key))
        can_see_rc = (lambda: True) if is_master else (lambda: can_see_report_centre(perms))
        can_see_admin = (
            (lambda: True)
            if is_master
            else (lambda: can_see_administration_menu(perms))
        )
    except Exception:
        can_see_p = lambda key: True
        can_see_s = lambda key: True
        can_see_rc = lambda: True
        can_see_admin = lambda: True
    return dict(
        current_permissions=perms,
        current_user_is_master=is_master,
        can_see_page=can_see_p,
        can_see_section=can_see_s,
        can_see_report_centre=can_see_rc,
        can_see_administration_menu=can_see_admin,
    )


@app.context_processor
def inject_fleet_build_context():
    """Cache-bust + dev banner for Capacitor LAN/USB testing."""
    import os
    import time
    from flask import request
    host_raw = (request.host or '').lower()
    host = host_raw.split(':')[0]
    is_local = host in ('127.0.0.1', 'localhost') or host.startswith('192.168.')
    fleet_dev = is_local
    return {
        'fleet_asset_version': os.environ.get('FLEET_ASSET_VERSION') or str(int(time.time())),
        'fleet_server_host': host_raw,
        'fleet_mobile_dev': fleet_dev,
    }


@app.after_request
def fleet_disable_html_cache(response):
    """Capacitor WebView must not reuse stale HTML after server-side template changes."""
    if request.method != 'GET':
        return response
    ct = (response.content_type or '').lower()
    if 'text/html' in ct:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


@app.context_processor
def inject_all_districts():
    """Provide all district names to templates for dropdown/typeahead."""
    try:
        from models import District
        districts = District.query.order_by(District.name).all()
    except Exception:
        districts = []
    return dict(all_districts=districts)

@app.context_processor
def inject_server_time():
    """Inject Pakistan server time for the frontend clock."""
    from utils import pk_now
    return dict(server_pk_now=pk_now().strftime('%Y-%m-%dT%H:%M:%S'))


@app.context_processor
def inject_freeze_data_status():
    """Provide current freeze status to shared layouts/forms."""
    try:
        cfg = get_freeze_config()
    except Exception:
        cfg = {}
    return dict(freeze_data_status=cfg)


@app.before_request
def sync_navigation_origin():
    """Lock Back return URL when a report opens; keep it across filter/view (no history.back)."""
    try:
        from nav_back import sync_nav_from_session
        sync_nav_from_session()
    except Exception:
        pass


@app.context_processor
def inject_nav_back_auto():
    """Fallback Back URL for hub/report pages (used when route omits nav_back_url)."""
    try:
        from nav_back import build_auto_nav_back
        return build_auto_nav_back()
    except Exception:
        return dict(nav_back_url_auto=None, nav_back_label_auto='Back', nav_from='', nav_back_hub_slug='')


@app.context_processor
def inject_hub_navigation():
    """Hub nav helpers for sidebar (flat links → /hub/<slug>)."""
    from flask import request
    from hub_registry import HUB_ACTIVE_ENDPOINTS

    from hub_registry import hub_slug_for_endpoint

    def hub_nav_active(slug):
        view_args = getattr(request, 'view_args', None) or {}
        if request.endpoint == 'module_hub' and view_args.get('hub_slug') == slug:
            return True
        return hub_slug_for_endpoint(request.endpoint) == slug

    return dict(hub_nav_active=hub_nav_active, HUB_ACTIVE_ENDPOINTS=HUB_ACTIVE_ENDPOINTS)


@app.context_processor
def inject_sidebar_profile_avatar():
    """Driver-linked profile photo for mobile sidebar header."""
    try:
        from flask import session
        from models import User
        from utils import user_profile_avatar_path
        user_id = session.get('user_id')
        path = None
        if user_id:
            user = db.session.get(User, user_id)
            if user:
                path = user_profile_avatar_path(user)
    except Exception:
        path = None
    return dict(sidebar_profile_avatar_path=path)


@app.context_processor
def inject_workspace_context():
    """Expose selected workspace employee in templates."""
    try:
        from flask import session
        from models import Employee
        emp_id = session.get('workspace_employee_id')
        emp = db.session.get(Employee, emp_id) if emp_id else None
    except Exception:
        emp = None
    return dict(workspace_selected_employee=emp)

# Create all tables if not exist (backward compatibility; new changes use migrations)
_run_startup_tasks = (not app.debug) or (os.environ.get('WERKZEUG_RUN_MAIN') == 'true')
if _run_startup_tasks:
    with app.app_context():
        print("Creating tables if needed...")
        try:
            db.create_all()
        except Exception as _e:
            print(f"db.create_all() warning (non-fatal): {_e}")
        # Ensure new tables exist
        try:
            db.create_all()
        except Exception as _e2:
            print(f"Second db.create_all() warning: {_e2}")

        try:
            from models import WorkspaceSlipProfile, WorkspaceSlipProfileField, ClientDiagnosticLog
            WorkspaceSlipProfile.__table__.create(db.engine, checkfirst=True)
            WorkspaceSlipProfileField.__table__.create(db.engine, checkfirst=True)
            ClientDiagnosticLog.__table__.create(db.engine, checkfirst=True)
        except Exception as _e:
            print(f"workspace_slip_profile / client_diagnostic_log ensure warning (non-fatal): {_e}")

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
                ('vehicle_daily_task', 'odometer_photo_path', 'TEXT'),
                ('vehicle_activity_record', 'latitude', 'NUMERIC(10,6)'),
                ('vehicle_activity_record', 'longitude', 'NUMERIC(10,6)'),
                ('employee', 'wallet_account_id', 'INTEGER REFERENCES account(id)'),
                ('employee', 'last_slip_profile_id', 'INTEGER REFERENCES workspace_slip_profile(id)'),
                ('workspace_slip_profile_field', 'ocr_recipe_json', 'TEXT'),
                ('driver', 'wallet_account_id', 'INTEGER REFERENCES account(id)'),
                ('account', 'entity_type', 'VARCHAR(30)'),
                ('account', 'entity_id', 'INTEGER'),
                ('fund_transfer', 'from_party_id', 'INTEGER REFERENCES party(id)'),
                ('fund_transfer', 'from_company_id', 'INTEGER REFERENCES company(id)'),
                ('fund_transfer', 'to_party_id', 'INTEGER REFERENCES party(id)'),
                ('fund_transfer', 'to_company_id', 'INTEGER REFERENCES company(id)'),
                ('fund_transfer', 'attachment', 'VARCHAR(500)'),
                ('fund_transfer', 'is_salary', 'BOOLEAN DEFAULT FALSE'),
                ('fund_transfer', 'from_account_id', 'INTEGER REFERENCES account(id)'),
                ('fund_transfer', 'to_account_id', 'INTEGER REFERENCES account(id)'),
                ('fund_transfer', 'category', 'VARCHAR(30)'),
                ('journal_entry', 'category', 'VARCHAR(30)'),
                # Workspace tables fallback (when migration wasn't applied yet)
                ('workspace_party', 'district_id', 'INTEGER REFERENCES district(id)'),
                ('workspace_party', 'contact', 'VARCHAR(100)'),
                ('workspace_party', 'remarks', 'TEXT'),
                ('workspace_opening_expense', 'journal_entry_id', 'INTEGER REFERENCES workspace_journal_entry(id)'),
                ('workspace_opening_expense', 'month_close_id', 'INTEGER REFERENCES workspace_month_close(id)'),
                ('workspace_fuel_oil_opening_expense', 'fuel_oil_month_close_id', 'INTEGER REFERENCES workspace_fuel_oil_month_close(id)'),
                ('workspace_month_close', 'district_id', 'INTEGER REFERENCES district(id)'),
                ('workspace_month_close', 'project_id', 'INTEGER REFERENCES project(id)'),
                ('workspace_journal_entry', 'district_id', 'INTEGER REFERENCES district(id)'),
                ('workspace_journal_entry', 'project_id', 'INTEGER REFERENCES project(id)'),
                ('vehicle', 'vehicle_family', 'VARCHAR(100)'),
                ('driver', 'license_valid_from', 'DATE'),
                ('driver', 'verify_license_photo_path', 'VARCHAR(500)'),
                ('driver_document_history', 'batch_id', 'VARCHAR(36)'),
                ('driver_document_history', 'update_source', 'VARCHAR(20)'),
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
            err = str(_e)
            print(f"Migration upgrade skip: {_e}")
            # If DB alembic_version references a missing revision, stamp back to last known good head.
            if "Can't locate revision identified by" in err:
                try:
                    from flask_migrate import stamp as _migrate_stamp
                    _migrate_stamp(revision='u1v2w3x4y5z6')
                    print("Alembic stamped to u1v2w3x4y5z6 after missing-revision recovery.")
                    _migrate_upgrade()
                    print("Migrations applied after recovery stamp.")
                except Exception as _e2:
                    print(f"Migration recovery skip (tables may still exist via create_all): {_e2}")
        # Auto-sync R2 CORS for browser direct uploads (non-fatal)
        try:
            _auto_cors = (os.environ.get('R2_AUTO_SYNC_CORS', 'true') or 'true').strip().lower() in ('1', 'true', 'yes')
            if _auto_cors:
                _origins = []
                for _k in ('APP_BASE_URL', 'PUBLIC_BASE_URL', 'RENDER_EXTERNAL_URL'):
                    _v = (os.environ.get(_k) or '').strip().rstrip('/')
                    if _v.startswith('http://') or _v.startswith('https://'):
                        _origins.append(_v)
                _extra = (os.environ.get('R2_CORS_ALLOWED_ORIGINS') or '').strip()
                if _extra:
                    _origins.extend([x.strip().rstrip('/') for x in _extra.split(',') if x.strip()])
                _origins = list(dict.fromkeys(_origins))
                if _origins:
                    from r2_storage import ensure_expense_upload_cors
                    _changed, _msg = ensure_expense_upload_cors(_origins)
                    print(f"R2 CORS sync: {_msg}; origins={len(_origins)}; changed={_changed}")
                else:
                    print("R2 CORS sync skipped: no origins configured.")
        except Exception as _e:
            print(f"R2 CORS sync skip: {_e}")
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
                    r2 = conn.execute(db.text("PRAGMA table_info(notification)"))
                    cols2 = [row[1] for row in r2]
                    if 'target_user_id' not in cols2:
                        conn.execute(db.text("ALTER TABLE notification ADD COLUMN target_user_id INTEGER REFERENCES user(id)"))
                        conn.commit()
                        print("Added notification.target_user_id.")
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
        try:
            from sqlalchemy import inspect, text
            insp = inspect(db.engine)
            cols = [c['name'] for c in insp.get_columns('user')]
            if 'biometric_token_version' not in cols:
                tbl = '"user"' if db.engine.dialect.name == 'postgresql' else 'user'
                db.session.execute(text(
                    f'ALTER TABLE {tbl} ADD COLUMN biometric_token_version INTEGER NOT NULL DEFAULT 0'
                ))
                db.session.commit()
                print('Added user.biometric_token_version column.')
        except Exception as e:
            db.session.rollback()
            print('Biometric column migrate skip:', e)
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
                    "CREATE INDEX IF NOT EXISTS ix_vehicle_family ON vehicle (vehicle_family)",
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
        try:
            from notification_service import purge_legacy_notifications_once
            if purge_legacy_notifications_once():
                print('Notifications v2: legacy inbox cleared.')
        except Exception as e:
            print('Notifications v2 init skip or error:', e)
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

        # Backfill EmployeeAssignment for employees with existing M2M assignments but no history
        try:
            from models import Employee, EmployeeAssignment, employee_project, employee_district
            from utils import pk_date as _pk_date
            _today = _pk_date()
            _existing_emp_ids = set(
                r[0] for r in db.session.query(EmployeeAssignment.employee_id).distinct().all()
            )
            _all_emps = Employee.query.all()
            _backfilled = 0
            for _emp in _all_emps:
                if _emp.id in _existing_emp_ids:
                    continue
                _has_any = False
                for _proj in _emp.projects:
                    ea = EmployeeAssignment(
                        employee_id=_emp.id, action='initial',
                        project_id=_proj.id, effective_date=_today,
                        remarks='Auto-backfilled from existing assignment',
                    )
                    db.session.add(ea)
                    _has_any = True
                for _dist in _emp.districts:
                    ea = EmployeeAssignment(
                        employee_id=_emp.id, action='initial',
                        district_id=_dist.id, effective_date=_today,
                        remarks='Auto-backfilled from existing assignment',
                    )
                    db.session.add(ea)
                    _has_any = True
                if _has_any:
                    _backfilled += 1
            if _backfilled:
                db.session.commit()
                print(f"Employee Assignment backfill: {_backfilled} employee(s) populated.")
            else:
                print("Employee Assignment backfill: nothing to do.")
        except Exception as _e:
            db.session.rollback()
            print(f"Employee Assignment backfill skip: {_e}")

# Import routes after app & db are ready
from routes import *  # noqa: E402,F401
import routes_tool_workstation  # noqa: E402,F401 — Tool Workstation (120 utilities)
import routes_system  # noqa: E402,F401 — System health, tracker automation, driver doc portal
import routes_reports  # noqa: E402,F401 — Report Centre, summary reports, driver/vehicle profiles
import routes_transfers  # noqa: E402,F401 — Project, vehicle, driver transfers
import routes_assignments  # noqa: E402,F401 — Project/Vehicle/Driver assignments
import routes_expenses  # noqa: E402,F401 — Fuel, Oil, Maintenance expenses + work orders
import routes_attendance  # noqa: E402,F401 — Driver attendance, GPS check-in/out, TRA report
import routes_misc  # noqa: E402,F401 — Misc: APIs, PWA, FCM, Account, Biometric, Mobile Init
import routes_auth  # noqa: E402,F401 — Auth, Users, Roles, Permissions, Form Control
import routes_dashboard  # noqa: E402,F401 — Dashboard, Notifications, Reminders, App Updates
import routes_master_data  # noqa: E402,F401 — Master data: Companies, Projects, Vehicles, Drivers, Parking, Districts, Parties, Products
import routes_employees  # noqa: E402,F401 — Employees: Workforce Lifecycle, Assignments
import routes_tasks  # noqa: E402,F401 — Task Reports: Core Task Reports, Logbooks
import routes_task_ops  # noqa: E402,F401 — Task Ops: Red Tasks, Without Task, Penalty Records
import routes_tracker_reports  # noqa: E402,F401 — Tracker & Operations Reports
import routes_workforce  # noqa: E402,F401 — Workforce: Job Left, Rejoin, Leave, Driver Posts

# Book management: explicit registration so endpoints always exist (avoids BuildError if routes.py tail not loaded)
from routes_books import register_book_routes  # noqa: E402
register_book_routes(app)

# Import and register finance routes
from routes_finance import (
    accounts_quick_payment, payment_vouchers_list, payment_voucher_edit, payment_voucher_delete,
    accounts_quick_receipt, receipt_vouchers_list,
    accounts_bank_entry, bank_entries_list,
    accounts_account_ledger, accounts_balance_sheet,
    employee_expense_form, employee_expense_list,     employee_expense_view, employee_expense_delete,
    employee_expense_media, employee_expense_media_download, employee_expense_media_download_all,
    employee_expense_receipt_push_cloud, employee_expense_description_suggestions_api,
    chart_of_accounts_list, chart_of_accounts_add, chart_of_accounts_edit, chart_of_accounts_toggle,
    fund_transfer_add, fund_transfer_edit, fund_transfer_delete, fund_transfers_list,
    fund_transfer_view, fund_transfer_media,
    wallet_dashboard,
    journal_voucher_add, journal_vouchers_list, journal_voucher_detail,
    bank_directory_list_api, bank_directory_add_api, bank_directory_delete_api, bank_directory_update_api,
    ft_description_suggestions_api, ft_categories_list_api, ft_categories_add_api,
)  # noqa: E402

from routes_workspace import (
    workspace_dashboard, workspace_home, workspace_select_employee, workspace_clear_employee,
    workspace_parties_list, workspace_party_form, workspace_party_delete, workspace_party_export,
    workspace_party_print, workspace_party_import, workspace_party_import_template,
    workspace_party_names_api,
    workspace_products_list, workspace_product_form, workspace_product_delete, workspace_product_export,
    workspace_product_print, workspace_product_import, workspace_product_import_template,
    workspace_product_names_api,
    workspace_accounts_list, workspace_account_form,
    workspace_expenses_list, workspace_expense_form, workspace_expense_delete,
    workspace_opening_expenses_list, workspace_opening_expense_form, workspace_opening_expense_delete,
    workspace_opening_expense_export, workspace_opening_expense_print,
    workspace_opening_expense_import, workspace_opening_expense_import_template,
    workspace_fuel_oil_openings_list, workspace_fuel_oil_opening_form, workspace_fuel_oil_opening_delete,
    workspace_fuel_oil_opening_export, workspace_fuel_oil_opening_print,
    workspace_fuel_oil_opening_import, workspace_fuel_oil_opening_import_template,
    workspace_fuel_oil_month_close, workspace_fuel_oil_month_close_list, workspace_fuel_oil_month_close_reverse,
    workspace_fund_transfers_list, workspace_fund_transfer_form, workspace_fund_transfer_delete,
    workspace_fund_transfer_view, workspace_fund_transfer_media,
    workspace_fund_transfer_media_download, workspace_fund_transfer_media_download_all,
    workspace_ledger, workspace_ledger_transfer_detail, workspace_ledger_journal_detail, workspace_balance_sheet, workspace_month_close, workspace_month_close_list, workspace_month_close_reverse, workspace_reports, workspace_mpg_report, workspace_dashboard_financial_report,
    workspace_journal_voucher_add, workspace_journal_vouchers_list, workspace_journal_voucher_detail, workspace_jv_backfill_district_project,
    workspace_journal_voucher_edit, workspace_journal_voucher_delete, workspace_journal_voucher_duplicate, workspace_journal_vouchers_export,
    workspace_transfer_description_suggestions_api,
    workspace_slip_profiles_api,
    workspace_slip_profile_delete_api,
    workspace_slip_profile_update_api,
    workspace_slip_last_profile_api,
    workspace_transfer_ref_check_api,
    workspace_account_balance_api,
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
app.add_url_rule('/accounts/employee-expense/<int:pk>/view', 'employee_expense_view', employee_expense_view)
app.add_url_rule('/accounts/employee-expense/<int:pk>/media', 'employee_expense_media', employee_expense_media)
app.add_url_rule(
    '/accounts/employee-expense/<int:pk>/media/download',
    'employee_expense_media_download',
    employee_expense_media_download,
)
app.add_url_rule(
    '/accounts/employee-expense/<int:pk>/media/download-all',
    'employee_expense_media_download_all',
    employee_expense_media_download_all,
)
app.add_url_rule(
    '/accounts/employee-expense/<int:pk>/receipt-push-cloud',
    'employee_expense_receipt_push_cloud',
    employee_expense_receipt_push_cloud,
    methods=['POST'],
)
app.add_url_rule('/api/employee-expense-descriptions', 'employee_expense_description_suggestions', employee_expense_description_suggestions_api, methods=['GET'])

# Chart of Accounts
app.add_url_rule('/accounts/chart', 'chart_of_accounts_list', chart_of_accounts_list)
app.add_url_rule('/accounts/chart/add', 'chart_of_accounts_add', chart_of_accounts_add, methods=['GET', 'POST'])
app.add_url_rule('/accounts/chart/<int:pk>/edit', 'chart_of_accounts_edit', chart_of_accounts_edit, methods=['GET', 'POST'])
app.add_url_rule('/accounts/chart/<int:pk>/toggle', 'chart_of_accounts_toggle', chart_of_accounts_toggle, methods=['POST'])

# Fund Transfer
app.add_url_rule('/accounts/fund-transfer', 'fund_transfer_add', fund_transfer_add, methods=['GET', 'POST'])
app.add_url_rule('/accounts/fund-transfers', 'fund_transfers_list', fund_transfers_list, methods=['GET', 'POST'])
app.add_url_rule('/accounts/fund-transfer/<int:pk>/view', 'fund_transfer_view', fund_transfer_view, methods=['GET'])
app.add_url_rule('/accounts/fund-transfer/<int:pk>/media', 'fund_transfer_media', fund_transfer_media, methods=['GET'])
app.add_url_rule('/accounts/fund-transfer/<int:pk>/edit', 'fund_transfer_edit', fund_transfer_edit, methods=['GET', 'POST'])
app.add_url_rule('/accounts/fund-transfer/<int:pk>/delete', 'fund_transfer_delete', fund_transfer_delete, methods=['POST'])

# Wallet Dashboard
app.add_url_rule('/accounts/wallet-dashboard', 'wallet_dashboard', wallet_dashboard, methods=['GET', 'POST'])

# Fund Transfer description autocomplete
app.add_url_rule('/api/ft-descriptions', 'ft_description_suggestions', ft_description_suggestions_api, methods=['GET'])
app.add_url_rule('/api/ft-categories', 'ft_categories_list', ft_categories_list_api, methods=['GET'])
app.add_url_rule('/api/ft-categories/add', 'ft_categories_add', ft_categories_add_api, methods=['POST'])

# Bank Account Directory API
app.add_url_rule('/api/bank-directory', 'bank_directory_list', bank_directory_list_api, methods=['GET'])
app.add_url_rule('/api/bank-directory/add', 'bank_directory_add', bank_directory_add_api, methods=['POST'])
app.add_url_rule('/api/bank-directory/<int:pk>/delete', 'bank_directory_delete', bank_directory_delete_api, methods=['POST'])
app.add_url_rule('/api/bank-directory/<int:pk>/update', 'bank_directory_update', bank_directory_update_api, methods=['POST'])

# Journal Voucher (replace placeholder)
app.add_url_rule('/accounts/jv', 'accounts_jv', journal_voucher_add, methods=['GET', 'POST'])
app.add_url_rule('/accounts/jv/list', 'journal_vouchers_list', journal_vouchers_list, methods=['GET', 'POST'])
app.add_url_rule('/accounts/jv/<int:pk>', 'journal_voucher_detail', journal_voucher_detail, methods=['GET'])

# Employee Financial Workspace
app.add_url_rule('/workspace', 'workspace_dashboard', workspace_dashboard)
app.add_url_rule('/workspace/home', 'workspace_home', workspace_home)
app.add_url_rule('/workspace/select-employee', 'workspace_select_employee', workspace_select_employee, methods=['POST'])
app.add_url_rule('/workspace/clear-employee', 'workspace_clear_employee', workspace_clear_employee)
app.add_url_rule('/workspace/parties', 'workspace_parties_list', workspace_parties_list)
app.add_url_rule('/workspace/parties/export', 'workspace_party_export', workspace_party_export)
app.add_url_rule('/workspace/parties/print', 'workspace_party_print', workspace_party_print)
app.add_url_rule('/workspace/parties/import', 'workspace_party_import', workspace_party_import, methods=['GET', 'POST'])
app.add_url_rule('/workspace/parties/import/template', 'workspace_party_import_template', workspace_party_import_template)
app.add_url_rule('/workspace/party/new', 'workspace_party_new', workspace_party_form, methods=['GET', 'POST'])
app.add_url_rule('/workspace/party/<int:pk>/edit', 'workspace_party_edit', workspace_party_form, methods=['GET', 'POST'])
app.add_url_rule('/workspace/party/<int:pk>/delete', 'workspace_party_delete', workspace_party_delete, methods=['POST'])
app.add_url_rule('/workspace/products', 'workspace_products_list', workspace_products_list)
app.add_url_rule('/workspace/products/export', 'workspace_product_export', workspace_product_export)
app.add_url_rule('/workspace/products/print', 'workspace_product_print', workspace_product_print)
app.add_url_rule('/workspace/products/import', 'workspace_product_import', workspace_product_import, methods=['GET', 'POST'])
app.add_url_rule('/workspace/products/import/template', 'workspace_product_import_template', workspace_product_import_template)
app.add_url_rule('/workspace/product/new', 'workspace_product_new', workspace_product_form, methods=['GET', 'POST'])
app.add_url_rule('/workspace/product/<int:pk>/edit', 'workspace_product_edit', workspace_product_form, methods=['GET', 'POST'])
app.add_url_rule('/workspace/product/<int:pk>/delete', 'workspace_product_delete', workspace_product_delete, methods=['POST'])
app.add_url_rule('/api/workspace-party-names', 'workspace_party_names_api', workspace_party_names_api, methods=['GET'])
app.add_url_rule('/api/workspace-product-names', 'workspace_product_names_api', workspace_product_names_api, methods=['GET'])
app.add_url_rule('/workspace/accounts', 'workspace_accounts_list', workspace_accounts_list)
app.add_url_rule('/workspace/account/new', 'workspace_account_new', workspace_account_form, methods=['GET', 'POST'])
app.add_url_rule('/workspace/account/<int:pk>/edit', 'workspace_account_edit', workspace_account_form, methods=['GET', 'POST'])
app.add_url_rule('/workspace/expenses', 'workspace_expenses_list', workspace_expenses_list)
app.add_url_rule('/workspace/expense/new', 'workspace_expense_new', workspace_expense_form, methods=['GET', 'POST'])
app.add_url_rule('/workspace/expense/<int:pk>/edit', 'workspace_expense_edit', workspace_expense_form, methods=['GET', 'POST'])
app.add_url_rule('/workspace/expense/<int:pk>/delete', 'workspace_expense_delete', workspace_expense_delete, methods=['POST'])
app.add_url_rule('/workspace/opening-expenses', 'workspace_opening_expenses_list', workspace_opening_expenses_list)
app.add_url_rule('/workspace/opening-expenses/export', 'workspace_opening_expense_export', workspace_opening_expense_export)
app.add_url_rule('/workspace/opening-expenses/print', 'workspace_opening_expense_print', workspace_opening_expense_print)
app.add_url_rule('/workspace/opening-expenses/import', 'workspace_opening_expense_import', workspace_opening_expense_import, methods=['GET', 'POST'])
app.add_url_rule('/workspace/opening-expenses/import/template', 'workspace_opening_expense_import_template', workspace_opening_expense_import_template)
app.add_url_rule('/workspace/opening-expense/new', 'workspace_opening_expense_new', workspace_opening_expense_form, methods=['GET', 'POST'])
app.add_url_rule('/workspace/opening-expense/<int:pk>/edit', 'workspace_opening_expense_edit', workspace_opening_expense_form, methods=['GET', 'POST'])
app.add_url_rule('/workspace/opening-expense/<int:pk>/delete', 'workspace_opening_expense_delete', workspace_opening_expense_delete, methods=['POST'])
app.add_url_rule('/workspace/fuel-oil-openings', 'workspace_fuel_oil_openings_list', workspace_fuel_oil_openings_list)
app.add_url_rule('/workspace/fuel-oil-openings/export', 'workspace_fuel_oil_opening_export', workspace_fuel_oil_opening_export)
app.add_url_rule('/workspace/fuel-oil-openings/print', 'workspace_fuel_oil_opening_print', workspace_fuel_oil_opening_print)
app.add_url_rule('/workspace/fuel-oil-openings/import', 'workspace_fuel_oil_opening_import', workspace_fuel_oil_opening_import, methods=['GET', 'POST'])
app.add_url_rule('/workspace/fuel-oil-openings/import/template', 'workspace_fuel_oil_opening_import_template', workspace_fuel_oil_opening_import_template)
app.add_url_rule('/workspace/fuel-oil-opening/new', 'workspace_fuel_oil_opening_new', workspace_fuel_oil_opening_form, methods=['GET', 'POST'])
app.add_url_rule('/workspace/fuel-oil-opening/<int:pk>/edit', 'workspace_fuel_oil_opening_edit', workspace_fuel_oil_opening_form, methods=['GET', 'POST'])
app.add_url_rule('/workspace/fuel-oil-opening/<int:pk>/delete', 'workspace_fuel_oil_opening_delete', workspace_fuel_oil_opening_delete, methods=['POST'])
app.add_url_rule('/workspace/fuel-oil-close', 'workspace_fuel_oil_month_close', workspace_fuel_oil_month_close, methods=['GET', 'POST'])
app.add_url_rule('/workspace/fuel-oil-close/list', 'workspace_fuel_oil_month_close_list', workspace_fuel_oil_month_close_list)
app.add_url_rule('/workspace/fuel-oil-close/<int:pk>/reverse', 'workspace_fuel_oil_month_close_reverse', workspace_fuel_oil_month_close_reverse, methods=['POST'])
app.add_url_rule('/workspace/transfers', 'workspace_fund_transfers_list', workspace_fund_transfers_list)
app.add_url_rule('/workspace/transfer/new', 'workspace_fund_transfer_new', workspace_fund_transfer_form, methods=['GET', 'POST'])
app.add_url_rule('/workspace/transfer/<int:pk>/view', 'workspace_fund_transfer_view', workspace_fund_transfer_view, methods=['GET'])
app.add_url_rule('/workspace/transfer/<int:pk>/media', 'workspace_fund_transfer_media', workspace_fund_transfer_media, methods=['GET'])
app.add_url_rule('/workspace/transfer/<int:pk>/media/download', 'workspace_fund_transfer_media_download', workspace_fund_transfer_media_download, methods=['GET'])
app.add_url_rule('/workspace/transfer/<int:pk>/media/download-all', 'workspace_fund_transfer_media_download_all', workspace_fund_transfer_media_download_all, methods=['GET'])
app.add_url_rule('/workspace/transfer/<int:pk>/edit', 'workspace_fund_transfer_edit', workspace_fund_transfer_form, methods=['GET', 'POST'])
app.add_url_rule('/workspace/transfer/<int:pk>/delete', 'workspace_fund_transfer_delete', workspace_fund_transfer_delete, methods=['POST'])
app.add_url_rule('/workspace/journal-voucher', 'workspace_journal_voucher_add', workspace_journal_voucher_add, methods=['GET', 'POST'])
app.add_url_rule('/workspace/journal-vouchers', 'workspace_journal_vouchers_list', workspace_journal_vouchers_list, methods=['GET', 'POST'])
app.add_url_rule('/workspace/journal-voucher/<int:pk>', 'workspace_journal_voucher_detail', workspace_journal_voucher_detail, methods=['GET'])
app.add_url_rule('/workspace/journal-voucher/<int:pk>/edit', 'workspace_journal_voucher_edit', workspace_journal_voucher_edit, methods=['GET', 'POST'])
app.add_url_rule('/workspace/journal-voucher/<int:pk>/delete', 'workspace_journal_voucher_delete', workspace_journal_voucher_delete, methods=['POST'])
app.add_url_rule('/workspace/journal-voucher/<int:pk>/duplicate', 'workspace_journal_voucher_duplicate', workspace_journal_voucher_duplicate, methods=['GET'])
app.add_url_rule('/workspace/journal-vouchers/export', 'workspace_journal_vouchers_export', workspace_journal_vouchers_export, methods=['GET'])
app.add_url_rule('/workspace/journal-vouchers/backfill', 'workspace_jv_backfill_district_project', workspace_jv_backfill_district_project, methods=['GET'])
app.add_url_rule('/api/workspace-transfer-descriptions', 'workspace_transfer_description_suggestions', workspace_transfer_description_suggestions_api, methods=['GET'])
app.add_url_rule('/api/workspace-slip-profiles', 'workspace_slip_profiles', workspace_slip_profiles_api, methods=['GET', 'POST'])
app.add_url_rule('/api/workspace-slip-profiles/<int:pk>', 'workspace_slip_profile_delete', workspace_slip_profile_delete_api, methods=['DELETE'])
app.add_url_rule('/api/workspace-slip-profiles/<int:pk>', 'workspace_slip_profile_update', workspace_slip_profile_update_api, methods=['PATCH'])
app.add_url_rule('/api/workspace-slip-last-profile', 'workspace_slip_last_profile', workspace_slip_last_profile_api, methods=['GET', 'POST'])
app.add_url_rule('/api/workspace-transfer-ref-check', 'workspace_transfer_ref_check', workspace_transfer_ref_check_api, methods=['GET'])
app.add_url_rule('/api/workspace-account-balance', 'workspace_account_balance_api', workspace_account_balance_api, methods=['GET'])
app.add_url_rule('/workspace/ledger', 'workspace_ledger', workspace_ledger)
app.add_url_rule('/workspace/ledger/fund-transfer/<int:transfer_id>', 'workspace_ledger_transfer_detail', workspace_ledger_transfer_detail)
app.add_url_rule('/workspace/ledger/journal/<int:journal_entry_id>', 'workspace_ledger_journal_detail', workspace_ledger_journal_detail)
app.add_url_rule('/workspace/balance-sheet', 'workspace_balance_sheet', workspace_balance_sheet)
app.add_url_rule('/workspace/month-close', 'workspace_month_close', workspace_month_close, methods=['GET', 'POST'])
app.add_url_rule('/workspace/month-close/list', 'workspace_month_close_list', workspace_month_close_list)
app.add_url_rule('/workspace/month-close/<int:pk>/reverse', 'workspace_month_close_reverse', workspace_month_close_reverse, methods=['POST'])
app.add_url_rule('/workspace/reports', 'workspace_reports', workspace_reports)
app.add_url_rule('/workspace/reports/mpg', 'workspace_mpg_report', workspace_mpg_report, methods=['GET', 'POST'])
app.add_url_rule('/workspace/dashboard-report/<string:kind>', 'workspace_dashboard_financial_report', workspace_dashboard_financial_report)

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

# Master Mind AI assistant routes
from routes_ai import ai_bp  # noqa: E402
app.register_blueprint(ai_bp)

# Start backup scheduler from DB/env settings (see backup_config.py)
if _run_startup_tasks:
    with app.app_context():
        try:
            from backup_config import start_backup_scheduler
            start_backup_scheduler(app)
        except Exception as e:
            app.logger.warning('Backup scheduler failed to start: %s', e)
        try:
            from attendance_reminder_scheduler import start_attendance_reminder_scheduler
            start_attendance_reminder_scheduler(app)
        except Exception as e:
            app.logger.warning('Attendance reminder scheduler failed to start: %s', e)
        try:
            from expiry_reminder_scheduler import start_expiry_reminder_scheduler
            start_expiry_reminder_scheduler(app)
        except Exception as e:
            app.logger.warning('Expiry/Oil reminder scheduler failed to start: %s', e)
        try:
            from fuel_market_scan_scheduler import start_fuel_market_scan_scheduler
            start_fuel_market_scan_scheduler(app)
        except Exception as e:
            app.logger.warning('Fuel market scan scheduler failed to start: %s', e)


if __name__ == '__main__':
    print("\n" + "="*50)
    port = int(os.environ.get('PORT', '5000'))
    print(f"Server starting at: http://127.0.0.1:{port}")
    print("Browser mein ye URL open karein. Band karne ke liye Ctrl+C")
    print("="*50 + "\n")
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1', host='0.0.0.0', port=port, use_reloader=False, threaded=True)