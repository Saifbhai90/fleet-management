"""
License / CNIC Expiry & Oil Change Alert Notification Service.

Scheduled to run once daily (via scheduler in app.py).
Sends FCM push + in-app notifications at configured intervals before expiry.

License/CNIC Reminders:
  - 30 days before expiry
  - 15 days before expiry
  - 7 days before expiry
  - Daily from 3 days before expiry until document is updated

Oil Change Reminders:
  - When status is 'near' (remaining <= 300 km): daily reminder
  - When status is 'crossed' (overdue): daily reminder
  - Continues until oil change record is updated
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

_STATE_KEY = 'expiry_reminder_last_sent'


def _load_state():
    from models import SystemSetting
    row = SystemSetting.query.filter_by(key=_STATE_KEY).first()
    if not row or not (row.value or '').strip():
        return {}
    try:
        return json.loads(row.value)
    except Exception:
        return {}


def _save_state(state):
    from models import db, SystemSetting
    row = SystemSetting.query.filter_by(key=_STATE_KEY).first()
    payload = json.dumps(state, default=str)
    if row:
        row.value = payload
    else:
        db.session.add(SystemSetting(key=_STATE_KEY, value=payload))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def _today():
    from utils import pk_now
    return pk_now().date()


def _should_send_today(state, key, today_str):
    """Check if reminder was already sent today for this key."""
    return state.get(key) != today_str


def _mark_sent(state, key, today_str):
    state[key] = today_str


# ────────────────────────────────────────────────────────────────
# License / CNIC Expiry Notifications
# ────────────────────────────────────────────────────────────────

def _expiry_reminder_days():
    """Days before expiry when reminders should fire."""
    return [30, 15, 7, 3, 2, 1, 0, -1, -2, -3, -7, -15, -30, -60, -90]


def _should_remind_for_days_left(days_left):
    """
    Returns True if a reminder should be sent for this many days remaining.
    - 30 days: first reminder
    - 15 days: second reminder
    - 7 days: third reminder
    - 3 days or less (including negative = expired): daily
    """
    if days_left <= 3:
        return True
    if days_left in (30, 15, 7):
        return True
    return False


def _expiry_message(driver_name, doc_type, days_left):
    """Generate appropriate notification title and message."""
    if days_left > 0:
        title = f'{doc_type} Expiry Warning'
        message = f"Driver {driver_name}'s {doc_type} will expire in {days_left} day{'s' if days_left != 1 else ''}."
    elif days_left == 0:
        title = f'{doc_type} Expires Today'
        message = f"Driver {driver_name}'s {doc_type} expires today. Immediate action required."
    else:
        title = f'{doc_type} Expired'
        message = f"Driver {driver_name}'s {doc_type} has expired. Immediate action required."
    return title, message


def run_license_cnic_reminders(app):
    """Check all active drivers for license/CNIC expiry and send notifications."""
    from models import Driver
    from notification_service import notify_user, get_dto_user_ids_for_scope
    from push_notifications import get_user_id_for_driver

    results = {'license_sent': 0, 'cnic_sent': 0, 'skipped': 0}

    with app.app_context():
        today = _today()
        today_str = today.isoformat()
        state = _load_state()

        drivers = Driver.query.filter_by(status='Active').all()

        for driver in drivers:
            driver_name = (driver.name or '').strip() or f'#{driver.driver_id}'

            # License expiry check
            if driver.license_expiry_date:
                days_left = (driver.license_expiry_date - today).days
                if _should_remind_for_days_left(days_left):
                    state_key = f'lic:{driver.id}:{today_str}'
                    if _should_send_today(state, state_key, today_str):
                        title, message = _expiry_message(driver_name, 'License', days_left)
                        _send_expiry_notification(
                            driver, title, message,
                            notify_user, get_user_id_for_driver, get_dto_user_ids_for_scope
                        )
                        _mark_sent(state, state_key, today_str)
                        results['license_sent'] += 1
                    else:
                        results['skipped'] += 1

            # CNIC expiry check
            if driver.cnic_expiry_date:
                days_left = (driver.cnic_expiry_date - today).days
                if _should_remind_for_days_left(days_left):
                    state_key = f'cnic:{driver.id}:{today_str}'
                    if _should_send_today(state, state_key, today_str):
                        title, message = _expiry_message(driver_name, 'CNIC', days_left)
                        _send_expiry_notification(
                            driver, title, message,
                            notify_user, get_user_id_for_driver, get_dto_user_ids_for_scope
                        )
                        _mark_sent(state, state_key, today_str)
                        results['cnic_sent'] += 1
                    else:
                        results['skipped'] += 1

        _save_state(state)
    return results


def _send_expiry_notification(driver, title, message, notify_user, get_user_id_for_driver, get_dto_user_ids_for_scope):
    """Send notification to driver + DTOs."""
    # Notify driver
    uid = get_user_id_for_driver(driver)
    if uid:
        notify_user(uid, title, message, notification_type='warning', link=None)

    # Notify DTOs for driver's district/project
    district_id = driver.district_id
    project_id = driver.project_id
    if district_id and project_id:
        driver_name = (driver.name or '').strip()
        dto_body = f'{message}\nDriver: {driver_name}'
        for dto_uid in get_dto_user_ids_for_scope(district_id, project_id):
            notify_user(dto_uid, title, dto_body, notification_type='warning', link=None)


# ────────────────────────────────────────────────────────────────
# Oil Change Alert Notifications
# ────────────────────────────────────────────────────────────────

def run_oil_change_reminders(app):
    """Check vehicles with 'near' or 'crossed' oil change status and send daily reminders."""
    from notification_service import notify_user, get_dto_user_ids_for_scope

    results = {'near_sent': 0, 'crossed_sent': 0, 'skipped': 0}

    with app.app_context():
        today = _today()
        today_str = today.isoformat()
        state = _load_state()

        try:
            from routes import _oil_change_alert_rows
            rows = _oil_change_alert_rows(statuses=['near', 'crossed'])
        except Exception as exc:
            logger.warning('Oil change alert rows failed: %s', exc)
            return results

        for row in rows:
            vehicle = row['vehicle']
            status = row['status']
            remaining_km = row.get('remaining_km', 0)
            v_no = (vehicle.vehicle_no or '').strip()

            state_key = f'oil:{vehicle.id}:{today_str}'
            if not _should_send_today(state, state_key, today_str):
                results['skipped'] += 1
                continue

            if status == 'near':
                title = 'Oil Change Due Soon'
                message = f'Vehicle {v_no} requires an oil change within {int(max(0, remaining_km))} KM.'
                results['near_sent'] += 1
            elif status == 'crossed':
                title = 'Oil Change Overdue'
                message = f'Vehicle {v_no} has exceeded its oil change limit. Immediate maintenance is required.'
                results['crossed_sent'] += 1
            else:
                continue

            _send_oil_change_notification(
                vehicle, title, message, notify_user, get_dto_user_ids_for_scope
            )
            _mark_sent(state, state_key, today_str)

        _save_state(state)
    return results


def _send_oil_change_notification(vehicle, title, message, notify_user, get_dto_user_ids_for_scope):
    """Send oil change notification to DTOs for this vehicle's scope."""
    district_id = vehicle.district_id
    project_id = vehicle.project_id
    if not district_id or not project_id:
        return

    v_no = (vehicle.vehicle_no or '').strip()
    dto_body = f'{message}\nVehicle: {v_no}'
    for dto_uid in get_dto_user_ids_for_scope(district_id, project_id):
        notify_user(dto_uid, title, dto_body, notification_type='warning', link=None)


# ────────────────────────────────────────────────────────────────
# Combined runner (called by scheduler)
# ────────────────────────────────────────────────────────────────

def run_all_expiry_reminders(app):
    """Run all expiry and oil change reminder checks."""
    results = {}
    try:
        r1 = run_license_cnic_reminders(app)
        results['license_cnic'] = r1
    except Exception as exc:
        logger.warning('License/CNIC reminder failed: %s', exc)
        results['license_cnic_error'] = str(exc)

    try:
        r2 = run_oil_change_reminders(app)
        results['oil_change'] = r2
    except Exception as exc:
        logger.warning('Oil change reminder failed: %s', exc)
        results['oil_change_error'] = str(exc)

    return results
