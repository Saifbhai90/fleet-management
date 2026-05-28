"""
Recurring FCM + in-app reminders for pending GPS check-in / check-out.

Uses AttendanceSettings checkin_reminder_minutes / checkout_reminder_minutes.
Same business rules as Mark Attendance (time windows, capacity 1/2, vehicle pending
checkout, cross-shift toggles) — does NOT use geofence / live GPS.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_STATE_KEY = 'attendance_reminder_last_sent'


def _load_last_sent():
    from models import SystemSetting

    row = SystemSetting.query.filter_by(key=_STATE_KEY).first()
    if not row or not (row.value or '').strip():
        return {'checkin': {}, 'checkout': {}}
    try:
        data = json.loads(row.value)
        return {
            'checkin': dict(data.get('checkin') or {}),
            'checkout': dict(data.get('checkout') or {}),
        }
    except Exception:
        return {'checkin': {}, 'checkout': {}}


def _save_last_sent(state):
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


def _mark_sent(state, kind, driver_id, when):
    bucket = state.setdefault(kind, {})
    bucket[str(int(driver_id))] = when.isoformat(timespec='seconds')


def _get_sent(state, kind, driver_id):
    raw = (state.get(kind) or {}).get(str(int(driver_id)))
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _reminder_interval_due(last_sent, window_start, now, interval_min):
    if interval_min <= 0 or not window_start:
        return False
    first_due = window_start + timedelta(minutes=interval_min)
    if now < first_due:
        return False
    if last_sent is None:
        return True
    return (now - last_sent) >= timedelta(minutes=interval_min)


def _combine_date_time(d, t):
    if not d or not t:
        return None
    return datetime.combine(d, t)


def _run_auto_gps_checkout(now_dt, helpers):
    """Auto mark check-out after checkout window end for pending GPS sessions."""
    from models import Driver, DriverAttendance, db

    if not helpers['auto_checkout_enabled']():
        return 0

    rows = (
        DriverAttendance.query.join(Driver, Driver.id == DriverAttendance.driver_id)
        .filter(
            Driver.status == 'Active',
            Driver.vehicle_id.isnot(None),
            DriverAttendance.check_in.isnot(None),
            DriverAttendance.check_out.is_(None),
        )
        .order_by(DriverAttendance.attendance_date.asc(), DriverAttendance.id.asc())
        .all()
    )
    updated = 0
    for rec in rows:
        driver = rec.driver
        if not driver:
            continue
        if not helpers['gps_marked'](rec):
            continue
        tw = helpers['time_window'](driver=driver)
        co_s, co_e, _cross = helpers['checkout_bounds'](driver, tw, rec.check_in)
        if not co_e:
            continue
        if not _checkout_window_end_passed(rec.attendance_date, rec.check_in, co_s, co_e, now_dt):
            continue

        end_dt = _checkout_window_end_datetime(
            rec.attendance_date, rec.check_in, co_s, co_e,
        )
        if not end_dt:
            continue

        rec.check_out = end_dt.time()
        rec.check_out_date = end_dt.date()
        rec.updated_at = now_dt
        remark = (rec.remarks or '').strip()
        auto_tag = GPS_AUTO_CHECKOUT_REMARK
        if auto_tag.lower() not in remark.lower():
            rec.remarks = ((remark + ' | ') if remark else '') + auto_tag
        updated += 1
    if updated:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return 0
    return updated


def _vehicle_has_gps_checkin_today(vehicle_id, today, helpers):
    if not vehicle_id:
        return False
    from models import Driver, DriverAttendance

    rows = (
        DriverAttendance.query.join(Driver, Driver.id == DriverAttendance.driver_id)
        .filter(
            Driver.vehicle_id == vehicle_id,
            DriverAttendance.attendance_date == today,
            DriverAttendance.check_in.isnot(None),
        )
        .all()
    )
    for rec in rows:
        if helpers['gps_marked'](rec):
            return True
    return False


def _drivers_on_vehicle(vehicle_id):
    from models import Driver

    if not vehicle_id:
        return []
    return (
        Driver.query.filter(
            Driver.vehicle_id == vehicle_id,
            Driver.status == 'Active',
        )
        .order_by(Driver.id)
        .all()
    )


def _active_checkin_window_starts(driver, tw, now_time, helpers):
    """Window starts for currently active check-in windows this driver may use."""
    shift_l = (driver.shift or '').strip().lower()
    allow_m_n = helpers['allow_morning_night']()
    allow_n_m = helpers['allow_night_morning']()
    in_m = helpers['time_in_window'](
        now_time, tw.get('morning_start'), tw.get('morning_end'),
    )
    in_n = helpers['time_in_window'](
        now_time, tw.get('night_start'), tw.get('night_end'),
    )
    starts = []
    if shift_l == 'morning':
        if in_m and tw.get('morning_start'):
            starts.append(_combine_date_time(helpers['today'], tw['morning_start']))
        if allow_m_n and in_n and tw.get('night_start'):
            starts.append(_combine_date_time(helpers['today'], tw['night_start']))
    elif shift_l == 'night':
        if in_n and tw.get('night_start'):
            starts.append(_combine_date_time(helpers['today'], tw['night_start']))
        if allow_n_m and in_m and tw.get('morning_start'):
            starts.append(_combine_date_time(helpers['today'], tw['morning_start']))
    else:
        if in_m and tw.get('morning_start'):
            starts.append(_combine_date_time(helpers['today'], tw['morning_start']))
        if in_n and tw.get('night_start'):
            starts.append(_combine_date_time(helpers['today'], tw['night_start']))
    return [s for s in starts if s]


def _driver_needs_checkin_reminder(driver, today, helpers):
    if not driver or not driver.vehicle_id:
        return False, None
    if helpers['duty_off'](driver.id, today):
        return False, None
    vehicle = driver.vehicle
    if helpers['vehicle_pending_msg'](driver.id, vehicle, today):
        return False, None
    if helpers['pending_other'](driver.id, driver.vehicle_id, today, helpers['vehicle_cap'](vehicle)):
        return False, None
    if helpers['open_session'](driver.id, today):
        return False, None
    cap = helpers['vehicle_cap'](vehicle)
    if helpers['segment_count'](driver.id, today) >= cap:
        return False, None
    if _vehicle_has_gps_checkin_today(driver.vehicle_id, today, helpers):
        return False, None
    now_time = helpers['now_time']()
    tw = helpers['time_window'](driver=driver)
    ok, _msg = helpers['checkin_window_ok'](driver.shift, now_time, tw, driver=driver, vehicle=vehicle)
    if not ok:
        return False, None
    starts = _active_checkin_window_starts(driver, tw, now_time, helpers)
    if not starts:
        return False, None
    anchor = min(starts)
    return True, anchor


def _driver_needs_checkout_reminder(driver, today, helpers):
    open_rec = helpers['open_checkout'](driver.id, today)
    if not open_rec:
        return False, None
    now_time = helpers['now_time']()
    tw = helpers['time_window'](driver=driver)
    cap = helpers['vehicle_cap'](driver.vehicle)
    if cap == 1:
        mode = helpers['capacity_one_mode']()
        slot = helpers['checkin_slot'](tw, open_rec.check_in)
        if mode == 'morning_only' and slot != 'morning':
            return False, None
        if mode == 'night_only' and slot != 'night':
            return False, None
    ok, _msg = helpers['checkout_window_ok'](driver, now_time, tw, open_rec.check_in)
    if not ok:
        return False, None
    co_s, _co_e, _cross = helpers['checkout_bounds'](driver, tw, open_rec.check_in)
    anchor_t = co_s or open_rec.check_in
    anchor = _combine_date_time(open_rec.attendance_date, anchor_t)
    if not anchor:
        return False, None
    return True, anchor


def _send_driver_reminder(driver, title, message, link, notification_type='warning'):
    from notification_service import notify_user
    from push_notifications import get_user_id_for_driver

    uid = get_user_id_for_driver(driver)
    if not uid:
        return False
    notify_user(uid, title, message, link=link, notification_type=notification_type, push=True)
    return True


def _attendance_settings():
    from models import AttendanceSettings

    return AttendanceSettings.query.first()


def _build_helpers():
    from utils import pk_now, pk_date, pk_time

    from routes import (
        _attendance_allow_morning_driver_night_gps_checkin,
        _attendance_allow_night_driver_morning_gps_checkin,
        _attendance_local_date,
        _attendance_time_in_window,
        _count_driver_segments_with_checkin,
        _driver_marked_duty_off_no_checkin,
        _get_effective_time_window,
        _gps_checkin_shift_window_ok,
        _gps_checkout_window_bounds,
        _gps_checkout_window_ok,
        _gps_marked_attendance_row,
        _attendance_auto_gps_checkout_on_window_end_enabled,
        _attendance_capacity_one_checkin_mode,
        _checkin_window_slot_from_time,
        _checkout_window_end_datetime,
        _checkout_window_end_passed,
        GPS_AUTO_CHECKOUT_REMARK,
        _manual_checkin_blocked_by_vehicle_rules,
        _open_gps_driver_attendance_for_checkout,
        _open_gps_driver_attendance_session,
        _pending_blocked_by_other_driver_on_vehicle,
        _vehicle_capacity_value,
        _vehicle_pending_checkout_block_message,
    )

    today = _attendance_local_date()

    return {
        'today': today,
        'now': pk_now,
        'now_time': pk_time,
        'time_window': _get_effective_time_window,
        'time_in_window': _attendance_time_in_window,
        'allow_morning_night': _attendance_allow_morning_driver_night_gps_checkin,
        'allow_night_morning': _attendance_allow_night_driver_morning_gps_checkin,
        'checkin_window_ok': _gps_checkin_shift_window_ok,
        'checkout_window_ok': _gps_checkout_window_ok,
        'checkout_bounds': _gps_checkout_window_bounds,
        'duty_off': _driver_marked_duty_off_no_checkin,
        'vehicle_pending_msg': _manual_checkin_blocked_by_vehicle_rules,
        'auto_checkout_enabled': _attendance_auto_gps_checkout_on_window_end_enabled,
        'capacity_one_mode': _attendance_capacity_one_checkin_mode,
        'checkin_slot': _checkin_window_slot_from_time,
        'vehicle_cap': _vehicle_capacity_value,
        'segment_count': _count_driver_segments_with_checkin,
        'open_session': _open_gps_driver_attendance_session,
        'open_checkout': _open_gps_driver_attendance_for_checkout,
        'pending_other': _pending_blocked_by_other_driver_on_vehicle,
        'gps_marked': _gps_marked_attendance_row,
    }


def run_attendance_reminders(app=None):
    """Evaluate all active drivers; send due check-in / check-out reminders."""
    import os

    if os.environ.get('ATTENDANCE_REMINDER_ENABLED', '1').strip().lower() in ('0', 'false', 'no'):
        return {'skipped': 'disabled'}

    ctx = app.app_context() if app is not None else None
    if ctx is not None:
        ctx.push()

    try:
        settings = _attendance_settings()
        if not settings:
            return {'checkin_sent': 0, 'checkout_sent': 0}
        ci_min = int(settings.checkin_reminder_minutes or 0)
        co_min = int(settings.checkout_reminder_minutes or 0)
        if ci_min <= 0 and co_min <= 0:
            return {'checkin_sent': 0, 'checkout_sent': 0}

        helpers = _build_helpers()
        today = helpers['today']
        now = helpers['now']()
        state = _load_last_sent()
        checkin_sent = 0
        checkout_sent = 0
        auto_checkout_done = _run_auto_gps_checkout(now, helpers)

        try:
            from flask import url_for
            link_checkin = url_for('driver_attendance_checkin', _external=True)
            link_checkout = url_for('driver_attendance_checkout', _external=True)
        except Exception:
            link_checkin = '/driver-attendance/checkin'
            link_checkout = '/driver-attendance/checkout'

        from models import Driver

        drivers = Driver.query.filter(
            Driver.status == 'Active',
            Driver.vehicle_id.isnot(None),
        ).all()

        vehicles_done_checkin = set()

        if ci_min > 0:
            for driver in drivers:
                vid = driver.vehicle_id
                if vid in vehicles_done_checkin:
                    continue
                if _vehicle_has_gps_checkin_today(vid, today, helpers):
                    vehicles_done_checkin.add(vid)
                    continue
                needs, anchor = _driver_needs_checkin_reminder(driver, today, helpers)
                if not needs or not anchor:
                    continue
                last = _get_sent(state, 'checkin', driver.id)
                if not _reminder_interval_due(last, anchor, now, ci_min):
                    continue
                v_no = (driver.vehicle.vehicle_no if driver.vehicle else '') or 'Vehicle'
                title = 'Check-in reminder'
                body = (
                    f'{driver.name}, aaj {v_no} par GPS + Camera check-in pending hai. '
                    f'Mark At Attendance se check-in karein.'
                )
                if _send_driver_reminder(driver, title, body, link_checkin):
                    _mark_sent(state, 'checkin', driver.id, now)
                    checkin_sent += 1

        if co_min > 0:
            for driver in drivers:
                needs, anchor = _driver_needs_checkout_reminder(driver, today, helpers)
                if not needs or not anchor:
                    continue
                last = _get_sent(state, 'checkout', driver.id)
                if not _reminder_interval_due(last, anchor, now, co_min):
                    continue
                title = 'Check-out reminder'
                body = (
                    f'{driver.name}, aap ka check-out abhi pending hai. '
                    f'Mark Check-out se selfie + GPS check-out complete karein.'
                )
                if _send_driver_reminder(driver, title, body, link_checkout):
                    _mark_sent(state, 'checkout', driver.id, now)
                    checkout_sent += 1

        _save_last_sent(state)
        return {
            'checkin_sent': checkin_sent,
            'checkout_sent': checkout_sent,
            'auto_checkout_done': auto_checkout_done,
        }
    except Exception as exc:
        logger.exception('run_attendance_reminders failed: %s', exc)
        return {'error': str(exc)}
    finally:
        if ctx is not None:
            ctx.pop()


def notify_vehicle_peers_after_checkout(completed_driver, vehicle=None):
    """
    After GPS check-out: notify other drivers on same vehicle when cross-shift
    GPS settings are ON (notify_on_attendance_mark must be enabled).
    """
    from models import AttendanceSettings, Driver

    settings = AttendanceSettings.query.first()
    if not settings or not settings.notify_on_attendance_mark:
        return 0
    if not completed_driver:
        return 0
    vehicle = vehicle or completed_driver.vehicle
    if not vehicle or not vehicle.id:
        return 0

    from routes import (
        _attendance_allow_morning_driver_night_gps_checkin,
        _attendance_allow_night_driver_morning_gps_checkin,
    )

    cross_on = (
        _attendance_allow_morning_driver_night_gps_checkin()
        or _attendance_allow_night_driver_morning_gps_checkin()
    )
    if not cross_on:
        return 0

    v_no = (vehicle.vehicle_no or '').strip() or 'Vehicle'
    name = (completed_driver.name or '').strip() or 'Driver'
    title = 'Vehicle check-out update'
    body = (
        f'{v_no}: {name} ne check-out complete kar liya. '
        f'Aap apni attendance / shift status check karein.'
    )
    try:
        from flask import url_for
        link = url_for('driver_attendance_checkout', _external=True)
    except Exception:
        link = '/driver-attendance/checkout'

    sent = 0
    for peer in _drivers_on_vehicle(vehicle.id):
        if peer.id == completed_driver.id:
            continue
        if _send_driver_reminder(peer, title, body, link, notification_type='info'):
            sent += 1
    return sent
