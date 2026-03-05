# backup_utils.py – Fleet Manager full backup (database + uploads)
"""
Professional-style backup: one ZIP containing database dump and uploads folder.
Supports SQLite and PostgreSQL. Used for Download, Email, and Save-to-path.
"""
import os
import zipfile
import tempfile
from datetime import datetime
from urllib.parse import unquote


def get_sqlite_db_path(app):
    """Resolve SQLite database file path from app config."""
    uri = app.config.get('SQLALCHEMY_DATABASE_URI') or ''
    if not uri.startswith('sqlite'):
        return None
    path = uri.replace('sqlite:///', '').strip()
    path = unquote(path)
    if os.path.isabs(path):
        return path
    for base in [app.instance_path, app.root_path, os.getcwd()]:
        if base and os.path.exists(base):
            p = os.path.join(base, path)
            if os.path.exists(p):
                return os.path.abspath(p)
    return os.path.abspath(path)


def create_backup_zip(app):
    """
    Create a full backup ZIP: database + uploads folder.
    Returns (path_to_zip_file, error_message). Caller must delete zip_path when done.
    """
    zip_path = tempfile.mktemp(suffix='.zip', prefix='fleet_backup_')
    try:
        db_uri = (app.config.get('SQLALCHEMY_DATABASE_URI') or '').strip()
        upload_folder = app.config.get('UPLOAD_FOLDER') or ''
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_basename = f'fleet_backup_{timestamp}.zip'
        # Use a proper name inside the zip for display; file on disk stays unique
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            if 'sqlite' in db_uri:
                db_path = get_sqlite_db_path(app)
                if db_path and os.path.exists(db_path):
                    zf.write(db_path, zip_basename.replace('.zip', '_db.sqlite'))
                else:
                    raise FileNotFoundError('SQLite database file not found.')
            else:
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(db_uri)
                    host = parsed.hostname or 'localhost'
                    port = parsed.port or 5432
                    user = parsed.username or 'postgres'
                    password = parsed.password or ''
                    dbname = (parsed.path or '').strip('/') or 'postgres'
                except Exception as e:
                    raise ValueError(f'Invalid DATABASE_URL: {e}')
                sql_file = tempfile.mktemp(suffix='.sql')
                env = os.environ.copy()
                if password:
                    env['PGPASSWORD'] = password
                import subprocess
                cmd = [
                    'pg_dump', '-h', host, '-p', str(port), '-U', user,
                    '-d', dbname, '-F', 'p', '-f', sql_file, '--no-owner', '--no-acl'
                ]
                r = subprocess.run(cmd, env=env, capture_output=True, text=True)
                if r.returncode != 0:
                    raise RuntimeError(f'pg_dump failed: {r.stderr or r.stdout}')
                zf.write(sql_file, zip_basename.replace('.zip', '_database.sql'))
                try:
                    os.remove(sql_file)
                except Exception:
                    pass
            if upload_folder and os.path.isdir(upload_folder):
                for root, dirs, files in os.walk(upload_folder):
                    for f in files:
                        full = os.path.join(root, f)
                        arc = os.path.join('uploads', os.path.relpath(full, upload_folder))
                        zf.write(full, arc)
        return zip_path, None
    except Exception as e:
        if zip_path and os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except Exception:
                pass
        return None, str(e)


def send_backup_email(app, zip_path, to_email):
    """
    Send backup ZIP as email attachment via SMTP.
    Returns (success: bool, message: str).
    Config: MAIL_SERVER, MAIL_PORT, MAIL_USE_TLS, MAIL_USERNAME, MAIL_PASSWORD, MAIL_FROM (optional).
    """
    if not to_email or not to_email.strip():
        return False, 'Email address is required.'
    to_email = to_email.strip()
    server = app.config.get('MAIL_SERVER') or os.environ.get('MAIL_SERVER')
    port = app.config.get('MAIL_PORT') or os.environ.get('MAIL_PORT', 587)
    use_tls = app.config.get('MAIL_USE_TLS', True)
    username = app.config.get('MAIL_USERNAME') or os.environ.get('MAIL_USERNAME')
    password = app.config.get('MAIL_PASSWORD') or os.environ.get('MAIL_PASSWORD')
    mail_from = app.config.get('MAIL_FROM') or os.environ.get('MAIL_FROM') or username or 'noreply@fleetmanager.local'
    if not server or not username or not password:
        return False, 'Email not configured. Set MAIL_SERVER, MAIL_USERNAME, MAIL_PASSWORD (and optionally MAIL_PORT, MAIL_USE_TLS, MAIL_FROM) in environment or app config.'
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email.mime.text import MIMEText
        from email import encoders
        msg = MIMEMultipart()
        msg['Subject'] = f'Fleet Manager Backup {datetime.now().strftime("%Y-%m-%d %H:%M")}'
        msg['From'] = mail_from
        msg['To'] = to_email
        msg.attach(MIMEText('Fleet Manager database and uploads backup. Please store securely.', 'plain'))
        with open(zip_path, 'rb') as f:
            part = MIMEBase('application', 'zip')
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment', filename=os.path.basename(zip_path))
        msg.attach(part)
        with smtplib.SMTP(server, int(port)) as smtp:
            if use_tls:
                smtp.starttls()
            smtp.login(username, password)
            smtp.sendmail(mail_from, [to_email], msg.as_string())
        return True, 'Backup sent to ' + to_email
    except Exception as e:
        return False, str(e)


def run_scheduled_backup(app):
    """
    Called by scheduler: create backup and send to BACKUP_EMAIL_TO only (no save to path).
    Uses app context; log errors via app.logger if available.
    """
    with app.app_context():
        zip_path, err = create_backup_zip(app)
        if err:
            if hasattr(app, 'logger'):
                app.logger.warning('Scheduled backup failed: %s', err)
            return
        try:
            to_email = (app.config.get('BACKUP_EMAIL_TO') or os.environ.get('BACKUP_EMAIL_TO') or '').strip()
            if to_email:
                ok, msg = send_backup_email(app, zip_path, to_email)
                if hasattr(app, 'logger'):
                    app.logger.info('Scheduled backup email: %s', msg if ok else 'Failed: ' + msg)
        finally:
            try:
                if zip_path and os.path.exists(zip_path):
                    os.remove(zip_path)
            except Exception:
                pass
