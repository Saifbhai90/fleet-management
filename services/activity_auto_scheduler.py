"""APScheduler jobs for PortalXS → vehicle_activity_record auto sync (PKT).

Rolling day cycle (example for 26 Aug):
  1) 26 Aug 04:00 PM  → full fleet refresh for 26
  2) 26 Aug 11:00 AM  → full fleet refresh for 26
  3) 27 Aug 05:00 AM  → final full fleet refresh for 26

Each run re-fetches ALL vehicles and upserts (Excel-protected regs skipped).
Disable with ACTIVITY_AUTO_SYNC_ENABLED=0.
"""

from __future__ import annotations

import logging
from datetime import timedelta

logger = logging.getLogger(__name__)
_SCHEDULER = None


def _run_sync_for_offset(app, day_offset: int, label: str):
    with app.app_context():
        from utils import pk_date
        from services.activity_record_service import sync_all_active_accounts_for_day

        target = pk_date() + timedelta(days=day_offset)
        logger.info('Activity auto-sync [%s] starting for %s', label, target)
        results = sync_all_active_accounts_for_day(target)
        for r in results:
            logger.info('Activity auto-sync [%s] result: %s', label, r)


def start_activity_auto_scheduler(app):
    global _SCHEDULER
    import os

    if os.environ.get('ACTIVITY_AUTO_SYNC_ENABLED', '1').strip().lower() in ('0', 'false', 'no'):
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

        def _today_job(label):
            def _job():
                try:
                    _run_sync_for_offset(app, 0, label)
                except Exception as exc:
                    logger.warning('Activity auto-sync %s failed: %s', label, exc)
            return _job

        def _yesterday_job(label):
            def _job():
                try:
                    _run_sync_for_offset(app, -1, label)
                except Exception as exc:
                    logger.warning('Activity auto-sync %s failed: %s', label, exc)
            return _job

        jobs = [
            # Same calendar day: midday + afternoon refresh
            ('activity_auto_1100', CronTrigger(hour=11, minute=0, timezone='Asia/Karachi'), _today_job('slot1-1100')),
            ('activity_auto_1600', CronTrigger(hour=16, minute=0, timezone='Asia/Karachi'), _today_job('slot2-1600')),
            # Next morning: final catch-up for previous date
            ('activity_auto_0500_prev', CronTrigger(hour=5, minute=0, timezone='Asia/Karachi'), _yesterday_job('slot3-0500-yesterday-final')),
        ]

        for job_id, trigger, fn in jobs:
            _SCHEDULER.add_job(
                fn,
                trigger=trigger,
                id=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
        _SCHEDULER.start()
        if hasattr(app, 'logger'):
            app.logger.info(
                'Activity auto-sync scheduler started (PKT: 11:00 today, 16:00 today, '
                '05:00 yesterday-final).'
            )
    except Exception as exc:
        if hasattr(app, 'logger'):
            app.logger.warning('Activity auto-sync scheduler failed to start: %s', exc)


def stop_activity_auto_scheduler():
    global _SCHEDULER
    try:
        if _SCHEDULER is not None:
            _SCHEDULER.shutdown(wait=False)
    except Exception:
        pass
    _SCHEDULER = None
