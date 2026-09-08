"""Background PSO fuel rate scan — 2:00 AM and 1:00 PM Pakistan time (current date)."""

import logging

logger = logging.getLogger(__name__)
_SCHEDULER = None


def run_fuel_market_scan_job(app, force=False, slot_label=''):
    """Scan PSO rates for today. force=True refreshes even if today's OK cache exists."""
    with app.app_context():
        from routes import _scan_fuel_market_rates

        result = _scan_fuel_market_rates(force=bool(force))
        today = (result or {}).get('scan_date', '')
        status = (result or {}).get('status', '')
        rates = (result or {}).get('rates') or {}
        today_entry = rates.get(today) or {}
        tag = f' [{slot_label}]' if slot_label else ''
        if today_entry.get('ok'):
            logger.info(
                'Fuel market scan OK%s for %s — Petrol: %s, Diesel: %s',
                tag,
                today,
                today_entry.get('petrol'),
                today_entry.get('diesel'),
            )
        elif status == 'ok' or today_entry:
            logger.info('Fuel market scan completed%s for %s (status=%s)', tag, today, status)
        else:
            logger.warning('Fuel market scan did not return today rates%s', tag)


def start_fuel_market_scan_scheduler(app):
    global _SCHEDULER
    import os

    if os.environ.get('FUEL_MARKET_SCAN_ENABLED', '1').strip().lower() in ('0', 'false', 'no'):
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

        def _am_job():
            try:
                # First daily capture for current date (2:00 AM PK).
                run_fuel_market_scan_job(app, force=True, slot_label='02:00')
            except Exception as exc:
                logger.warning('Fuel market scan 02:00 job failed: %s', exc)

        def _pm_job():
            try:
                # Afternoon refresh for current date (1:00 PM PK).
                run_fuel_market_scan_job(app, force=True, slot_label='13:00')
            except Exception as exc:
                logger.warning('Fuel market scan 13:00 job failed: %s', exc)

        _SCHEDULER.add_job(
            _am_job,
            CronTrigger(hour=2, minute=0, timezone='Asia/Karachi'),
            id='fleet_fuel_market_scan_0200',
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _SCHEDULER.add_job(
            _pm_job,
            CronTrigger(hour=13, minute=0, timezone='Asia/Karachi'),
            id='fleet_fuel_market_scan_1300',
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _SCHEDULER.start()
        # Boot catch-up: ensure today has a rate without waiting for next cron.
        try:
            run_fuel_market_scan_job(app, force=False, slot_label='boot')
        except Exception as exc:
            logger.warning('Initial fuel market scan failed: %s', exc)
        if hasattr(app, 'logger'):
            app.logger.info('Fuel market scan scheduler started (02:00 + 13:00 Asia/Karachi).')
    except Exception as exc:
        if hasattr(app, 'logger'):
            app.logger.warning('Fuel market scan scheduler failed: %s', exc)


def stop_fuel_market_scan_scheduler():
    global _SCHEDULER
    try:
        if _SCHEDULER is not None:
            _SCHEDULER.shutdown(wait=False)
    except Exception:
        pass
    _SCHEDULER = None
