"""APScheduler jobs for PortalXS → vehicle_mileage_record auto sync (PKT).

Rolling day cycle (example for 26 Aug):
  1) 26 Aug 12:00 AM  → full fleet refresh for 26
  2) 26 Aug  3:00 PM  → full fleet refresh for 26
  3) 26 Aug  3:50 PM  → full fleet refresh for 26
  4) 26 Aug 11:57 PM  → full fleet refresh for 26
  5) 27 Aug 12:15 AM  → full fleet catch-up for 26
  6) 27 Aug  5:00 AM  → final for 26, then start 27

Each run re-fetches ALL vehicles and upserts (Excel-protected regs skipped).
"""

from __future__ import annotations

import logging
from datetime import timedelta

logger = logging.getLogger(__name__)
_SCHEDULER = None


def _run_sync_for_offset(app, day_offset: int, label: str):
    with app.app_context():
        from utils import pk_date
        from services.mileage_record_service import sync_all_active_accounts_for_day

        target = pk_date() + timedelta(days=day_offset)
        logger.info('Mileage auto-sync [%s] starting for %s', label, target)
        results = sync_all_active_accounts_for_day(target)
        for r in results:
            logger.info('Mileage auto-sync [%s] result: %s', label, r)


def _run_slot6(app):
    """05:00 PKT — yesterday final, then today first fill."""
    with app.app_context():
        from utils import pk_date
        from services.mileage_record_service import sync_all_active_accounts_for_day

        today = pk_date()
        yesterday = today - timedelta(days=1)
        logger.info('Mileage auto-sync [slot6] final for %s then start %s', yesterday, today)
        for target, label in ((yesterday, 'slot6-yesterday-final'), (today, 'slot6-today-start')):
            try:
                results = sync_all_active_accounts_for_day(target)
                for r in results:
                    logger.info('Mileage auto-sync [%s] result: %s', label, r)
            except Exception as exc:
                logger.warning('Mileage auto-sync [%s] failed: %s', label, exc)


def start_mileage_auto_scheduler(app):
    global _SCHEDULER
    import os

    if os.environ.get('MILEAGE_AUTO_SYNC_ENABLED', '1').strip().lower() in ('0', 'false', 'no'):
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
                    logger.warning('Mileage auto-sync %s failed: %s', label, exc)
            return _job

        def _yesterday_job(label):
            def _job():
                try:
                    _run_sync_for_offset(app, -1, label)
                except Exception as exc:
                    logger.warning('Mileage auto-sync %s failed: %s', label, exc)
            return _job

        def _slot6_job():
            try:
                _run_slot6(app)
            except Exception as exc:
                logger.warning('Mileage auto-sync slot6 failed: %s', exc)

        jobs = [
            ('mileage_auto_0000', CronTrigger(hour=0, minute=0, timezone='Asia/Karachi'), _today_job('slot1-0000')),
            ('mileage_auto_1500', CronTrigger(hour=15, minute=0, timezone='Asia/Karachi'), _today_job('slot2-1500')),
            ('mileage_auto_1550', CronTrigger(hour=15, minute=50, timezone='Asia/Karachi'), _today_job('slot3-1550')),
            ('mileage_auto_2357', CronTrigger(hour=23, minute=57, timezone='Asia/Karachi'), _today_job('slot4-2357')),
            ('mileage_auto_0015', CronTrigger(hour=0, minute=15, timezone='Asia/Karachi'), _yesterday_job('slot5-0015-catchup')),
            ('mileage_auto_0500', CronTrigger(hour=5, minute=0, timezone='Asia/Karachi'), _slot6_job),
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
                'Mileage auto-sync scheduler started (PKT: 00:00, 15:00, 15:50, 23:57, '
                '00:15 catch-up yesterday, 05:00 yesterday-final + today).'
            )
    except Exception as exc:
        if hasattr(app, 'logger'):
            app.logger.warning('Mileage auto-sync scheduler failed to start: %s', exc)


def stop_mileage_auto_scheduler():
    global _SCHEDULER
    try:
        if _SCHEDULER is not None:
            _SCHEDULER.shutdown(wait=False)
    except Exception:
        pass
    _SCHEDULER = None
