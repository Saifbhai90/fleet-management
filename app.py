from flask import Flask
from models import db
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
import os

# Load .env from app folder (so it works even when run from another directory)
_app_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_app_dir, '.env'))

print("Starting app...")
app = Flask(__name__)

# Secret key / DB config (env first, fallback to current defaults)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-me-please-make-it-strong')

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

# Enable global CSRF protection so csrf_token() is available in templates
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
    """
    Make unread notification count available in all templates as
    `unread_notification_count` for the navbar bell icon.
    """
    try:
        from models import Notification
        unread_count = Notification.query.filter(Notification.read_at.is_(None)).count()
    except Exception:
        unread_count = 0
    return dict(unread_notification_count=unread_count)


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
    print("Database ready.")

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