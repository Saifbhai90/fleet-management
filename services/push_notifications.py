"""
Firebase Cloud Messaging (FCM) push notification utility.
Sends notifications to user devices via Firebase Admin SDK.
"""

import os
import logging
from datetime import datetime

_firebase_app = None
_initialized = False

logger = logging.getLogger(__name__)

_TASK_POPUP_TITLES = {
    'New Task Generate',
    'Task Complete',
    'Task close karwa dein',
}


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
                'created_at': datetime.utcnow().isoformat(),
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


def send_push(user_id, title, body, data=None, link=None):
    """
    Send push notification to all active devices of a user.
    Bank-app style: works even if the user has no active web/app session,
    because tokens persist across logout. A token is only deactivated when
    a different user logs into the same physical device, or when FCM reports
    the token as unregistered/invalid.
    Returns number of successfully sent messages.
    """
    app = _init_firebase()
    if not app:
        return 0

    from firebase_admin import messaging
    from models import DeviceFCMToken

    tokens = DeviceFCMToken.query.filter_by(user_id=user_id, is_active=True).all()
    if not tokens:
        return 0

    payload_data = dict(data or {})
    popup_link = _build_popup_link(title, body, original_link=link)
    click_link = popup_link or link
    payload_data['popup_mode'] = '1'
    payload_data['title'] = title or ''
    payload_data['body'] = body or ''
    if title in _TASK_POPUP_TITLES:
        payload_data['save_enabled'] = '1'
        payload_data['popup_source'] = 'ufone_task_event'
    else:
        payload_data['save_enabled'] = '0'
        payload_data['popup_source'] = 'generic'
    if click_link:
        payload_data['click_action'] = click_link
        payload_data['link'] = click_link

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
                ),
            )
            messaging.send(message)
            success_count += 1
        except messaging.UnregisteredError:
            stale_ids.append(tok.id)
        except messaging.SenderIdMismatchError:
            stale_ids.append(tok.id)
        except Exception as e:
            logger.warning("FCM send failed for token %s: %s", tok.id, e)

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


def send_push_to_multiple(user_ids, title, body, data=None, link=None):
    """Send the same notification to multiple users. Returns total successes."""
    total = 0
    for uid in user_ids:
        total += send_push(uid, title, body, data=data, link=link)
    return total


def send_push_to_permitted(required_perms, title, body, data=None, link=None):
    """Send push only to users whose role has ANY of the required permission codes.
    required_perms: list of permission code strings (e.g. ['report_expiry', 'reports']).
    Falls back to broadcast_push_all if required_perms is empty/None."""
    if not required_perms:
        return broadcast_push_all(title, body, data=data, link=link)

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

    return send_push_to_multiple(user_ids, title, body, data=data, link=link)


def broadcast_push_all(title, body, data=None, link=None):
    """Broadcast push notification to ALL users with active tokens."""
    app_inst = _init_firebase()
    if not app_inst:
        return 0

    from firebase_admin import messaging
    from models import DeviceFCMToken, db

    tokens = DeviceFCMToken.query.filter_by(is_active=True).all()
    if not tokens:
        return 0

    payload_data = dict(data or {})
    popup_link = _build_popup_link(title, body, original_link=link)
    click_link = popup_link or link
    payload_data['popup_mode'] = '1'
    payload_data['title'] = title or ''
    payload_data['body'] = body or ''
    if title in _TASK_POPUP_TITLES:
        payload_data['save_enabled'] = '1'
        payload_data['popup_source'] = 'ufone_task_event'
    else:
        payload_data['save_enabled'] = '0'
        payload_data['popup_source'] = 'generic'
    if click_link:
        payload_data['click_action'] = click_link
        payload_data['link'] = click_link

    success_count = 0
    stale_ids = []

    for tok in tokens:
        try:
            # Keep Android pushes data-only so FleetFirebaseMessagingService
            # always creates the notification with our popup pending intent.
            message = messaging.Message(
                data=payload_data,
                token=tok.fcm_token,
                android=messaging.AndroidConfig(
                    priority='high',
                ),
            )
            messaging.send(message)
            success_count += 1
        except messaging.UnregisteredError:
            stale_ids.append(tok.id)
        except messaging.SenderIdMismatchError:
            stale_ids.append(tok.id)
        except Exception as e:
            logger.warning("FCM broadcast failed for token %s: %s", tok.id, e)

    if stale_ids:
        try:
            DeviceFCMToken.query.filter(DeviceFCMToken.id.in_(stale_ids)).update(
                {DeviceFCMToken.is_active: False}, synchronize_session=False
            )
            db.session.commit()
        except Exception:
            pass

    return success_count


def get_user_id_for_driver(driver):
    """Find user_id for a driver (linked by cnic_no == username)."""
    if not driver or not driver.cnic_no:
        return None
    from models import User
    user = User.query.filter_by(username=driver.cnic_no, is_active=True).first()
    return user.id if user else None


def notify_driver(driver, title, body, data=None, link=None):
    """Send push notification to a driver's linked user account."""
    uid = get_user_id_for_driver(driver)
    if uid:
        return send_push(uid, title, body, data=data, link=link)
    return 0
