"""
Fleet Manager notification service (v2).

- Per-user in-app notifications (target_user_id) + FCM push
- Driver attendance (GPS+Camera) and task report entry events
- DTO recipients matched by vehicle district + project assignments
"""

from __future__ import annotations

import logging

from sqlalchemy import func

logger = logging.getLogger(__name__)

NOTIFICATIONS_V2_SETTING_KEY = 'notifications_v2_purged'


def _invalidate_notif_cache(user_ids):
    try:
        from app import _notif_cache
        for uid in user_ids or []:
            _notif_cache.pop(f'notif_{uid}', None)
    except Exception:
        pass


def _is_cloud_media_url(path):
    p = (path or '').strip().lower()
    return p.startswith('http://') or p.startswith('https://')


def _is_parking_full_notification(notification):
    if not notification:
        return False
    t = ((notification.title or '') + ' ' + (notification.message or '')).lower()
    return 'parking' in t and 'full' in t


def notification_visible_to_user(notification, user_id, user_perms=None, is_master=False):
    """Whether this notification row should appear for the given user."""
    if _is_parking_full_notification(notification):
        return False
    tid = getattr(notification, 'target_user_id', None)
    if tid is not None:
        return int(tid) == int(user_id)
    if notification.required_permission:
        if is_master:
            return True
        req_codes = set((notification.required_permission or '').split(','))
        return bool(set(user_perms or []) & req_codes)
    return False


def _ensure_target_user_id_column():
    from models import db

    try:
        with db.engine.connect() as conn:
            uri = (db.engine.url.drivername or '').lower()
            if 'sqlite' in uri:
                r = conn.execute(db.text('PRAGMA table_info(notification)'))
                cols = [row[1] for row in r]
                if 'target_user_id' not in cols:
                    conn.execute(db.text(
                        'ALTER TABLE notification ADD COLUMN target_user_id INTEGER REFERENCES user(id)'
                    ))
                    conn.commit()
            else:
                conn.execute(db.text(
                    'ALTER TABLE notification ADD COLUMN IF NOT EXISTS target_user_id INTEGER '
                    'REFERENCES "user"(id) ON DELETE CASCADE'
                ))
                conn.commit()
    except Exception as exc:
        logger.warning('target_user_id column ensure skipped: %s', exc)


def purge_legacy_notifications_once():
    """Delete all legacy notifications once per deployment (SystemSetting flag)."""
    from models import db, Notification, NotificationRead, SystemSetting

    _ensure_target_user_id_column()
    flag = SystemSetting.query.filter_by(key=NOTIFICATIONS_V2_SETTING_KEY).first()
    if flag and (flag.value or '').strip() == '1':
        return False
    try:
        NotificationRead.query.delete()
        Notification.query.delete()
        if not flag:
            flag = SystemSetting(key=NOTIFICATIONS_V2_SETTING_KEY, value='1')
            db.session.add(flag)
        else:
            flag.value = '1'
        db.session.commit()
        logger.info('Legacy notifications purged (v2 reset).')
        return True
    except Exception as exc:
        db.session.rollback()
        logger.exception('purge_legacy_notifications_once failed: %s', exc)
        return False


def get_dto_post_ids():
    from models import EmployeePost

    ids = []
    for p in EmployeePost.query.all():
        sn = (p.short_name or '').strip().upper()
        fn = (p.full_name or '').strip().lower()
        if sn == 'DTO' or 'district transport' in fn:
            ids.append(p.id)
    return ids


def get_dto_user_ids_for_scope(district_id, project_id):
    """Users with DTO post whose Employee is assigned to this district and project."""
    from models import User, Employee, employee_district, employee_project, db

    if not district_id or not project_id:
        return []
    dto_post_ids = get_dto_post_ids()
    if not dto_post_ids:
        return []

    user_ids = set()
    emp_rows = (
        db.session.query(Employee.id, Employee.cnic_no)
        .join(employee_district, Employee.id == employee_district.c.employee_id)
        .join(employee_project, Employee.id == employee_project.c.employee_id)
        .filter(
            employee_district.c.district_id == district_id,
            employee_project.c.project_id == project_id,
            Employee.post_id.in_(dto_post_ids),
        )
        .distinct()
        .all()
    )
    for _eid, cnic in emp_rows:
        if not cnic:
            continue
        cnic_s = cnic.strip()
        variants = {cnic_s, cnic_s.replace('-', '')}
        for v in variants:
            u = User.query.filter(
                User.is_active == True,
                func.lower(User.username) == v.lower(),
            ).first()
            if u:
                user_ids.add(u.id)
                break

    for u in User.query.filter(
        User.is_active == True,
        User.employee_post_id.in_(dto_post_ids),
    ).all():
        emp = None
        uname = (u.username or '').strip()
        for v in (uname, uname.replace('-', '')):
            if not v:
                continue
            emp = Employee.query.filter(func.lower(Employee.cnic_no) == v.lower()).first()
            if emp:
                break
        if not emp:
            continue
        dist_ids = {d.id for d in emp.districts.all() if d and d.id}
        proj_ids = {p.id for p in emp.projects.all() if p and p.id}
        if district_id in dist_ids and project_id in proj_ids:
            user_ids.add(u.id)

    return list(user_ids)


def _vehicle_scope_from_driver(driver, vehicle=None):
    from models import Vehicle

    v = vehicle
    if not v and driver and getattr(driver, 'vehicle_id', None):
        v = Vehicle.query.get(driver.vehicle_id)
    if not v:
        return None, None, ''
    v_no = (v.vehicle_no or '').strip()
    district_id = v.district_id or getattr(driver, 'district_id', None)
    project_id = v.project_id or getattr(driver, 'project_id', None)
    return district_id, project_id, v_no


