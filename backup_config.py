"""Backup email & schedule settings (SystemSetting with env fallback)."""
import os

PASSWORD_PLACEHOLDER = '••••••••'

_DB_KEYS = {
    'mail_server': 'backup_mail_server',
    'mail_port': 'backup_mail_port',
    'mail_use_tls': 'backup_mail_use_tls',
    'mail_username': 'backup_mail_username',
    'mail_password': 'backup_mail_password',
    'mail_from': 'backup_mail_from',
    'email_to': 'backup_email_to',
    'schedule_enabled': 'backup_schedule_enabled',
    'schedule_time': 'backup_schedule_time',
    'schedule_frequency': 'backup_schedule_frequency',
    'schedule_weekday': 'backup_schedule_weekday',
}

_ENV_MAP = {
    'mail_server': 'MAIL_SERVER',
    'mail_port': 'MAIL_PORT',
    'mail_use_tls': 'MAIL_USE_TLS',
    'mail_username': 'MAIL_USERNAME',
    'mail_password': 'MAIL_PASSWORD',
    'mail_from': 'MAIL_FROM',
    'email_to': 'BACKUP_EMAIL_TO',
    'schedule_enabled': 'BACKUP_SCHEDULE_ENABLED',
    'schedule_time': 'BACKUP_SCHEDULE_TIME',
}

_SCHEDULER = None


def _get_db(key):
    from models import SystemSetting
    return SystemSetting.get(_DB_KEYS[key])


def _set_db(key, value):
    from models import SystemSetting
    SystemSetting.set(_DB_KEYS[key], value)


def _read_field(app, key, default=''):
    db_val = _get_db(key)
    if db_val is not None and str(db_val).strip() != '':
        return str(db_val).strip()
    env_name = _ENV_MAP.get(key)
    if env_name:
        raw = os.environ.get(env_name) or app.config.get(env_name)
        if raw is not None and str(raw).strip() != '':
            return str(raw).strip()
    if key == 'mail_server' and not db_val:
        return default or 'smtp.gmail.com'
    if key == 'mail_port' and not db_val:
        return default or '587'
    if key == 'mail_use_tls' and not db_val:
        return 'true'
    if key == 'schedule_time' and not db_val:
        return default or '02:00'
    if key == 'schedule_frequency' and not db_val:
        return default or 'daily'
    if key == 'schedule_weekday' and not db_val:
        return default or '0'
    return default or ''


def get_backup_settings(app):
    """Settings for Backup page UI (password masked if set)."""
    with app.app_context():
        pwd = _read_field(app, 'mail_password')
        has_pwd = bool(pwd)
        freq = (_read_field(app, 'schedule_frequency') or 'daily').lower()
        if freq not in ('daily', 'weekly', 'twice_daily'):
            freq = 'daily'
        enabled_raw = (_read_field(app, 'schedule_enabled') or '').lower()
        schedule_on = enabled_raw in ('1', 'true', 'yes', 'on')
        if not schedule_on and os.environ.get('BACKUP_SCHEDULE_ENABLED', '').lower() in ('1', 'true', 'yes'):
            schedule_on = True
        return {
            'mail_server': _read_field(app, 'mail_server') or 'smtp.gmail.com',
            'mail_port': _read_field(app, 'mail_port') or '587',
            'mail_use_tls': _read_field(app, 'mail_use_tls', 'true').lower() in ('1', 'true', 'yes'),
            'mail_username': _read_field(app, 'mail_username'),
            'mail_from': _read_field(app, 'mail_from') or _read_field(app, 'mail_username'),
            'mail_password': PASSWORD_PLACEHOLDER if has_pwd else '',
            'mail_password_set': has_pwd,
            'email_to': _read_field(app, 'email_to'),
            'schedule_enabled': schedule_on,
            'schedule_time': _read_field(app, 'schedule_time') or '02:00',
            'schedule_frequency': freq,
            'schedule_weekday': _read_field(app, 'schedule_weekday') or '0',
        }


def apply_backup_config_to_app(app):
    """Apply DB/env backup mail settings to app.config (for send + scheduler)."""
    with app.app_context():
        app.config['MAIL_SERVER'] = _read_field(app, 'mail_server') or 'smtp.gmail.com'
        port = _read_field(app, 'mail_port') or '587'
        app.config['MAIL_PORT'] = port
        app.config['MAIL_USE_TLS'] = _read_field(app, 'mail_use_tls', 'true').lower() in ('1', 'true', 'yes')
        app.config['MAIL_USERNAME'] = _read_field(app, 'mail_username')
        app.config['MAIL_PASSWORD'] = _read_field(app, 'mail_password')
        app.config['MAIL_FROM'] = _read_field(app, 'mail_from') or _read_field(app, 'mail_username')
        app.config['BACKUP_EMAIL_TO'] = _read_field(app, 'email_to')
        enabled_raw = (_read_field(app, 'schedule_enabled') or '').lower()
        app.config['BACKUP_SCHEDULE_ENABLED'] = enabled_raw in ('1', 'true', 'yes', 'on')
        app.config['BACKUP_SCHEDULE_TIME'] = _read_field(app, 'schedule_time') or '02:00'
        app.config['BACKUP_SCHEDULE_FREQUENCY'] = _read_field(app, 'schedule_frequency') or 'daily'
        app.config['BACKUP_SCHEDULE_WEEKDAY'] = _read_field(app, 'schedule_weekday') or '0'


