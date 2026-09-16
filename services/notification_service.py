"""
Fleet Manager notification service (v2).

- Per-user in-app notifications (target_user_id) + FCM push
- Driver attendance (GPS+Camera) and task report entry events
- DTO recipients matched by vehicle district + project assignments
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from sqlalchemy import func

logger = logging.getLogger(__name__)

NOTIFICATIONS_V2_SETTING_KEY = 'notifications_v2_purged'

# Process-lifetime workers (started at boot). Per-request daemon threads are
# dropped by gunicorn gthread after the GPS submit response, so FCM never left.
_fcm_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='fcm-push')


def warmup_fcm_executor():
    """Start pool threads at boot so GPS FCM is not tied to a request thread."""
    _fcm_executor.submit(lambda: None)


def _enqueue_fcm(app_obj, user_id, title, message, link, notification_id, dismiss_reminder_kind):
    def _run():
        ctx = app_obj.app_context() if app_obj is not None else None
        if ctx is not None:
            ctx.push()
        try:
            from push_notifications import send_push
            send_push(
                int(user_id), title, message or '', link=link,
                notification_id=notification_id,
                dismiss_reminder_kind=dismiss_reminder_kind,
            )
        except Exception as exc:
            logger.warning('Deferred FCM failed user %s: %s', user_id, exc)
        finally:
            if ctx is not None:
                ctx.pop()

    try:
        _fcm_executor.submit(_run)
    except Exception:
        logger.warning('FCM executor submit failed user %s; sending inline', user_id)
        _run()


def _invalidate_notif_cache(user_ids):
    try:
        from app import _notif_cache
        for uid in user_ids or []:
            _notif_cache.pop(f'notif_{uid}', None)
    except Exception:
        pass


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


def _unread_read_subq(user_id):
    from sqlalchemy import select
    from models import NotificationRead

    return select(NotificationRead.notification_id).where(NotificationRead.user_id == user_id)


def unread_inbox_for_user(user_id, user_perms=None, is_master=False):
    """
    Unread notifications for this user's inbox — same scope as the bell badge.
    Personal (target_user_id) rows plus permission-based broadcasts not yet read.
    """
    from models import Notification

    if not user_id:
        return []
    user_perms = user_perms if user_perms is not None else set()
    read_subq = _unread_read_subq(user_id)
    personal = (
        Notification.query.filter(
            Notification.target_user_id == user_id,
            ~Notification.id.in_(read_subq),
        )
        .order_by(Notification.created_at.desc())
        .all()
    )
    broadcast = (
        Notification.query.filter(
            Notification.target_user_id.is_(None),
            Notification.required_permission.isnot(None),
            ~Notification.id.in_(read_subq),
        )
        .order_by(Notification.created_at.desc())
        .limit(300)
        .all()
    )
    out = list(personal)
    seen = {n.id for n in out}
    for n in broadcast:
        if n.id in seen:
            continue
        if notification_visible_to_user(n, user_id, user_perms, is_master):
            out.append(n)
            seen.add(n.id)
    out.sort(key=lambda n: n.created_at or datetime.min, reverse=True)
    return out


def count_unread_inbox_for_user(user_id, user_perms=None, is_master=False):
    """Fast unread count aligned with unread_inbox_for_user (badge)."""
    from models import Notification

    if not user_id:
        return 0
    user_perms = user_perms if user_perms is not None else set()
    read_subq = _unread_read_subq(user_id)
    personal = Notification.query.filter(
        Notification.target_user_id == user_id,
        ~Notification.id.in_(read_subq),
    ).count()
    extra = 0
    for n in Notification.query.filter(
        Notification.target_user_id.is_(None),
        Notification.required_permission.isnot(None),
        ~Notification.id.in_(read_subq),
    ).order_by(Notification.created_at.desc()).limit(300):
        if notification_visible_to_user(n, user_id, user_perms, is_master):
            extra += 1
    return personal + extra


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
    from models import Vehicle, db

    v = vehicle
    if not v and driver and getattr(driver, 'vehicle_id', None):
        v = db.session.get(Vehicle, driver.vehicle_id)
    if not v:
        return None, None, ''
    v_no = (v.vehicle_no or '').strip()
    district_id = v.district_id or getattr(driver, 'district_id', None)
    project_id = v.project_id or getattr(driver, 'project_id', None)
    return district_id, project_id, v_no


def notify_user(
    user_id, title, message, *, link=None, link_text=None,
    notification_type='info', push=True, dismiss_reminder_kind=None,
    defer_push=False,
):
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
            if defer_push:
                from flask import current_app
                _enqueue_fcm(
                    current_app._get_current_object(),
                    int(user_id), title, message or '', link, n.id,
                    dismiss_reminder_kind,
                )
            else:
                from push_notifications import send_push
                send_push(
                    int(user_id), title, message or '', link=link, notification_id=n.id,
                    dismiss_reminder_kind=dismiss_reminder_kind,
                )
        except Exception as exc:
            logger.warning('FCM push failed user %s: %s', user_id, exc)
    _invalidate_notif_cache([user_id])
    return n


def _notify_driver_user(
    driver, title, message, link=None, dismiss_reminder_kind=None, defer_push=False,
):
    from push_notifications import get_user_id_for_driver

    uid = get_user_id_for_driver(driver)
    if uid:
        notify_user(
            uid, title, message, link=link, notification_type='success',
            dismiss_reminder_kind=dismiss_reminder_kind, defer_push=defer_push,
        )
    else:
        logger.info(
            'Driver notify skipped: no linked user for driver=%s',
            getattr(driver, 'id', None),
        )


def _notify_dtos(
    district_id, project_id, driver, vehicle_no, title, message, link=None,
    defer_push=False,
):
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
        notify_user(
            uid, title, body, link=link, notification_type='info',
            defer_push=defer_push,
        )


ATTENDANCE_CHECKIN_REMINDER_TITLE = 'Check-in reminder'
ATTENDANCE_CHECKOUT_REMINDER_TITLE = 'Check-out reminder'


def mark_unread_titles_read(user_id, titles, *, older_than=None):
    """
    Mark this user's unread notifications with any of `titles` as read.

    A notification nobody ever reads keeps showing in the inbox forever and is
    re-delivered to the tray by the app's polling fallback, so whatever made a
    notification obsolete (check-in done, document renewed) must retire it here.

    older_than: only retire notifications created strictly before this datetime.
    Returns the number newly marked read.
    """
    from models import db, Notification, NotificationRead
    from utils import pk_now

    wanted = [t for t in (titles or []) if t]
    if not user_id or not wanted:
        return 0

    uid = int(user_id)
    read_subq = _unread_read_subq(uid)
    query = Notification.query.filter(
        Notification.target_user_id == uid,
        Notification.title.in_(wanted),
        ~Notification.id.in_(read_subq),
    )
    if older_than is not None:
        query = query.filter(Notification.created_at < older_than)
    unread = query.all()
    if not unread:
        return 0

    now = pk_now()
    marked = 0
    for n in unread:
        existing = NotificationRead.query.filter_by(
            notification_id=n.id, user_id=uid
        ).first()
        if existing:
            existing.read_at = now
        else:
            db.session.add(
                NotificationRead(notification_id=n.id, user_id=uid, read_at=now)
            )
            marked += 1
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning(
            'mark_unread_titles_read failed user=%s titles=%s: %s',
            uid, wanted, exc,
        )
        return 0
    _invalidate_notif_cache([uid])
    return marked


def retire_stale_notifications(titles, older_than, *, limit=20000):
    """
    Mark every user's unread notifications with these titles as read once they
    are older than `older_than`, in one statement.

    Reminders that nobody read stay "pending" forever: the inbox keeps showing
    them and the app's polling fallback can replay them to the tray. A reminder
    is only meaningful inside its own shift window, so retire the rest.
    Returns the number of rows retired.
    """
    from sqlalchemy import exists, insert, literal, select

    from models import db, Notification, NotificationRead
    from utils import pk_now

    wanted = [t for t in (titles or []) if t]
    if not wanted or older_than is None:
        return 0

    notif_t = Notification.__table__
    read_t = NotificationRead.__table__
    unread_stale = (
        notif_t.c.title.in_(wanted),
        notif_t.c.target_user_id.isnot(None),
        notif_t.c.created_at < older_than,
        ~exists(
            select(read_t.c.notification_id).where(
                (read_t.c.notification_id == notif_t.c.id)
                & (read_t.c.user_id == notif_t.c.target_user_id)
            )
        ),
    )

    try:
        affected_users = [
            row[0] for row in db.session.execute(
                select(notif_t.c.target_user_id).where(*unread_stale).distinct()
            )
        ]
        if not affected_users:
            return 0
        now = pk_now()
        source = (
            select(notif_t.c.id, notif_t.c.target_user_id, literal(now))
            .where(*unread_stale)
            .limit(limit)
        )
        result = db.session.execute(
            insert(read_t).from_select(
                ['notification_id', 'user_id', 'read_at'], source
            )
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning('retire_stale_notifications failed titles=%s: %s', wanted, exc)
        return 0

    _invalidate_notif_cache(affected_users)
    return int(result.rowcount or 0)


def dismiss_driver_attendance_reminders(driver, kind):
    """
    After a successful GPS/manual check-in or check-out, mark that driver's
    unread matching reminder notifications as read so the inbox/tray no longer
    shows a stale "pending" message.
    kind: 'checkin' | 'checkout'
    Returns number of reminders newly marked read.
    """
    from push_notifications import get_user_id_for_driver

    if not driver:
        return 0
    kind_l = (kind or '').strip().lower()
    if kind_l in ('checkin', 'check-in', 'in'):
        title = ATTENDANCE_CHECKIN_REMINDER_TITLE
    elif kind_l in ('checkout', 'check-out', 'out'):
        title = ATTENDANCE_CHECKOUT_REMINDER_TITLE
    else:
        return 0

    uid = get_user_id_for_driver(driver)
    if not uid:
        return 0
    return mark_unread_titles_read(uid, [title])


def notify_gps_checkin(driver, photo_path, *, vehicle=None, defer_push=True):
    """After GPS+Camera check-in. In-app row is created now; FCM can be queued."""
    from models import AttendanceSettings

    # Always clear stale pending reminders, even if success push is skipped.
    try:
        dismiss_driver_attendance_reminders(driver, 'checkin')
    except Exception as exc:
        logger.warning('dismiss check-in reminders after GPS check-in: %s', exc)

    if not driver:
        logger.info('GPS check-in notify skipped: no driver')
        return
    att = AttendanceSettings.query.first()
    if not att or not att.notify_on_attendance_mark:
        logger.info('GPS check-in notify skipped: notify_on_attendance_mark off')
        return
    district_id, project_id, v_no = _vehicle_scope_from_driver(driver, vehicle)
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
    _notify_driver_user(
        driver, driver_title, driver_msg, link=link, dismiss_reminder_kind='checkin',
        defer_push=defer_push,
    )
    if district_id and project_id:
        _notify_dtos(
            district_id, project_id, driver, v_no, dto_title, dto_msg, link=link,
            defer_push=defer_push,
        )
    else:
        logger.info(
            'GPS check-in DTO notify skipped: missing district/project driver=%s',
            getattr(driver, 'id', None),
        )


def notify_gps_checkout(driver, photo_path, *, vehicle=None, defer_push=True):
    """After GPS+Camera check-out. In-app row is created now; FCM can be queued."""
    from models import AttendanceSettings

    # Always clear stale pending reminders, even if success push is skipped.
    try:
        dismiss_driver_attendance_reminders(driver, 'checkout')
    except Exception as exc:
        logger.warning('dismiss check-out reminders after GPS check-out: %s', exc)

    if not driver:
        logger.info('GPS check-out notify skipped: no driver')
        return
    att = AttendanceSettings.query.first()
    if not att or not att.notify_on_attendance_mark:
        logger.info('GPS check-out notify skipped: notify_on_attendance_mark off')
        return
    district_id, project_id, v_no = _vehicle_scope_from_driver(driver, vehicle)
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
    _notify_driver_user(
        driver, driver_title, driver_msg, link=link, dismiss_reminder_kind='checkout',
        defer_push=defer_push,
    )
    if district_id and project_id:
        _notify_dtos(
            district_id, project_id, driver, v_no, dto_title, dto_msg, link=link,
            defer_push=defer_push,
        )
    else:
        logger.info(
            'GPS check-out DTO notify skipped: missing district/project driver=%s',
            getattr(driver, 'id', None),
        )
    try:
        from attendance_reminder_service import notify_vehicle_peers_after_checkout
        notify_vehicle_peers_after_checkout(driver, vehicle=vehicle)
    except Exception as exc:
        logger.warning('notify_vehicle_peers_after_checkout: %s', exc)


def notify_task_report_saved(
    vehicle, task_date, *, driver=None,
    close_reading=None, tasks_count=None,
    district_id=None, project_id=None, defer_push=True,
):
    """After New Task Entry save for a vehicle (Close reading / Tasks)."""
    from models import Driver, db

    if not vehicle:
        logger.info('Task report notify skipped: no vehicle')
        return
    district_id = district_id or getattr(vehicle, 'district_id', None)
    project_id = project_id or getattr(vehicle, 'project_id', None)
    v_no = (vehicle.vehicle_no or '').strip()
    date_s = task_date.strftime('%d-%m-%Y') if task_date else ''
    extras = []
    if close_reading is not None and close_reading != '':
        extras.append('Close: %s' % close_reading)
    if tasks_count is not None and tasks_count != '':
        extras.append('Tasks: %s' % tasks_count)
    extra_s = ' | '.join(extras)
    driver_title = 'Task Report Saved'
    driver_msg = (
        f'Aap ki vehicle {v_no} ki task report {date_s} par save ho gayi hai.'
    )
    if extra_s:
        driver_msg = f'{driver_msg} {extra_s}.'
    dto_title = 'Task Report Saved'
    dto_msg = f'Task report save ho gayi ({date_s}).'
    if extra_s:
        dto_msg = f'{dto_msg} {extra_s}.'
    drivers = []
    seen = set()
    if driver and getattr(driver, 'id', None):
        drivers.append(driver)
        seen.add(driver.id)
    if getattr(vehicle, 'driver_id', None) and vehicle.driver_id not in seen:
        assigned = db.session.get(Driver, vehicle.driver_id)
        if assigned:
            drivers.append(assigned)
            seen.add(assigned.id)
    for d in Driver.query.filter_by(vehicle_id=vehicle.id, status='Active').all():
        if d.id not in seen:
            drivers.append(d)
            seen.add(d.id)
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
    for d in drivers:
        _notify_driver_user(
            d, driver_title, driver_msg, link=link, defer_push=defer_push,
        )
    if not drivers:
        logger.info(
            'Task report driver notify skipped: no driver on vehicle=%s',
            getattr(vehicle, 'id', None),
        )
    if district_id and project_id:
        _notify_dtos(
            district_id, project_id,
            drivers[0] if drivers else None,
            v_no, dto_title, dto_msg, link=link, defer_push=defer_push,
        )
    else:
        logger.info(
            'Task report DTO notify skipped: missing district/project vehicle=%s',
            getattr(vehicle, 'id', None),
        )


def pk_time_str():
    try:
        from utils import pk_now
        return pk_now().strftime('%I:%M %p')
    except Exception:
        return ''
