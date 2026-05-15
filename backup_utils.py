# backup_utils.py – Fleet Manager full backup (database + uploads)
"""
Professional-style backup: one ZIP containing database dump and uploads folder.
Supports SQLite and PostgreSQL. Used for Download, Email, and Save-to-path.
On Windows, PostgreSQL backup uses Python (psycopg2) when pg_dump is not found.
"""
import os
import shutil
import zipfile
import tempfile
from datetime import date, datetime, time
from decimal import Decimal
from utils import pk_now
from urllib.parse import unquote


def _backup_include_uploads(app):
    raw = os.environ.get('BACKUP_INCLUDE_UPLOADS')
    if raw is None:
        raw = app.config.get('BACKUP_INCLUDE_UPLOADS')
    if raw is None:
        raw = 'false' if os.environ.get('RENDER') else 'true'
    return str(raw).strip().lower() in ('1', 'true', 'yes')


def _backup_exclude_tables():
    raw = (os.environ.get('BACKUP_EXCLUDE_TABLES') or '').strip()
    if not raw and os.environ.get('RENDER'):
        raw = 'activity_log,client_activity_log,login_log,login_attempt'
    if not raw:
        return set()
    return {t.strip() for t in raw.split(',') if t.strip()}


def _backup_compact(app):
    """On Render: single compressed dump file (no ZIP) to avoid 2× disk for large DBs."""
    raw = os.environ.get('BACKUP_COMPACT')
    if raw is None:
        raw = app.config.get('BACKUP_COMPACT')
    if raw is None:
        raw = 'true' if os.environ.get('RENDER') else 'false'
    return str(raw).strip().lower() in ('1', 'true', 'yes')


def _backup_temp_path(suffix):
    ts = pk_now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(tempfile.gettempdir(), f'fleet_backup_{ts}{suffix}')


def _gzip_file(src_path, dest_path=None):
    import gzip
    gz_path = dest_path or (src_path + '.gz')
    with open(src_path, 'rb') as f_in:
        with gzip.open(gz_path, 'wb', compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out, length=1024 * 1024)
    return gz_path


def _check_disk_for_path(path, need_mb):
    """Raise if free space on volume is below need_mb (rough estimate)."""
    try:
        usage = shutil.disk_usage(os.path.dirname(os.path.abspath(path)) or os.getcwd())
        free_mb = usage.free / (1024 * 1024)
        if free_mb < need_mb:
            raise OSError(
                f'Not enough server disk space ({free_mb:.0f} MB free, need about {need_mb:.0f} MB). '
                'Set BACKUP_INCLUDE_UPLOADS=false and/or BACKUP_EXCLUDE_TABLES=activity_log,client_activity_log,login_log,login_attempt in Render env.'
            )
    except OSError:
        raise
    except Exception:
        pass


def _postgres_dump_to_file(db_uri, progress_cb=None):
    """
    PostgreSQL backup as .dump (pg_dump -Fc) or .sql.gz (Python fallback).
    Much smaller than plain .sql — avoids running out of disk on Render.
    """
    import subprocess

    def _rep(pct, msg):
        if progress_cb:
            progress_cb(int(pct), str(msg))

    out_path = _backup_temp_path('.dump')
    _rep(12, 'Exporting database (pg_dump compressed)…')
    try:
        r = subprocess.run(
            ['pg_dump', db_uri, '-Fc', '--no-owner', '--no-acl', '-f', out_path],
            capture_output=True,
            text=True,
            timeout=1200,
        )
        if r.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            _rep(80, 'Database export ready')
            return out_path
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            'pg_dump timed out (database very large). '
            'Set BACKUP_EXCLUDE_TABLES=activity_log,client_activity_log,login_log,login_attempt on Render.'
        )

    try:
        os.remove(out_path)
    except OSError:
        pass

    fd_sql, sql_file = tempfile.mkstemp(suffix='.sql', prefix='fleet_backup_pg_')
    os.close(fd_sql)
    try:
        _rep(10, 'Exporting database (Python)…')
        _pg_dump_via_python(db_uri, sql_file, progress_cb=progress_cb)
        if not os.path.isfile(sql_file) or os.path.getsize(sql_file) <= 0:
            raise ValueError('Database export produced an empty file.')
        _rep(70, 'Compressing database export…')
        size_mb = os.path.getsize(sql_file) / (1024 * 1024)
        _check_disk_for_path(sql_file, size_mb * 1.5 + 50)
        gz_path = _backup_temp_path('.sql.gz')
        _gzip_file(sql_file, gz_path)
        _rep(80, 'Database export ready')
        return gz_path
    finally:
        try:
            os.remove(sql_file)
        except OSError:
            pass


