"""Move expense photos and videos that landed on the server disk up to Cloudflare R2.

A failed R2 upload is saved locally so the bill is not lost. That local copy is
why a list row shows Mixed. This job keeps retrying those files until they are
on R2, then deletes the disk copy.
"""

import logging
import os
import threading
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from flask import current_app
from werkzeug.datastructures import FileStorage

import r2_storage
from services.expense_media_store import MediaRejected, store_verified_media

from models import (
    db,
    FuelExpenseAttachment,
    MaintenanceExpenseAttachment,
    MaintenanceWorkOrderAttachment,
    OilExpenseAttachment,
    OilWorkOrderAttachment,
)

logger = logging.getLogger(__name__)
_SCHEDULER = None
_LOCK = threading.Lock()

_SPECS = (
    (OilExpenseAttachment, 'oil_expense'),
    (FuelExpenseAttachment, 'fuel_expense'),
    (MaintenanceExpenseAttachment, 'maintenance_expense'),
    (MaintenanceWorkOrderAttachment, 'maintenance_work_order'),
    (OilWorkOrderAttachment, 'oil_work_order'),
)


def _r2_ready():
    return bool(
        r2_storage.R2_PUBLIC_URL
        and r2_storage.R2_ACCESS_KEY_ID
        and r2_storage.R2_SECRET_ACCESS_KEY
        and r2_storage.R2_ENDPOINT_URL
        and r2_storage.R2_BUCKET_NAME
    )


def _local_full_path(upload_root, rel_path):
    rel = (rel_path or '').replace('\\', '/').lstrip('/')
    if not rel or '..' in rel.split('/'):
        return None
    root = os.path.normpath(upload_root)
    full = os.path.normpath(os.path.join(root, rel.replace('/', os.sep)))
    if not full.startswith(root + os.sep) and full != root:
        return None
    return full


def promote_local_expense_media(limit=25):
    """Upload local expense attachments to R2. Returns how many moved."""
    if not _LOCK.acquire(blocking=False):
        return 0
    try:
        if not _r2_ready():
            return 0

        app = current_app._get_current_object()
        upload_root = app.config.get('UPLOAD_FOLDER') or ''
        if not upload_root:
            return 0
        promoted = 0
        for model, folder in _SPECS:
            if promoted >= limit:
                break
            rows = (
                model.query
                .filter(~model.file_path.ilike('http://%'))
                .filter(~model.file_path.ilike('https://%'))
                .order_by(model.id.asc())
                .limit(limit)
                .all()
            )
            for row in rows:
                if promoted >= limit:
                    break
                full = _local_full_path(upload_root, row.file_path)
                if not full or not os.path.isfile(full):
                    continue
                ftype = (row.file_type or '').strip().lower()
                ext = os.path.splitext(full)[1].lower()
                if ftype not in ('image', 'video'):
                    ftype = 'video' if ext in ('.mp4', '.webm', '.mov') else 'image'
                name = row.original_name or os.path.basename(full)
                try:
                    with open(full, 'rb') as fp:
                        stored = FileStorage(stream=fp, filename=name)
                        url = store_verified_media(stored, ftype, name, folder)
                    if not url or not str(url).startswith('http'):
                        continue
                    row.file_path = url
                    db.session.commit()
                    promoted += 1
                    try:
                        os.remove(full)
                    except OSError:
                        pass
                    logger.info('Moved %s id=%s to R2', model.__tablename__, row.id)
                except MediaRejected:
                    db.session.rollback()
                    logger.warning(
                        'Leaving unreadable %s id=%s on disk until a good file is sent',
                        model.__tablename__,
                        row.id,
                    )
                except Exception:
                    db.session.rollback()
                    logger.warning(
                        'Cloud retry failed for %s id=%s',
                        model.__tablename__,
                        row.id,
                        exc_info=True,
                    )
        return promoted
    finally:
        _LOCK.release()


def start_expense_cloud_retry_scheduler(app):
    global _SCHEDULER
    if os.environ.get('EXPENSE_CLOUD_RETRY_ENABLED', '1').strip().lower() in ('0', 'false', 'no'):
        return
    try:
        if _SCHEDULER is not None:
            _SCHEDULER.shutdown(wait=False)
    except Exception:
        pass
    _SCHEDULER = BackgroundScheduler()

    def _job():
        try:
            with app.app_context():
                moved = promote_local_expense_media()
                if moved:
                    app.logger.info('Expense cloud retry moved %s file(s) to R2', moved)
        except Exception as exc:
            app.logger.warning('Expense cloud retry job failed: %s', exc)

    _SCHEDULER.add_job(
        _job,
        'interval',
        minutes=2,
        id='expense_cloud_retry',
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now() + timedelta(seconds=20),
    )
    _SCHEDULER.start()
    app.logger.info('Expense cloud retry scheduler started (every 2 minutes).')
