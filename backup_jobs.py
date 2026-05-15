"""File-backed backup job state (shared across gunicorn workers on same instance)."""
import json
import os
import time
import uuid


def _jobs_root(app):
    root = os.path.join(app.instance_path, 'backup_jobs')
    os.makedirs(root, exist_ok=True)
    return root


def _job_file(app, job_id):
    safe = ''.join(c for c in (job_id or '') if c.isalnum())
    if not safe:
        raise ValueError('invalid job id')
    return os.path.join(_jobs_root(app), f'{safe}.json')


def cleanup_old_jobs(app, max_age_seconds=3600):
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


def create_job(app, user_id):
    cleanup_old_jobs(app)
    job_id = uuid.uuid4().hex
    write_job(app, job_id, {
        'status': 'queued',
        'step': 'Queued…',
        'percent': 0,
        'message': '',
        'error': None,
        'zip_path': None,
        'download_name': None,
        'user_id': int(user_id) if user_id else None,
        'created': time.time(),
    })
    return job_id


def write_job(app, job_id, data):
    path = _job_file(app, job_id)
    existing = read_job_file(path) or {}
    existing.update(data)
    existing['updated'] = time.time()
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(existing, f)
    os.replace(tmp, path)


def read_job(app, job_id):
    try:
        return read_job_file(_job_file(app, job_id))
    except (ValueError, OSError):
        return None


def read_job_file(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def delete_job(app, job_id):
    try:
        data = read_job(app, job_id)
        if data:
            zp = data.get('zip_path')
            if zp and os.path.isfile(zp):
                os.remove(zp)
        os.remove(_job_file(app, job_id))
    except OSError:
        pass
