"""Backup async job state.

- SQLite / BACKUP_JOBS_FORCE_FILE: JSON files under instance/backup_jobs (same host only).
- PostgreSQL: rows in fleet_backup_job (+ lock table) so Render multi-instance polls find the job.

Backup ZIP paths remain local to the worker that created them; download-by-email avoids that.
"""
import json
import os
import tempfile
import time
import uuid


def _db_uri(app):
    return (app.config.get('SQLALCHEMY_DATABASE_URI') or '').strip().lower()


def _use_pg_jobs(app):
    """Postgres-backed job rows (survives cross-instance HTTP routing on Render)."""
    if (os.environ.get('BACKUP_JOBS_FORCE_FILE') or '').strip().lower() in ('1', 'true', 'yes'):
        return False
    u = _db_uri(app)
    if 'sqlite' in u:
        return False
    return u.startswith('postgresql') or u.startswith('postgres://')


def _jobs_root(app):
    explicit = (os.environ.get('BACKUP_JOBS_DIR') or '').strip()
    if explicit:
        root = explicit
    else:
        try:
            root = os.path.join(app.instance_path, 'backup_jobs')
        except Exception:
            root = os.path.join(tempfile.gettempdir(), 'fleet_backup_jobs')
    os.makedirs(root, exist_ok=True)
    return root


def _lock_file(app, job_id):
    return _job_file(app, job_id) + '.lock'


def has_worker_claim(app, job_id):
    """True if some worker already claimed this queued job (file lock or DB lock row)."""
    if _use_pg_jobs(app):
        from models import FleetBackupJobLock

        try:
            with app.app_context():
                return FleetBackupJobLock.query.get(job_id) is not None
        except Exception:
            return False
    try:
        return os.path.exists(_lock_file(app, job_id))
    except OSError:
        return False


def try_claim_job(app, job_id):
    """Exclusive lock so only one worker runs the backup."""
    job = read_job(app, job_id)
    if not job or job.get('status') != 'queued':
        return False
    if _use_pg_jobs(app):
        return _try_claim_job_pg(app, job_id)
    lock_path = _lock_file(app, job_id)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except OSError:
        return False


def _try_claim_job_pg(app, job_id):
    from sqlalchemy.exc import IntegrityError
    from models import FleetBackupJobLock, db

    try:
        with app.app_context():
            db.session.add(FleetBackupJobLock(job_id=job_id))
            db.session.commit()
            return True
    except IntegrityError:
        try:
            with app.app_context():
                db.session.rollback()
        except Exception:
            pass
        return False
    except Exception:
        try:
            with app.app_context():
                db.session.rollback()
        except Exception:
            pass
        return False


def release_claim(app, job_id):
    if _use_pg_jobs(app):
        _release_claim_pg(app, job_id)
        return
    try:
        os.remove(_lock_file(app, job_id))
    except OSError:
        pass


def _release_claim_pg(app, job_id):
    from models import FleetBackupJobLock, db

    try:
        with app.app_context():
            row = FleetBackupJobLock.query.get(job_id)
            if row:
                db.session.delete(row)
                db.session.commit()
    except Exception:
        try:
            with app.app_context():
                db.session.rollback()
        except Exception:
            pass


def _job_file(app, job_id):
    safe = ''.join(c for c in (job_id or '') if c.isalnum())
    if not safe:
        raise ValueError('invalid job id')
    return os.path.join(_jobs_root(app), f'{safe}.json')


def cleanup_old_jobs(app, max_age_seconds=3600):
    if _use_pg_jobs(app):
        _cleanup_old_jobs_pg(app, max_age_seconds)
        return
    root = _jobs_root(app)
    now = time.time()
    for name in os.listdir(root):
        if not name.endswith('.json'):
            continue
        path = os.path.join(root, name)
        try:
            if now - os.path.getmtime(path) > max_age_seconds:
                data = read_job_file(path)
                zip_path = (data or {}).get('zip_path')
                if zip_path and os.path.isfile(zip_path):
                    os.remove(zip_path)
                os.remove(path)
        except OSError:
            pass


def _cleanup_old_jobs_pg(app, max_age_seconds):
    from datetime import timedelta

    from models import FleetBackupJob, db
    from utils import pk_now

    try:
        with app.app_context():
            cutoff = pk_now() - timedelta(seconds=max_age_seconds)
            rows = FleetBackupJob.query.filter(FleetBackupJob.updated_at < cutoff).all()
            for row in rows:
                zp = (row.body or {}).get('zip_path')
                if zp and os.path.isfile(zp):
                    try:
                        os.remove(zp)
                    except OSError:
                        pass
                db.session.delete(row)
            db.session.commit()
    except Exception:
        try:
            with app.app_context():
                db.session.rollback()
        except Exception:
            pass


def create_job(app, user_id, job_type='download', email_to=None):
    cleanup_old_jobs(app)
    job_id = uuid.uuid4().hex
    write_job(
        app,
        job_id,
        {
            'status': 'queued',
            'step': 'Queued…',
            'percent': 0,
            'message': '',
            'error': None,
            'zip_path': None,
            'download_name': None,
            'job_type': job_type or 'download',
            'email_to': (email_to or '').strip() or None,
            'user_id': int(user_id) if user_id else None,
            'created': time.time(),
        },
    )
    return job_id


def write_job(app, job_id, data=None, **kwargs):
    if _use_pg_jobs(app):
        _write_job_pg(app, job_id, data, **kwargs)
        return
    path = _job_file(app, job_id)
    existing = read_job_file(path) or {}
    patch = dict(data or {})
    patch.update(kwargs)
    existing.update(patch)
    existing['updated'] = time.time()
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(existing, f)
    os.replace(tmp, path)


def _write_job_pg(app, job_id, data=None, **kwargs):
    from models import FleetBackupJob, db
    from utils import pk_now

    patch = dict(data or {})
    patch.update(kwargs)
    patch['updated'] = time.time()
    with app.app_context():
        row = FleetBackupJob.query.get(job_id)
        if row is None:
            db.session.add(FleetBackupJob(id=job_id, body=patch, updated_at=pk_now()))
        else:
            merged = dict(row.body or {})
            merged.update(patch)
            row.body = merged
            row.updated_at = pk_now()
        db.session.commit()


def read_job(app, job_id):
    if _use_pg_jobs(app):
        return _read_job_pg(app, job_id)
    try:
        return read_job_file(_job_file(app, job_id))
    except (ValueError, OSError):
        return None


def _read_job_pg(app, job_id):
    from models import FleetBackupJob

    try:
        with app.app_context():
            row = FleetBackupJob.query.get(job_id)
            if not row or row.body is None:
                return None
            return dict(row.body)
    except Exception:
        return None


def read_job_file(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def delete_job(app, job_id):
    if _use_pg_jobs(app):
        _delete_job_pg(app, job_id)
        return
    try:
        data = read_job(app, job_id)
        if data:
            zp = data.get('zip_path')
            if zp and os.path.isfile(zp):
                os.remove(zp)
        os.remove(_job_file(app, job_id))
    except OSError:
        pass


def _delete_job_pg(app, job_id):
    from models import FleetBackupJob, db

    try:
        with app.app_context():
            row = FleetBackupJob.query.get(job_id)
            if row:
                zp = (row.body or {}).get('zip_path')
                if zp and os.path.isfile(zp):
                    try:
                        os.remove(zp)
                    except OSError:
                        pass
                db.session.delete(row)
                db.session.commit()
    except Exception:
        try:
            with app.app_context():
                db.session.rollback()
        except Exception:
            pass
