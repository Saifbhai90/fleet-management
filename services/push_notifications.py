"""
Firebase Cloud Messaging (FCM) push notification utility.
Sends notifications to user devices via Firebase Admin SDK.
"""

import os
import logging
import time as _time
from datetime import datetime, timedelta

_firebase_app = None
_initialized = False

logger = logging.getLogger(__name__)

_TASK_POPUP_TITLES = {
    'New Task Generate',
    'Task Complete',
    'Task close karwa dein',
}

_BODY_PREVIEW_LEN = 200
_TOKEN_PREFIX_LEN = 16

# Attendance reminders are the only pushes that go stale: once the driver has
# checked in / out, an old "pending" message is wrong. FCM keeps undelivered
# data messages for up to 4 weeks by default, so a dozed phone can surface a
# morning reminder at night. TTL + collapse key keep at most one live reminder
# per kind, and it expires within the reminder cycle.
_REMINDER_KIND_BY_TITLE = {
    'Check-in reminder': 'checkin',
    'Check-out reminder': 'checkout',
}
REMINDER_TTL_SECONDS = 45 * 60
DISMISS_REMINDER_LOG_TITLE = 'Reminder auto-clear'


def reminder_kind_for_title(title):
    return _REMINDER_KIND_BY_TITLE.get((title or '').strip())


def _reminder_collapse_key(kind):
    return f'attendance_{kind}_reminder'


def _notify_created_at_pkt() -> str:
    """Wall-clock Pakistan time for popup 'Received' (matches Task CreateDateTime TZ).

    Historical bug: UTC wall clock was shown without conversion, so Received
    looked ~5h earlier than Ufone CreateDateTime (PKT) — even when the push
    actually went out after task create.
    """
    try:
        from utils import pk_now
        return pk_now().strftime('%Y-%m-%d %H:%M')
    except Exception:
        from datetime import timedelta
        return (datetime.utcnow() + timedelta(hours=5)).strftime('%Y-%m-%d %H:%M')


def _build_popup_link(title, body, *, notification_type='info', original_link=None):
    """Create a signed short-lived popup link for Android notification taps."""
    try:
        from flask import current_app
        from utils import make_notification_popup_token
    except Exception:
        return None
    try:
        token = make_notification_popup_token(
            current_app.config['SECRET_KEY'],
            {
                'title': title,
                'message': body,
                'type': notification_type or 'info',
                'source': 'ufone_task_event' if title in _TASK_POPUP_TITLES else 'generic',
                'save_enabled': title in _TASK_POPUP_TITLES,
                'created_at': _notify_created_at_pkt(),
                'original_link': original_link or '',
            },
        )
        return f'/notification-popup?t={token}'
    except Exception as exc:
        logger.warning('popup link build failed: %s', exc)
        return None


def _init_firebase():
    """Lazy-initialize Firebase Admin SDK from service account JSON file or env var."""
    global _firebase_app, _initialized
    if _initialized:
        return _firebase_app

    _initialized = True
    try:
        import firebase_admin
        from firebase_admin import credentials
        import json

        sa_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'firebase-service-account.json')

        if os.path.exists(sa_path):
            cred = credentials.Certificate(sa_path)
        elif os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON'):
            sa_dict = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT_JSON'])
            cred = credentials.Certificate(sa_dict)
        else:
            logger.warning("Firebase credentials not found (no file or FIREBASE_SERVICE_ACCOUNT_JSON env var) — push notifications disabled.")
            return None

        _firebase_app = firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin SDK initialized successfully.")
        return _firebase_app
    except Exception as e:
        logger.error("Firebase init failed: %s", e)
        return None


def _token_prefix(fcm_token):
    if not fcm_token:
        return None
    s = str(fcm_token)
    return s[:_TOKEN_PREFIX_LEN] if len(s) > _TOKEN_PREFIX_LEN else s


def _body_preview(body):
    if body is None:
        return None
    s = str(body)
    return s[:_BODY_PREVIEW_LEN] if len(s) > _BODY_PREVIEW_LEN else s


