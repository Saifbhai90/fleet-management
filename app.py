from flask import Flask
from models import db
from flask_migrate import Migrate
from dotenv import load_dotenv
import os

load_dotenv()

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

# Initialize SQLAlchemy
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

# Create all tables if not exist (backward compatibility; new changes use migrations)
with app.app_context():
    db.create_all()

# Import routes after app & db are ready
from routes import *  # noqa: E402,F401


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)