def _postgres_into_zip(zf, db_uri, arcname, progress_cb=None):
    """Add compressed PostgreSQL dump (.dump or .sql.gz) into ZIP."""
    out_path = _postgres_dump_to_file(db_uri, progress_cb=progress_cb)
    try:
        if out_path.endswith('.dump'):
            arc = arcname.replace('_database.sql', '_database.dump')
            if not arc.endswith('.dump'):
                arc = arc.rsplit('.', 1)[0] + '.dump'
        else:
            arc = arcname if arcname.endswith('.gz') else (arcname + '.gz')
        size_mb = round(os.path.getsize(out_path) / (1024 * 1024), 1)
        _check_disk_for_path(out_path, size_mb * 1.3 + 40)
        if progress_cb:
            progress_cb(78, f'Adding database to ZIP ({size_mb} MB)…')
        try:
            zf.write(out_path, arc, compress_type=zipfile.ZIP_STORED)
        except OSError as ex:
            raise OSError(
                f'Cannot add database to ZIP ({size_mb} MB): {ex}. '
                'On Render use compact backup (BACKUP_COMPACT=true, default).'
            ) from ex
        if progress_cb:
            progress_cb(82, 'Database added to ZIP')
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass


def _create_backup_compact(app, progress_cb=None):
    """Single-file backup (no ZIP) — one copy on disk for large PostgreSQL DBs."""
    def _report(pct, step):
        if progress_cb:
            progress_cb(int(pct), str(step))

    _report(5, 'Preparing compact backup…')
    db_uri = (app.config.get('SQLALCHEMY_DATABASE_URI') or '').strip()
    if 'sqlite' in db_uri:
        db_path = get_sqlite_db_path(app)
        if not db_path or not os.path.exists(db_path):
            raise FileNotFoundError('SQLite database file not found.')
        out_path = _backup_temp_path('.sqlite')
        shutil.copy2(db_path, out_path)
        _report(95, 'Backup ready')
        return out_path, None

    out_path = _postgres_dump_to_file(db_uri, progress_cb=_report)
    _report(95, 'Finalizing backup…')
    return out_path, None


def _sql_literal(value):
    """Escape a Python value for a simple SQL INSERT literal."""
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return "'" + value.isoformat().replace("'", "''") + "'"
    if isinstance(value, date):
        return "'" + value.isoformat().replace("'", "''") + "'"
    if isinstance(value, time):
        return "'" + value.isoformat().replace("'", "''") + "'"
    if isinstance(value, (bytes, memoryview)):
        raw = bytes(value)
        return "'\\\\x" + raw.hex() + "'"
    s = str(value).replace("\\", "\\\\").replace("'", "''")
    return "'" + s + "'"


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


def _pg_connect(db_uri):
    """Connect with psycopg2; prefer SQLAlchemy URL parsing (sslmode, etc.)."""
    import psycopg2
    try:
        from sqlalchemy.engine.url import make_url
        url = make_url(db_uri)
        kwargs = {
            'host': url.host or 'localhost',
            'port': url.port or 5432,
            'user': url.username or 'postgres',
            'password': url.password or '',
            'dbname': url.database or 'postgres',
        }
        q = dict(url.query) if url.query else {}
        if q.get('sslmode'):
            kwargs['sslmode'] = q['sslmode']
        return psycopg2.connect(**kwargs)
    except Exception:
        from urllib.parse import urlparse
        parsed = urlparse(db_uri)
        return psycopg2.connect(
            host=parsed.hostname or 'localhost',
            port=parsed.port or 5432,
            user=parsed.username or 'postgres',
            password=parsed.password or '',
            dbname=(parsed.path or '').strip('/') or 'postgres',
        )