def _log_delivery(
    *,
    user_id,
    notification_id=None,
    device_token=None,
    title=None,
    body=None,
    channel='fcm',
    status='skipped',
    error_code=None,
    remarks=None,
    fcm_message_id=None,
):
    """Persist one delivery attempt. Never raises — must not break push."""
    if not user_id:
        return
    try:
        from models import db, NotificationDeliveryLog
        from utils import pk_now

        tok_id = None
        device_uid = None
        prefix = None
        if device_token is not None:
            tok_id = getattr(device_token, 'id', None)
            device_uid = getattr(device_token, 'device_unique_id', None)
            prefix = _token_prefix(getattr(device_token, 'fcm_token', None))

        row = NotificationDeliveryLog(
            created_at=pk_now(),
            notification_id=int(notification_id) if notification_id else None,
            user_id=int(user_id),
            device_fcm_token_id=tok_id,
            device_unique_id=device_uid,
            fcm_token_prefix=prefix,
            title=(str(title)[:200] if title else None),
            body_preview=_body_preview(body),
            channel=channel or 'none',
            status=status,
            error_code=error_code,
            remarks=(str(remarks)[:500] if remarks else None),
            fcm_message_id=(str(fcm_message_id)[:200] if fcm_message_id else None),
        )
        db.session.add(row)
        db.session.commit()
    except Exception as exc:
        logger.warning('notification_delivery_log write failed: %s', exc)
        try:
            from models import db
            db.session.rollback()
        except Exception:
            pass


def _build_payload_data(title, body, data=None, link=None):
    payload_data = dict(data or {})
    popup_link = _build_popup_link(title, body, original_link=link)
    click_link = popup_link or link
    payload_data['popup_mode'] = '1'
    payload_data['title'] = title or ''
    payload_data['body'] = body or ''
    payload_data['created_at'] = _notify_created_at_pkt()
    if title in _TASK_POPUP_TITLES:
        payload_data['save_enabled'] = '1'
        payload_data['popup_source'] = 'ufone_task_event'
    else:
        payload_data['save_enabled'] = '0'
        payload_data['popup_source'] = 'generic'
    if click_link:
        payload_data['click_action'] = click_link
        payload_data['link'] = click_link
    kind = reminder_kind_for_title(title)
    if kind:
        payload_data['reminder_kind'] = kind
        # Belt-and-braces for devices whose FCM ignores TTL: the app drops
        # reminders it receives after this instant.
        payload_data['valid_until'] = str(int(_time.time()) + REMINDER_TTL_SECONDS)
    return payload_data


def _send_to_tokens(
    tokens, title, body, payload_data, *,
    notification_id=None, ttl_seconds=None, collapse_key=None,
):
    """Send to a list of DeviceFCMToken rows; log each outcome. Returns success count."""
    from firebase_admin import messaging
    from models import DeviceFCMToken

    success_count = 0
    stale_ids = []

    for tok in tokens:
        try:
            # Data-only FCM is required for Android custom tap handling.
            # If we send a top-level notification payload, Android may let the
            # system build the tray notification itself when the app is in the
            # background/killed state, which bypasses our native pending intent
            # and reopens the default launcher/login flow instead of popup mode.
            message = messaging.Message(
                data=payload_data,
                token=tok.fcm_token,
                android=messaging.AndroidConfig(
                    priority='high',
                    ttl=timedelta(seconds=ttl_seconds) if ttl_seconds else None,
                    collapse_key=collapse_key,
                ),
            )
            msg_id = messaging.send(message)
            success_count += 1
            _log_delivery(
                user_id=tok.user_id,
                notification_id=notification_id,
                device_token=tok,
                title=title,
                body=body,
                channel='fcm',
                status='sent',
                remarks='Delivered to FCM',
                fcm_message_id=msg_id,
            )
        except messaging.UnregisteredError:
            stale_ids.append(tok.id)
            _log_delivery(
                user_id=tok.user_id,
                notification_id=notification_id,
                device_token=tok,
                title=title,
                body=body,
                channel='fcm',
                status='failed',
                error_code='UNREGISTERED',
                remarks='Token invalid; deactivated',
            )
        except messaging.SenderIdMismatchError:
            stale_ids.append(tok.id)
            _log_delivery(
                user_id=tok.user_id,
                notification_id=notification_id,
                device_token=tok,
                title=title,
                body=body,
                channel='fcm',
                status='failed',
                error_code='SENDER_MISMATCH',
                remarks='FCM sender ID mismatch; deactivated',
            )
        except Exception as e:
            logger.warning("FCM send failed for token %s: %s", tok.id, e)
            _log_delivery(
                user_id=tok.user_id,
                notification_id=notification_id,
                device_token=tok,
                title=title,
                body=body,
                channel='fcm',
                status='failed',
                error_code='FCM_ERROR',
                remarks=str(e)[:500],
            )

    if stale_ids:
        try:
            from models import db
            DeviceFCMToken.query.filter(DeviceFCMToken.id.in_(stale_ids)).update(
                {DeviceFCMToken.is_active: False}, synchronize_session=False
            )
            db.session.commit()
        except Exception:
            pass

    return success_count


