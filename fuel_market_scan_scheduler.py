"""Background PSO fuel rate scan — runs even when Add Fuel Expense is not opened."""

import logging

logger = logging.getLogger(__name__)
_SCHEDULER = None


def run_fuel_market_scan_job(app):
    """Scan PSO rates for today if not already cached."""
    with app.app_context():
        from routes import _scan_fuel_market_rates

        result = _scan_fuel_market_rates(force=False)
        today = (result or {}).get('scan_date', '')
        status = (result or {}).get('status', '')
        rates = (result or {}).get('rates') or {}
        today_entry = rates.get(today) or {}
        if today_entry.get('ok'):
            logger.info(
                'Fuel market scan OK for %s — Petrol: %s, Diesel: %s',
                today,
                today_entry.get('petrol'),
                today_entry.get('diesel'),
            )
        elif status == 'ok' or today_entry:
            logger.info('Fuel market scan completed for %s (status=%s)', today, status)
        else:
            logger.warning('Fuel market scan did not return today rates')


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

        _SCHEDULER = BackgroundScheduler()

        def _job():
            try:
                run_fuel_market_scan_job(app)
            except Exception as exc:
                logger.warning('Fuel market scan job failed: %s', exc)

        _SCHEDULER.add_job(
            _job,
            'interval',
            hours=1,
            id='fleet_fuel_market_scan',
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _SCHEDULER.start()
        try:
            run_fuel_market_scan_job(app)
        except Exception as exc:
            logger.warning('Initial fuel market scan failed: %s', exc)
        if hasattr(app, 'logger'):
            app.logger.info('Fuel market scan scheduler started (every 1 hour).')
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