def _pg_dump_via_python(db_uri, sql_file, progress_cb=None):
    """
    Dump PostgreSQL to sql_file using psycopg2 COPY (fast) with INSERT fallback per row batch.
    """
    import io
    conn = _pg_connect(db_uri)
    batch_size = 1000
    try:
        with open(sql_file, 'w', encoding='utf-8') as f:
            with conn.cursor() as meta:
                meta.execute("""
                    SELECT tablename FROM pg_tables
                    WHERE schemaname = 'public'
                    ORDER BY tablename
                """)
                tables = [r[0] for r in meta.fetchall()]
            skip = _backup_exclude_tables()
            if skip:
                tables = [t for t in tables if t not in skip]
            total = max(len(tables), 1)
            for idx, table in enumerate(tables):
                if progress_cb:
                    pct = 10 + int(65 * (idx / total))
                    progress_cb(pct, f'Database: {table} ({idx + 1}/{total})')
                f.write(f'\n-- Table "{table}"\n')
                copied = False
                try:
                    buf = io.StringIO()
                    with conn.cursor() as cur:
                        cur.copy_expert(
                            f'COPY (SELECT * FROM "{table}") TO STDOUT WITH (FORMAT csv, HEADER true)',
                            buf,
                        )
                    payload = buf.getvalue()
                    if payload.strip():
                        f.write('-- format: csv\n')
                        f.write(payload)
                        if not payload.endswith('\n'):
                            f.write('\n')
                    else:
                        f.write('-- (empty)\n')
                    copied = True
                except Exception:
                    copied = False
                if copied:
                    continue
                with conn.cursor() as cur:
                    offset = 0
                    row_count = 0
                    while True:
                        cur.execute(
                            f'SELECT * FROM "{table}" LIMIT %s OFFSET %s',
                            (batch_size, offset),
                        )
                        rows = cur.fetchall()
                        if not rows:
                            break
                        cols = [d[0] for d in cur.description] if cur.description else []
                        if not cols:
                            break
                        col_list = ','.join(f'"{c}"' for c in cols)
                        for row in rows:
                            vals = [_sql_literal(v) for v in row]
                            f.write(
                                f'INSERT INTO "{table}" ({col_list}) VALUES ({",".join(vals)});\n'
                            )
                            row_count += 1
                        offset += len(rows)
                    if row_count == 0:
                        f.write('-- (empty)\n')
    finally:
        conn.close()