def mail_is_configured(app):
    apply_backup_config_to_app(app)
    return bool(
        (app.config.get('MAIL_USERNAME') or '').strip()
        and (app.config.get('MAIL_PASSWORD') or '').strip()
        and (app.config.get('BACKUP_EMAIL_TO') or '').strip()
    )


def save_backup_settings(app, data):
    """Save settings from form/JSON. Password left blank keeps existing password."""
    with app.app_context():
        mail_server = (data.get('mail_server') or 'smtp.gmail.com').strip()
        mail_port = (data.get('mail_port') or '587').strip()
        mail_use_tls = 'true' if data.get('mail_use_tls') in (True, 'true', '1', 'on', 'yes') else 'false'
        mail_username = (data.get('mail_username') or '').strip()
        mail_from = (data.get('mail_from') or mail_username).strip()
        email_to = (data.get('email_to') or '').strip()
        schedule_time = (data.get('schedule_time') or '02:00').strip()
        schedule_frequency = (data.get('schedule_frequency') or 'daily').strip().lower()
        if schedule_frequency not in ('daily', 'weekly', 'twice_daily'):
            schedule_frequency = 'daily'
        schedule_weekday = str(data.get('schedule_weekday') or '0').strip()
        schedule_enabled = 'true' if data.get('schedule_enabled') in (True, 'true', '1', 'on', 'yes') else 'false'
        new_password = (data.get('mail_password') or '').strip()
        if new_password in (PASSWORD_PLACEHOLDER, '********', ''):
            new_password = ''

        if not mail_username:
            return False, 'Sender Gmail address is required.'
        if not email_to:
            return False, 'Recipient email is required.'
        if not _read_field(app, 'mail_password') and not new_password:
            return False, 'Gmail App Password is required (first-time setup).'

        _set_db('mail_server', mail_server)
        _set_db('mail_port', mail_port)
        _set_db('mail_use_tls', mail_use_tls)
        _set_db('mail_username', mail_username)
        _set_db('mail_from', mail_from)
        _set_db('email_to', email_to)
        _set_db('schedule_enabled', schedule_enabled)
        _set_db('schedule_time', schedule_time)
        _set_db('schedule_frequency', schedule_frequency)
        _set_db('schedule_weekday', schedule_weekday)
        if new_password:
            _set_db('mail_password', new_password)

        apply_backup_config_to_app(app)
        reload_backup_scheduler(app)
        return True, 'Backup email settings saved.'


def _parse_time(time_str):
    parts = (time_str or '02:00').strip().split(':')
    hour = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 2
    minute = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    hour = max(0, min(23, hour))
    minute = max(0, min(59, minute))
    return hour, minute


def reload_backup_scheduler(app):
    """Restart APScheduler jobs from current backup settings."""
    global _SCHEDULER
    try:
        if _SCHEDULER is not None:
            _SCHEDULER.shutdown(wait=False)
    except Exception:
        pass
    _SCHEDULER = None
    start_backup_scheduler(app)


def start_backup_scheduler(app):
    """Start scheduled backup if enabled in settings."""
    global _SCHEDULER
    apply_backup_config_to_app(app)
    if not app.config.get('BACKUP_SCHEDULE_ENABLED'):
        return
    to_email = (app.config.get('BACKUP_EMAIL_TO') or '').strip()
    if not to_email:
        return
    if not (app.config.get('MAIL_USERNAME') and app.config.get('MAIL_PASSWORD')):
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from backup_utils import run_scheduled_backup

        hour, minute = _parse_time(app.config.get('BACKUP_SCHEDULE_TIME'))
        freq = (app.config.get('BACKUP_SCHEDULE_FREQUENCY') or 'daily').lower()
        weekday = int(app.config.get('BACKUP_SCHEDULE_WEEKDAY') or 0)

        _SCHEDULER = BackgroundScheduler()

        if freq == 'weekly':
            _SCHEDULER.add_job(
                lambda: run_scheduled_backup(app),
                'cron',
                day_of_week=weekday,
                hour=hour,
                minute=minute,
                id='fleet_backup',
            )
        elif freq == 'twice_daily':
            hour2 = (hour + 12) % 24
            _SCHEDULER.add_job(
                lambda: run_scheduled_backup(app),
                'cron',
                hour=hour,
                minute=minute,
                id='fleet_backup_am',
            )
            _SCHEDULER.add_job(
                lambda: run_scheduled_backup(app),
                'cron',
                hour=hour2,
                minute=minute,
                id='fleet_backup_pm',
            )
        else:
            _SCHEDULER.add_job(
                lambda: run_scheduled_backup(app),
                'cron',
                hour=hour,
                minute=minute,
                id='fleet_backup',
            )
        _SCHEDULER.start()
        if hasattr(app, 'logger'):
            app.logger.info(
                'Backup scheduler started: %s at %02d:%02d → %s',
                freq, hour, minute, to_email,
            )
    except Exception as e:
        if hasattr(app, 'logger'):
            app.logger.warning('Backup scheduler failed to start: %s', e)