def notify_user(user_id, title, message, *, link=None, link_text=None, notification_type='info', push=True):
    """Create in-app notification for one user and optionally send FCM."""
    if not user_id:
        return None
    from models import db, Notification

    n = Notification(
        title=title,
        message=message,
        link=link,
        link_text=link_text,
        notification_type=notification_type,
        target_user_id=int(user_id),
        required_permission=None,
        created_by_user_id=None,
    )
    db.session.add(n)
    try:
        db.session.flush()
    except Exception:
        db.session.rollback()
        raise
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    if push:
        try:
            from push_notifications import send_push
            send_push(int(user_id), title, message or '', link=link)
        except Exception as exc:
            logger.warning('FCM push failed user %s: %s', user_id, exc)
    _invalidate_notif_cache([user_id])
    return n


def _notify_driver_user(driver, title, message, link=None):
    from push_notifications import get_user_id_for_driver

    uid = get_user_id_for_driver(driver)
    if uid:
        notify_user(uid, title, message, link=link, notification_type='success')


def _notify_dtos(district_id, project_id, driver, vehicle_no, title, message, link=None):
    driver_name = (driver.name or '').strip() if driver else ''
    v_no = (vehicle_no or '').strip()
    body = message
    if driver_name or v_no:
        parts = []
        if driver_name:
            parts.append(f'Driver: {driver_name}')
        if v_no:
            parts.append(f'Vehicle: {v_no}')
        body = (message or '').strip()
        if body:
            body = body + '\n' + ' | '.join(parts)
        else:
            body = ' | '.join(parts)
    for uid in get_dto_user_ids_for_scope(district_id, project_id):
        notify_user(uid, title, body, link=link, notification_type='info')


def notify_gps_checkin(driver, photo_path, *, vehicle=None):
    """After GPS+Camera check-in with photo stored (prefer R2/cloud URL)."""
    if not driver or not _is_cloud_media_url(photo_path):
        return
    district_id, project_id, v_no = _vehicle_scope_from_driver(driver, vehicle)
    if not district_id or not project_id:
        return
    driver_title = 'Attendance Marked'
    driver_msg = (
        f'{driver.name}, aap ki attendance check-in mark ho chuki hai. '
        f'Photo upload ho chuki hai ({pk_time_str()}).'
    )
    dto_title = 'Driver Check-in'
    dto_msg = f'GPS + Camera check-in upload ho gaya.'
    link = None
    try:
        from flask import url_for
        from utils import pk_now as _pk

        today = _pk().date()
        link = url_for('driver_attendance_list', date=today.strftime('%d-%m-%Y'), _external=True)
    except Exception:
        pass
    _notify_driver_user(driver, driver_title, driver_msg, link=link)
    _notify_dtos(district_id, project_id, driver, v_no, dto_title, dto_msg, link=link)


def notify_gps_checkout(driver, photo_path, *, vehicle=None):
    """After GPS+Camera check-out with photo stored (prefer R2/cloud URL)."""
    if not driver or not _is_cloud_media_url(photo_path):
        return
    district_id, project_id, v_no = _vehicle_scope_from_driver(driver, vehicle)
    if not district_id or not project_id:
        return
    driver_title = 'Check-out Complete'
    driver_msg = (
        f'{driver.name}, aap ka check-out upload ho gaya hai aur duty successfully end ho gayi hai. '
        f'({pk_time_str()})'
    )
    dto_title = 'Driver Check-out'
    dto_msg = 'GPS + Camera check-out upload ho gaya; duty end.'
    link = None
    try:
        from flask import url_for
        from utils import pk_now as _pk

        today = _pk().date()
        link = url_for('driver_attendance_list', date=today.strftime('%d-%m-%Y'), _external=True)
    except Exception:
        pass
    _notify_driver_user(driver, driver_title, driver_msg, link=link)
    _notify_dtos(district_id, project_id, driver, v_no, dto_title, dto_msg, link=link)


def notify_task_report_saved(vehicle, task_date, *, driver=None):
    """After New Task Entry save for a vehicle."""
    from models import Driver, Vehicle

    if not vehicle:
        return
    if not driver and vehicle.driver_id:
        driver = Driver.query.get(vehicle.driver_id)
    district_id = vehicle.district_id
    project_id = vehicle.project_id
    if not district_id or not project_id:
        return
    v_no = (vehicle.vehicle_no or '').strip()
    date_s = task_date.strftime('%d-%m-%Y') if task_date else ''
    driver_title = 'Task Report Saved'
    driver_msg = f'Aap ki vehicle {v_no} ki task report {date_s} par save ho gayi hai.'
    dto_title = 'Task Report Saved'
    dto_msg = f'Task report save ho gayi ({date_s}).'
    link = None
    try:
        from flask import url_for
        link = url_for(
            'task_report_new',
            date=date_s,
            district_id=district_id,
            project_id=project_id,
            _external=True,
        )
    except Exception:
        pass
    if driver:
        _notify_driver_user(driver, driver_title, driver_msg, link=link)
    _notify_dtos(district_id, project_id, driver, v_no, dto_title, dto_msg, link=link)


def pk_time_str():
    try:
        from utils import pk_now
        return pk_now().strftime('%I:%M %p')
    except Exception:
        return ''