def create_backup_zip(app, progress_cb=None):
    """
    Create backup archive. On Render (BACKUP_COMPACT=true): single .dump or .sql.gz file.
    Otherwise: ZIP with database + optional uploads.
    Returns (path_to_file, error_message). Caller must delete file when done.
    """
    if _backup_compact(app):
        return _create_backup_compact(app, progress_cb)

    def _report(pct, step):
        if progress_cb:
            progress_cb(int(pct), str(step))

    fd, zip_path = tempfile.mkstemp(suffix='.zip', prefix='fleet_backup_')
    os.close(fd)
    try:
        _report(5, 'Preparing backup…')
        db_uri = (app.config.get('SQLALCHEMY_DATABASE_URI') or '').strip()
        upload_folder = app.config.get('UPLOAD_FOLDER') or ''
        timestamp = pk_now().strftime('%Y%m%d_%H%M%S')
        zip_basename = f'fleet_backup_{timestamp}.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            if 'sqlite' in db_uri:
                _report(15, 'Copying SQLite database…')
                db_path = get_sqlite_db_path(app)
                if db_path and os.path.exists(db_path):
                    zf.write(db_path, zip_basename.replace('.zip', '_db.sqlite'))
                else:
                    raise FileNotFoundError('SQLite database file not found.')
            else:
                arc_sql = zip_basename.replace('.zip', '_database.sql')
                _postgres_into_zip(zf, db_uri, arc_sql, progress_cb=_report)
            if _backup_include_uploads(app) and upload_folder and os.path.isdir(upload_folder):
                _report(82, 'Adding local uploads folder…')
                file_count = 0
                for root, dirs, files in os.walk(upload_folder):
                    for f in files:
                        full = os.path.join(root, f)
                        try:
                            if not os.path.isfile(full):
                                continue
                            arc = os.path.join('uploads', os.path.relpath(full, upload_folder))
                            zf.write(full, arc)
                            file_count += 1
                            if file_count % 50 == 0:
                                _report(82 + min(12, file_count // 50), f'Uploads: {file_count} files…')
                        except OSError:
                            continue
            else:
                _report(85, 'Skipping local uploads (R2 / BACKUP_INCLUDE_UPLOADS=false)…')
        _report(98, 'Finalizing ZIP…')
        return zip_path, None
    except Exception as e:
        if zip_path and os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except OSError:
                pass
        return None, str(e)


def _email_attachment_limit_mb():
    return int(os.environ.get('BACKUP_EMAIL_MAX_MB', '24'))


def _format_email_error(exc):
    msg = str(exc).strip() or type(exc).__name__
    low = msg.lower()
    if os.environ.get('RENDER') and any(
        x in low for x in ('timed out', 'timeout', 'connection refused', 'network is unreachable', 'errno 111', 'errno 110')
    ):
        return (
            'SMTP blocked or unreachable from Render (free plan blocks ports 587/465). '
            'Fix: add a Mailtrap API token in backup settings (recommended on Render), '
            'upgrade Render to paid for Gmail SMTP, or use Download Backup. Detail: ' + msg
        )
    if 'authentication' in low or '535' in msg or '534' in msg:
        return 'Gmail login failed. Use a 16-character App Password (Google → Security → App passwords), not your normal password.'
    if any(x in low for x in ('552', 'too large', 'maximum', 'size exceeded', 'message size')):
        return f'Attachment too large for email (max about {_email_attachment_limit_mb()} MB). Use Download Backup.'
    return msg


def _send_backup_via_mailtrap(api_token, from_email, to_email, subject, body, attach_path):
    import base64
    import json
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    attach_name = os.path.basename(attach_path)
    ext = os.path.splitext(attach_name)[1].lower()
    mime = 'application/zip' if ext == '.zip' else 'application/gzip' if ext == '.gz' else 'application/octet-stream'
    with open(attach_path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('ascii')
    payload = {
        'from': {'email': from_email, 'name': 'Fleet Manager Backup'},
        'to': [{'email': to_email}],
        'subject': subject,
        'text': body,
        'attachments': [{
            'content': b64,
            'filename': attach_name,
            'type': mime,
            'disposition': 'attachment',
        }],
    }
    body_json = json.dumps(payload).encode('utf-8')

    def _post(headers):
        return Request(
            'https://send.api.mailtrap.io/api/send',
            data=body_json,
            headers=dict(headers),
            method='POST',
        )

    auth_attempts = [
        {'Authorization': 'Bearer ' + api_token},
        {'Api-Token': api_token},
    ]
    last_detail = ''
    for auth_hdr in auth_attempts:
        req = _post({
            **auth_hdr,
            'Content-Type': 'application/json',
            'User-Agent': 'FleetManager-Backup/1.0',
        })
        try:
            with urlopen(req, timeout=180) as resp:
                raw = resp.read().decode('utf-8', errors='replace')
                if 200 <= getattr(resp, 'status', 200) < 300:
                    try:
                        data = json.loads(raw) if raw and raw.strip() else {}
                    except json.JSONDecodeError:
                        return False, 'Mailtrap: invalid JSON response — ' + raw[:200]

                    if isinstance(data, dict):
                        if data.get('success') is False:
                            errs = data.get('errors') or ['Unknown Mailtrap error']
                            msg = '; '.join(str(e) for e in errs[:5])
                            hint = ''
                            low = msg.lower()
                            if 'from' in low or 'domain' in low or 'sender' in low or 'verify' in low:
                                hint = (
                                    ' In Mailtrap → Sending → Domains, verify the same domain as your Sender email. '
                                    'Pure Gmail (@gmail.com) usually cannot be used as Mailtrap Sending sender.'
                                )
                            return False, 'Mailtrap: ' + msg + hint
                        errs = data.get('errors') or []
                        if errs:
                            msg = '; '.join(str(e) for e in errs[:5])
                            return False, 'Mailtrap: ' + msg
                        mids = data.get('message_ids') or []
                        if data.get('success') is True or mids:
                            return True, 'Backup sent to ' + to_email + ' (Mailtrap)'
                        return False, 'Mailtrap: unexpected response — ' + (raw[:400] if raw else 'empty body')
        except HTTPError as e:
            detail = e.read().decode('utf-8', errors='replace')[:600]
            last_detail = detail or str(e.reason)
            try:
                err_json = json.loads(detail)
                errs = err_json.get('errors')
                if errs:
                    msg = '; '.join(str(x) for x in errs[:5])
                    hint = ''
                    low = msg.lower()
                    if 'from' in low or 'domain' in low or 'sender' in low:
                        hint = ' Verify sender @ Mailtrap Domains.'
                    return False, 'Mailtrap: ' + msg + hint
            except json.JSONDecodeError:
                pass
            continue
        except URLError as e:
            return False, 'Mailtrap request failed: ' + str(e.reason or e)

    if last_detail:
        return False, f'Mailtrap error: {last_detail}'
    return False, 'Mailtrap send failed'


def _send_backup_via_sendgrid(api_key, from_email, to_email, subject, body, attach_path):
    import base64
    import json
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    attach_name = os.path.basename(attach_path)
    ext = os.path.splitext(attach_name)[1].lower()
    mime = 'application/zip' if ext == '.zip' else 'application/gzip' if ext == '.gz' else 'application/octet-stream'
    with open(attach_path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('ascii')
    payload = {
        'personalizations': [{'to': [{'email': to_email}]}],
        'from': {'email': from_email},
        'subject': subject,
        'content': [{'type': 'text/plain', 'value': body}],
        'attachments': [{
            'content': b64,
            'type': mime,
            'filename': attach_name,
            'disposition': 'attachment',
        }],
    }
    req = Request(
        'https://api.sendgrid.com/v3/mail/send',
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': 'Bearer ' + api_key,
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with urlopen(req, timeout=180) as resp:
            if 200 <= getattr(resp, 'status', 200) < 300:
                return True, 'Backup sent to ' + to_email + ' (SendGrid)'
    except HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')[:400]
        return False, f'SendGrid error ({e.code}): {detail or e.reason}'
    except URLError as e:
        return False, 'SendGrid request failed: ' + str(e.reason or e)
    return False, 'SendGrid send failed'


def _send_backup_via_smtp(server, port, use_tls, username, password, mail_from, to_email, msg_bytes):
    import smtplib

    attempts = []
    if port == 465:
        attempts.append((465, True))
    elif port == 587:
        attempts.append((587, False))
    else:
        attempts.append((port, False))
    for extra_port, use_ssl in ((465, True), (587, False)):
        if (extra_port, use_ssl) not in attempts:
            attempts.append((extra_port, use_ssl))

    last_err = None
    envelope_from = username or mail_from
    for try_port, use_ssl in attempts:
        try:
            if use_ssl:
                smtp = smtplib.SMTP_SSL(server, try_port, timeout=90)
            else:
                smtp = smtplib.SMTP(server, try_port, timeout=90)
            with smtp:
                smtp.ehlo()
                if not use_ssl and use_tls:
                    smtp.starttls()
                    smtp.ehlo()
                smtp.login(username, password)
                smtp.sendmail(envelope_from, [to_email], msg_bytes)
            return True, None
        except Exception as e:
            last_err = e
    return False, last_err


def send_backup_email(app, zip_path, to_email):
    """
    Send backup file as email attachment.
    Uses Mailtrap API, then SendGrid, then SMTP (Gmail).
    On Render free tier use Mailtrap or SendGrid (SMTP ports blocked).
    """
    from backup_config import apply_backup_config_to_app

    apply_backup_config_to_app(app)
    if not to_email or not to_email.strip():
        return False, 'Email address is required.'
    to_email = to_email.strip()
    if not zip_path or not os.path.isfile(zip_path):
        return False, 'Backup file missing.'

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    max_mb = _email_attachment_limit_mb()
    if size_mb > max_mb:
        return False, (
            f'Backup file is {size_mb:.1f} MB; email allows about {max_mb} MB. '
            'Use Download Backup or enable SendGrid with a smaller backup.'
        )

    username = (app.config.get('MAIL_USERNAME') or '').strip()
    password = (app.config.get('MAIL_PASSWORD') or '').strip()
    mail_from = (app.config.get('MAIL_FROM') or username or '').strip()
    mailtrap_token = (app.config.get('MAILTRAP_API_TOKEN') or os.environ.get('MAILTRAP_API_TOKEN') or '').strip()
    sendgrid_key = (app.config.get('SENDGRID_API_KEY') or os.environ.get('SENDGRID_API_KEY') or '').strip()
    subject = f'Fleet Manager Backup {pk_now().strftime("%Y-%m-%d %H:%M")}'
    body = 'Fleet Manager database backup. Please store securely.'

    if mailtrap_token:
        if not mail_from:
            return False, 'Sender email is required (must be verified in Mailtrap → Domains).'
        return _send_backup_via_mailtrap(mailtrap_token, mail_from, to_email, subject, body, zip_path)

    if sendgrid_key:
        if not mail_from:
            return False, 'Sender email is required for SendGrid.'
        return _send_backup_via_sendgrid(sendgrid_key, mail_from, to_email, subject, body, zip_path)

    server = (app.config.get('MAIL_SERVER') or 'smtp.gmail.com').strip()
    port_str = str(app.config.get('MAIL_PORT') or '587').strip()
    port = int(port_str) if port_str.isdigit() else 587
    use_tls = str(app.config.get('MAIL_USE_TLS', True)).lower() in ('1', 'true', 'yes')
    if not server or not username or not password:
        hint = ''
        if os.environ.get('RENDER'):
            hint = ' On Render free tier, add a Mailtrap API token in backup settings (SMTP is blocked).'
        return False, 'Email not configured (Gmail App Password required).' + hint

    try:
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email.mime.text import MIMEText
        from email import encoders

        msg = MIMEMultipart()
        msg['Subject'] = subject
        msg['From'] = mail_from
        msg['To'] = to_email
        msg.attach(MIMEText(body, 'plain'))
        attach_name = os.path.basename(zip_path)
        ext = os.path.splitext(attach_name)[1].lower()
        subtype = 'zip' if ext == '.zip' else 'gzip' if ext == '.gz' else 'octet-stream'
        with open(zip_path, 'rb') as f:
            part = MIMEBase('application', subtype)
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment', filename=attach_name)
        msg.attach(part)
        msg_text = msg.as_string()

        ok, err = _send_backup_via_smtp(server, port, use_tls, username, password, mail_from, to_email, msg_text)
        if ok:
            return True, 'Backup sent to ' + to_email
        return False, _format_email_error(err)
    except Exception as e:
        return False, _format_email_error(e)


def run_backup_job_sync(app, job_id):
    """
    Run backup in the current request (Render/gunicorn: background threads often never run).
    Caller must hold the job claim lock from backup_jobs.try_claim_job.
    Returns dict with started, status, error.
    """
    from backup_jobs import write_job, read_job, release_claim, try_claim_job

    if not try_claim_job(app, job_id):
        job = read_job(app, job_id) or {}
        return {
            'started': False,
            'status': job.get('status'),
            'error': job.get('error'),
        }

    zip_path = None
    try:
        write_job(app, job_id, status='running', step='Starting backup…', percent=5, error=None)

        def progress(pct, step):
            write_job(app, job_id, status='running', step=step, percent=pct)

        job = read_job(app, job_id) or {}
        job_type = (job.get('job_type') or 'download').strip().lower()
        email_to = (job.get('email_to') or '').strip()

        zip_path, err = create_backup_zip(app, progress_cb=progress)
        if err:
            err_msg = (err or '').strip() or 'Backup failed (unknown reason)'
            write_job(
                app, job_id,
                status='error', step='Backup failed', error=err_msg,
            )
            return {'started': True, 'status': 'error', 'error': err_msg}

        if not zip_path or not os.path.isfile(zip_path):
            err_msg = 'Backup file was not created.'
            write_job(app, job_id, status='error', step='Backup failed', error=err_msg)
            return {'started': True, 'status': 'error', 'error': err_msg}

        ext = os.path.splitext(zip_path)[1] or '.zip'
        friendly = os.path.basename(zip_path)
        if not friendly.startswith('fleet_backup_'):
            friendly = f'fleet_backup_{pk_now().strftime("%Y%m%d_%H%M%S")}{ext}'
        size_mb = round(os.path.getsize(zip_path) / (1024 * 1024), 1)
        try:
            from models import SystemSetting
            SystemSetting.set('last_backup_ts', pk_now().strftime('%Y-%m-%d %H:%M:%S'))
            SystemSetting.set('last_backup_result', 'success')
            SystemSetting.set('last_backup_size', f'{size_mb} MB')
        except Exception:
            pass

        if job_type == 'email':
            from backup_config import apply_backup_config_to_app
            apply_backup_config_to_app(app)
            dest = email_to or (app.config.get('BACKUP_EMAIL_TO') or '').strip()
            if not dest:
                err_msg = 'Recipient email not configured.'
                try:
                    os.remove(zip_path)
                except OSError:
                    pass
                write_job(app, job_id, status='error', step='Backup failed', error=err_msg)
                return {'started': True, 'status': 'error', 'error': err_msg}
            write_job(app, job_id, status='running', step='Sending email…', percent=92)
            ok, msg = send_backup_email(app, zip_path, dest)
            try:
                os.remove(zip_path)
            except OSError:
                pass
            zip_path = None
            if not ok:
                err_msg = (msg or '').strip() or 'Email failed'
                write_job(
                    app, job_id,
                    status='error',
                    step='Email failed',
                    error=err_msg,
                    percent=92,
                )
                return {'started': True, 'status': 'error', 'error': err_msg}
            write_job(
                app, job_id,
                status='done',
                step='Email sent',
                percent=100,
                zip_path=None,
                download_name=None,
                message=msg,
                job_type='email',
                error=None,
            )
            return {'started': True, 'status': 'done', 'error': None}

        write_job(
            app, job_id,
            status='done',
            step='Backup ready',
            percent=100,
            zip_path=zip_path,
            download_name=friendly,
            message=f'{size_mb} MB',
            error=None,
        )
        zip_path = None
        return {'started': True, 'status': 'done', 'error': None}
    except Exception as e:
        if hasattr(app, 'logger'):
            app.logger.exception('backup job %s failed: %s', job_id, e)
        if zip_path and os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except OSError:
                pass
        err_msg = str(e).strip() or f'{type(e).__name__}: backup failed'
        write_job(
            app, job_id,
            status='error', step='Backup failed', error=err_msg,
        )
        return {'started': True, 'status': 'error', 'error': err_msg}
    finally:
        release_claim(app, job_id)


def run_scheduled_backup(app):
    """
    Called by scheduler: create backup and send to BACKUP_EMAIL_TO only (no save to path).
    Uses app context; log errors via app.logger if available.
    """
    with app.app_context():
        from backup_config import apply_backup_config_to_app
        apply_backup_config_to_app(app)
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
