from flask import Flask
from models import db
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
from datetime import timedelta
import os

# Load .env from app folder (so it works even when run from another directory)
_app_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_app_dir, '.env'))

print("Starting app...")
app = Flask(__name__)

# When behind a reverse proxy (e.g. Render), trust X-Forwarded-Proto and X-Forwarded-Host
# so redirects and session cookies use the correct scheme (https) and host. Fixes ERR_TOO_MANY_REDIRECTS.
try:
    from werkzeug.middleware.proxy_fix import ProxyFix
    # Use depth 2 in case Render has multiple proxy hops (e.g. edge -> app server)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=2, x_host=2)
except ImportError:
    pass

# Secret key / DB config (env first, fallback to current defaults)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-me-please-make-it-strong')
# When "Remember me" is checked, session lasts this long (default 7 days)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=int(os.environ.get('SESSION_DAYS', '7')))

# Database URL: Render (and some hosts) give postgres:// but SQLAlchemy 1.4+ requires postgresql://
database_url = os.environ.get('DATABASE_URL', 'sqlite:///company_management.db')
if database_url:
    database_url = database_url.strip()
    if database_url.startswith('postgres://'):
        database_url = 'postgresql://' + database_url[9:]
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///company_management.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max upload

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

# Session timeout; PERMANENT_SESSION_LIFETIME when "Remember me" is checked
app.config['SESSION_TIMEOUT_MINUTES'] = int(os.environ.get('SESSION_TIMEOUT_MINUTES', '60'))
app.config['PERMANENT_SESSION_LIFETIME'] = __import__('datetime').timedelta(days=7)
# On Render: set SESSION_COOKIE_SECURE=true in Environment so cookie is sent only over HTTPS (use with ProxyFix).
if os.environ.get('SESSION_COOKIE_SECURE', '').lower() in ('1', 'true', 'yes'):
    app.config['SESSION_COOKIE_SECURE'] = True
# Avoid redirect/cookie issues behind HTTPS proxy (Render)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
csrf = CSRFProtect(app)

# Initialize SQLAlchemy
print("Connecting to database...")
db.init_app(app)
Migrate(app, db)

# Jinja filters: date dd-mm-yyyy, CNIC, phone
from utils import format_date_ddmmyyyy, format_cnic, format_phone
app.jinja_env.filters['ddmmyyyy'] = format_date_ddmmyyyy
app.jinja_env.filters['cnic_fmt'] = format_cnic
app.jinja_env.filters['phone_fmt'] = format_phone


@app.context_processor
def inject_notification_badge():
    """Unread notification count for current user (per-user read via NotificationRead). Excludes Parking full."""
    try:
        from flask import session
        from sqlalchemy import and_, or_
        from models import db, Notification, NotificationRead
        user_id = session.get('user_id')
        if not user_id:
            return dict(unread_notification_count=0)
        subq = db.session.query(NotificationRead.notification_id).filter(NotificationRead.user_id == user_id)
        # Exclude "Parking full" notifications from count
        parking_full = and_(
            Notification.title.ilike('%parking%'),
            or_(Notification.title.ilike('%full%'), db.func.coalesce(Notification.message, '').ilike('%full%'))
        )
        count = Notification.query.filter(~Notification.id.in_(subq)).filter(~parking_full).count()
    except Exception:
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


@app.context_processor
def inject_all_districts():
    """
    Provide all district names to templates for dropdown/typeahead.
    """
    try:
        from models import District
        districts = District.query.order_by(District.name).all()
    except Exception:
        districts = []
    return dict(all_districts=districts)

# Create all tables if not exist (backward compatibility; new changes use migrations)
with app.app_context():
    print("Creating tables if needed...")
    db.create_all()
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
    # Seed default permissions, Admin role, and admin user (if none exist)
    try:
        from auth_utils import seed_auth_tables
        seed_auth_tables(app)
        print("Auth seed done.")
    except Exception as e:
        print("Auth seed skip or error:", e)

# Import routes after app & db are ready
from routes import *  # noqa: E402,F401

# Start backup scheduler if enabled
_backup_scheduler = None
if app.config.get('BACKUP_SCHEDULE_ENABLED'):
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
    except Exception:
        pass


if __name__ == '__main__':
    print("\n" + "="*50)
    print("Server starting at: http://127.0.0.1:5000")
    print("Browser mein ye URL open karein. Band karne ke liye Ctrl+C")
    print("="*50 + "\n")
    app.run(debug=True, host='0.0.0.0', port=5000)