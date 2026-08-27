"""APScheduler job that snapshots each day's fleet scores (PKT).

Two runs per day, mirroring the tail of the mileage schedule:
  1) 23:50 → today, while the day is still open on the PortalXS side
  2) 05:30 → yesterday again, once upstream figures have settled

The 23:50 pass is what keeps the trend usable the same evening; the 05:30 pass
is the one whose numbers are final. Snapshotting is idempotent, so the second
run simply overwrites the first.
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta

logger = logging.getLogger(__name__)
_SCHEDULER = None


def _snapshot(app, day_offset: int, label: str):
    with app.app_context():
        from services.fleet_score_service import snapshot_all_active_accounts
        from utils import pk_date

        target = pk_date() + timedelta(days=day_offset)
        logger.info('Fleet score snapshot [%s] starting for %s', label, target)
        for result in snapshot_all_active_accounts(target):
            logger.info('Fleet score snapshot [%s] result: %s', label, result)


def start_fleet_score_scheduler(app):
    global _SCHEDULER

    if os.environ.get('FLEET_SCORE_SNAPSHOT_ENABLED', '1').strip().lower() in ('0', 'false', 'no'):
        return
    try:
        if _SCHEDULER is not None:
            _SCHEDULER.shutdown(wait=False)
    except Exception:
        pass
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        _SCHEDULER = BackgroundScheduler(timezone='Asia/Karachi')

        def _job(day_offset, label):
            def _run():
                try:
                    _snapshot(app, day_offset, label)
                except Exception as exc:
                    logger.warning('Fleet score snapshot %s failed: %s', label, exc)
            return _run

        jobs = [
            ('fleet_score_2350', CronTrigger(hour=23, minute=50, timezone='Asia/Karachi'),
             _job(0, 'today')),
            ('fleet_score_0530', CronTrigger(hour=5, minute=30, timezone='Asia/Karachi'),
             _job(-1, 'yesterday-final')),
        ]
        for job_id, trigger, fn in jobs:
            _SCHEDULER.add_job(fn, trigger=trigger, id=job_id,
                               replace_existing=True, max_instances=1,
                               coalesce=True)
        _SCHEDULER.start()
        if hasattr(app, 'logger'):
            app.logger.info('Fleet score snapshot scheduler started '
                            '(PKT: 23:50 today, 05:30 yesterday-final).')
    except Exception as exc:
        if hasattr(app, 'logger'):
            app.logger.warning('Fleet score snapshot scheduler failed to start: %s', exc)


def stop_fleet_score_scheduler():
    global _SCHEDULER
    try:
        if _SCHEDULER is not None:
            _SCHEDULER.shutdown(wait=False)
    except Exception:
        pass
    _SCHEDULER = None
