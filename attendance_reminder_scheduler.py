"""APScheduler job for attendance check-in / check-out reminders."""

import logging

logger = logging.getLogger(__name__)
_SCHEDULER = None


def start_attendance_reminder_scheduler(app):
    global _SCHEDULER
    import os

    if os.environ.get('ATTENDANCE_REMINDER_ENABLED', '1').strip().lower() in ('0', 'false', 'no'):
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
                from attendance_reminder_service import run_attendance_reminders
                result = run_attendance_reminders(app)
                if result.get('checkin_sent') or result.get('checkout_sent'):
                    logger.info('Attendance reminders: %s', result)
            except Exception as exc:
                logger.warning('Attendance reminder job failed: %s', exc)

        _SCHEDULER.add_job(
            _job,
            'interval',
            minutes=1,
            id='fleet_attendance_reminders',
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _SCHEDULER.start()
        if hasattr(app, 'logger'):
            app.logger.info('Attendance reminder scheduler started (every 1 min).')
    except Exception as exc:
        if hasattr(app, 'logger'):
            app.logger.warning('Attendance reminder scheduler failed: %s', exc)


def stop_attendance_reminder_scheduler():
    global _SCHEDULER
    try:
        if _SCHEDULER is not None:
            _SCHEDULER.shutdown(wait=False)
    except Exception:
        pass
    _SCHEDULER = None
