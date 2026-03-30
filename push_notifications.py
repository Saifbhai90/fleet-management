"""
Firebase Cloud Messaging (FCM) push notification utility.
Sends notifications to user devices via Firebase Admin SDK.
"""

import os
import logging

_firebase_app = None
_initialized = False

logger = logging.getLogger(__name__)


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

        sa_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'firebase-service-account.json')

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
    if link:
        payload_data['click_action'] = link
        payload_data['link'] = link

    success_count = 0
    stale_ids = []

    for tok in tokens:
        try:
            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=payload_data,
                token=tok.fcm_token,
                android=messaging.AndroidConfig(
                    priority='high',
                    notification=messaging.AndroidNotification(
                        sound='default',
                        channel_id='fleet_attendance',
                    ),
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
    if link:
        payload_data['click_action'] = link
        payload_data['link'] = link

    success_count = 0
    stale_ids = []

    for tok in tokens:
        try:
            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=payload_data,
                token=tok.fcm_token,
                android=messaging.AndroidConfig(
                    priority='high',
                    notification=messaging.AndroidNotification(
                        sound='default',
                        channel_id='fleet_attendance',
                    ),
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