def send_push(user_id, title, body, data=None, link=None, notification_id=None):
    """
    Send push notification to all active devices of a user.
    Bank-app style: works even if the user has no active web/app session,
    because tokens persist across logout. A token is only deactivated when
    a different user logs into the same physical device, or when FCM reports
    the token as unregistered/invalid.
    Returns number of successfully sent messages.
    """
    if not user_id:
        return 0

    app = _init_firebase()
    if not app:
        _log_delivery(
            user_id=user_id,
            notification_id=notification_id,
            title=title,
            body=body,
            channel='none',
            status='skipped',
            error_code='NO_FIREBASE',
            remarks='Firebase not configured',
        )
        return 0

    from models import DeviceFCMToken

    tokens = DeviceFCMToken.query.filter_by(user_id=user_id, is_active=True).all()
    if not tokens:
        _log_delivery(
            user_id=user_id,
            notification_id=notification_id,
            title=title,
            body=body,
            channel='none',
            status='skipped',
            error_code='NO_TOKEN',
            remarks='No active FCM token for user',
        )
        return 0

    payload_data = _build_payload_data(title, body, data=data, link=link)
    kind = reminder_kind_for_title(title)
    return _send_to_tokens(
        tokens, title, body, payload_data,
        notification_id=notification_id,
        ttl_seconds=REMINDER_TTL_SECONDS if kind else None,
        collapse_key=_reminder_collapse_key(kind) if kind else None,
    )


def send_reminder_dismiss_push(user_id, kind):
    """
    Silently clear an attendance reminder from the device tray after the driver
    has actually checked in / out. Shares the reminder's collapse key, so a
    reminder still queued at FCM (undelivered phone) is replaced by this
    dismissal instead of arriving late.
    """
    if not user_id or kind not in ('checkin', 'checkout'):
        return 0
    if not _init_firebase():
        return 0

    from models import DeviceFCMToken

    tokens = DeviceFCMToken.query.filter_by(user_id=user_id, is_active=True).all()
    if not tokens:
        return 0

    payload_data = {
        'fleet_action': 'dismiss_reminder',
        'reminder_kind': kind,
        'created_at': _notify_created_at_pkt(),
    }
    return _send_to_tokens(
        tokens,
        DISMISS_REMINDER_LOG_TITLE,
        f'{kind} reminder cleared on device',
        payload_data,
        ttl_seconds=REMINDER_TTL_SECONDS,
        collapse_key=_reminder_collapse_key(kind),
    )


def send_push_to_multiple(user_ids, title, body, data=None, link=None, notification_id=None):
    """Send the same notification to multiple users. Returns total successes."""
    total = 0
    for uid in user_ids:
        total += send_push(uid, title, body, data=data, link=link, notification_id=notification_id)
    return total


def send_push_to_permitted(required_perms, title, body, data=None, link=None, notification_id=None):
    """Send push only to users whose role has ANY of the required permission codes.
    required_perms: list of permission code strings (e.g. ['report_expiry', 'reports']).
    Falls back to broadcast_push_all if required_perms is empty/None."""
    if not required_perms:
        return broadcast_push_all(title, body, data=data, link=link, notification_id=notification_id)

    app = _init_firebase()
    if not app:
        return 0

    from models import User, Role, Permission, role_permissions, DeviceFCMToken, db

    perm_ids = [p.id for p in Permission.query.filter(Permission.code.in_(required_perms)).all()]
    if not perm_ids:
        return 0

    role_ids = db.session.query(role_permissions.c.role_id).filter(
        role_permissions.c.permission_id.in_(perm_ids)
    ).distinct().all()
    role_ids = [r[0] for r in role_ids]
    if not role_ids:
        return 0

    user_ids = [u.id for u in User.query.filter(
        User.role_id.in_(role_ids), User.is_active == True
    ).all()]
    if not user_ids:
        return 0

    return send_push_to_multiple(user_ids, title, body, data=data, link=link, notification_id=notification_id)


def broadcast_push_all(title, body, data=None, link=None, notification_id=None):
    """Broadcast push notification to ALL users with active tokens."""
    app_inst = _init_firebase()
    if not app_inst:
        return 0

    from models import DeviceFCMToken

    tokens = DeviceFCMToken.query.filter_by(is_active=True).all()
    if not tokens:
        return 0

    payload_data = _build_payload_data(title, body, data=data, link=link)
    return _send_to_tokens(tokens, title, body, payload_data, notification_id=notification_id)


def get_user_id_for_driver(driver):
    """Find user_id for a driver (linked by cnic_no == username)."""
    if not driver or not driver.cnic_no:
        return None
    from models import User
    user = User.query.filter_by(username=driver.cnic_no, is_active=True).first()
    return user.id if user else None


def notify_driver(driver, title, body, data=None, link=None, notification_id=None):
    """Send push notification to a driver's linked user account."""
    uid = get_user_id_for_driver(driver)
    if uid:
        return send_push(uid, title, body, data=data, link=link, notification_id=notification_id)
    return 0
