"""APScheduler job for License/CNIC expiry & Oil Change alert reminders.

Runs once every hour (checks internally if notification was already sent today).
Actual notifications are only sent once per day per driver/vehicle.
"""

import logging

logger = logging.getLogger(__name__)
_SCHEDULER = None


def start_expiry_reminder_scheduler(app):
    global _SCHEDULER
    import os

    if os.environ.get('EXPIRY_REMINDER_ENABLED', '1').strip().lower() in ('0', 'false', 'no'):
        return
    try:
        if _SCHEDULER is not None:
            _SCHEDULER.shutdown(wait=False)
    except Exception:
        pass
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        _SCHEDULER = BackgroundScheduler()

        def _job():
            try:
                from expiry_reminder_service import run_all_expiry_reminders
                result = run_all_expiry_reminders(app)
                lc = result.get('license_cnic', {})
                oc = result.get('oil_change', {})
                sent = (
                    lc.get('license_sent', 0) + lc.get('cnic_sent', 0) +
                    oc.get('near_sent', 0) + oc.get('crossed_sent', 0)
                )
                if sent:
                    logger.info('Expiry/Oil reminders sent: %s', result)
            except Exception as exc:
                logger.warning('Expiry reminder job failed: %s', exc)

        _SCHEDULER.add_job(
            _job,
            'interval',
            minutes=5,
            id='fleet_expiry_reminders',
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _SCHEDULER.start()
        if hasattr(app, 'logger'):
            app.logger.info('Expiry/Oil change reminder scheduler started (every 5 min).')
    except Exception as exc:
        if hasattr(app, 'logger'):
            app.logger.warning('Expiry reminder scheduler failed: %s', exc)


def stop_expiry_reminder_scheduler():
    global _SCHEDULER
    try:
        if _SCHEDULER is not None:
            _SCHEDULER.shutdown(wait=False)
    except Exception:
        pass
    _SCHEDULER = None
