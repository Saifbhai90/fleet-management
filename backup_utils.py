# backup_utils.py – Fleet Manager full backup (database + uploads)
"""
Professional-style backup: one ZIP containing database dump and uploads folder.
Supports SQLite and PostgreSQL. Used for Download, Email, and Save-to-path.
On Windows, PostgreSQL backup uses Python (psycopg2) when pg_dump is not found.
"""
import os
import zipfile
import tempfile
from datetime import datetime
from utils import pk_now
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


def _pg_dump_via_python(db_uri, sql_file):
    """
    Dump PostgreSQL schema + data to sql_file using psycopg2 (no pg_dump needed).
    Raises on error.
    """
    import psycopg2
    from urllib.parse import urlparse
    parsed = urlparse(db_uri)
    host = parsed.hostname or 'localhost'
    port = parsed.port or 5432
    user = parsed.username or 'postgres'
    password = parsed.password or ''
    dbname = (parsed.path or '').strip('/') or 'postgres'
    conn = psycopg2.connect(
        host=host, port=port, user=user, password=password, dbname=dbname
    )
    try:
        with open(sql_file, 'w', encoding='utf-8') as f:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT tablename FROM pg_tables
                    WHERE schemaname = 'public'
                    ORDER BY tablename
                """)
                tables = [r[0] for r in cur.fetchall()]
                for table in tables:
                    cur.execute(f'SELECT * FROM "{table}"')
                    rows = cur.fetchall()
                    cols = [d[0] for d in cur.description]
                    if not rows:
                        f.write(f'-- Table "{table}" (empty)\n')
                        continue
                    col_list = ','.join(f'"{c}"' for c in cols)
                    f.write(f'-- Table "{table}"\n')
                    for row in rows:
                        vals = []
                        for v in row:
                            if v is None:
                                vals.append('NULL')
                            elif isinstance(v, bool):
                                vals.append('TRUE' if v else 'FALSE')
                            elif isinstance(v, (int, float)):
                                vals.append(str(v))
                            elif isinstance(v, datetime):
                                vals.append("'" + v.isoformat().replace("'", "''") + "'")
                            else:
                                s = str(v).replace("\\", "\\\\").replace("'", "''")
                                vals.append("'" + s + "'")
                        f.write(f'INSERT INTO "{table}" ({col_list}) VALUES ({",".join(vals)});\n')
                    f.write('\n')
    finally:
        conn.close()


def create_backup_zip(app):
    """
    Create a full backup ZIP: database + uploads folder.
    Returns (path_to_zip_file, error_message). Caller must delete zip_path when done.
    """
    zip_path = tempfile.mktemp(suffix='.zip', prefix='fleet_backup_')
    try:
        db_uri = (app.config.get('SQLALCHEMY_DATABASE_URI') or '').strip()
        upload_folder = app.config.get('UPLOAD_FOLDER') or ''
        timestamp = pk_now().strftime('%Y%m%d_%H%M%S')
        zip_basename = f'fleet_backup_{timestamp}.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            if 'sqlite' in db_uri:
                db_path = get_sqlite_db_path(app)
                if db_path and os.path.exists(db_path):
                    zf.write(db_path, zip_basename.replace('.zip', '_db.sqlite'))
                else:
                    raise FileNotFoundError('SQLite database file not found.')
            else:
                sql_file = tempfile.mktemp(suffix='.sql')
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
                env = os.environ.copy()
                if password:
                    env['PGPASSWORD'] = password
                import subprocess
                cmd = [
                    'pg_dump', '-h', host, '-p', str(port), '-U', user,
                    '-d', dbname, '-F', 'p', '-f', sql_file, '--no-owner', '--no-acl'
                ]
                try:
                    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
                except FileNotFoundError:
                    r = None
                if r is None or r.returncode != 0:
                    # pg_dump not found (e.g. Windows) or failed: use Python dump
                    _pg_dump_via_python(db_uri, sql_file)
                else:
                    # pg_dump wrote sql_file; only need to zip it (no rewrite)
                    pass
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
    Tries port 465 (SSL) first, then 587 (STARTTLS).
    """
    if not to_email or not to_email.strip():
        return False, 'Email address is required.'
    to_email = to_email.strip()
    server = (app.config.get('MAIL_SERVER') or os.environ.get('MAIL_SERVER') or '').strip()
    port_str = (app.config.get('MAIL_PORT') or os.environ.get('MAIL_PORT') or '587').strip()
    port = int(port_str) if port_str.isdigit() else 587
    use_tls = str(app.config.get('MAIL_USE_TLS', True)).lower() in ('1', 'true', 'yes')
    username = (app.config.get('MAIL_USERNAME') or os.environ.get('MAIL_USERNAME') or '').strip()
    password = (app.config.get('MAIL_PASSWORD') or os.environ.get('MAIL_PASSWORD') or '').strip()
    mail_from = (app.config.get('MAIL_FROM') or os.environ.get('MAIL_FROM') or username or 'noreply@fleetmanager.local').strip()
    if not server or not username or not password:
        return False, 'Email not configured. Set MAIL_SERVER, MAIL_USERNAME, MAIL_PASSWORD in .env (local) or Environment (online).'
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email.mime.text import MIMEText
        from email import encoders
        msg = MIMEMultipart()
        msg['Subject'] = f'Fleet Manager Backup {pk_now().strftime("%Y-%m-%d %H:%M")}'
        msg['From'] = mail_from
        msg['To'] = to_email
        msg.attach(MIMEText('Fleet Manager database and uploads backup. Please store securely.', 'plain'))
        with open(zip_path, 'rb') as f:
            part = MIMEBase('application', 'zip')
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment', filename=os.path.basename(zip_path))
        msg.attach(part)
        # Try 465 (SSL) first; often works better from local. Else 587 (STARTTLS).
        last_err = None
        for try_port, use_ssl in [(465, True), (587, False)]:
            try:
                if use_ssl:
                    with smtplib.SMTP_SSL(server, try_port) as smtp:
                        smtp.login(username, password)
                        smtp.sendmail(mail_from, [to_email], msg.as_string())
                else:
                    with smtplib.SMTP(server, try_port) as smtp:
                        if use_tls:
                            smtp.starttls()
                        smtp.login(username, password)
                        smtp.sendmail(mail_from, [to_email], msg.as_string())
                return True, 'Backup sent to ' + to_email
            except Exception as e:
                last_err = e
                continue
        return False, str(last_err) if last_err else 'Email failed'
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
            try:
                from models import SystemSetting
                SystemSetting.set('last_backup_result', 'failed')
                SystemSetting.set('last_backup_ts', __import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
            except Exception:
                pass
            return
        try:
            try:
                from models import SystemSetting
                _bk_sz = os.path.getsize(zip_path) if zip_path and os.path.exists(zip_path) else 0
                SystemSetting.set('last_backup_ts', __import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
                SystemSetting.set('last_backup_result', 'success')
                SystemSetting.set('last_backup_size', f'{round(_bk_sz / (1024*1024), 1)} MB')
            except Exception:
                pass
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
