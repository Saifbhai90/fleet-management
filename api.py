"""
Mobile API Blueprint  —  /api/v1/
JWT-based authentication for mobile app integration.

Endpoints:
  POST /api/v1/login              → returns JWT token
  GET  /api/v1/me                 → driver/user profile
  GET  /api/v1/dashboard/stats    → summary KPIs
  POST /api/v1/attendance/checkin → mark attendance check-in
  POST /api/v1/attendance/checkout→ mark attendance check-out
  GET  /api/v1/drivers            → paginated driver list
  GET  /api/v1/drivers/<id>       → single driver detail
  GET  /api/v1/vehicles           → paginated vehicle list
"""

import os
import jwt
import datetime
from functools import wraps

from flask import Blueprint, request, jsonify, current_app
from werkzeug.security import check_password_hash

api_bp = Blueprint('api', __name__, url_prefix='/api/v1')

JWT_ALGORITHM = 'HS256'
JWT_EXPIRY_HOURS = 24


def _jwt_secret():
    return current_app.config.get('SECRET_KEY', 'changeme')


def _make_token(payload: dict) -> str:
    payload = dict(payload)
    payload['exp'] = datetime.datetime.utcnow() + datetime.timedelta(hours=JWT_EXPIRY_HOURS)
    payload['iat'] = datetime.datetime.utcnow()
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def _decode_token(token: str) -> dict:
    return jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])


def jwt_required(f):
    """Decorator: validates Bearer JWT token in Authorization header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid Authorization header.'}), 401
        token = auth[7:]
        try:
            payload = _decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired. Please login again.'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token.'}), 401
        request.jwt_payload = payload
        return f(*args, **kwargs)
    return decorated


def _err(msg, code=400):
    return jsonify({'success': False, 'error': msg}), code


def _ok(data=None, **kwargs):
    payload = {'success': True}
    if data is not None:
        payload['data'] = data
    payload.update(kwargs)
    return jsonify(payload)


# ── POST /api/v1/login ────────────────────────────────────────────────────────
@api_bp.route('/login', methods=['POST'])
def mobile_login():
    """
    Body: { "username": "CNIC", "password": "..." }
    Returns JWT token on success.
    """
    from models import User
    body = request.get_json(silent=True) or {}
    username = (body.get('username') or '').strip()
    password = (body.get('password') or '').strip()

    if not username or not password:
        return _err('username and password are required.')

    user = User.query.filter_by(username=username, is_active=True).first()
    if not user or not check_password_hash(user.password_hash, password):
        return _err('Invalid credentials.', 401)

    token = _make_token({
        'user_id': user.id,
        'username': user.username,
        'name': user.name or user.username,
        'is_master': user.is_master if hasattr(user, 'is_master') else False,
    })
    return _ok({
        'token': token,
        'user_id': user.id,
        'name': user.name or user.username,
        'expires_in_hours': JWT_EXPIRY_HOURS,
    })


# ── GET /api/v1/me ────────────────────────────────────────────────────────────
@api_bp.route('/me', methods=['GET'])
@jwt_required
def mobile_me():
    """Returns the logged-in user's profile."""
    from models import User, Driver
    uid = request.jwt_payload.get('user_id')
    user = User.query.get(uid)
    if not user:
        return _err('User not found.', 404)
    driver = Driver.query.filter_by(cnic_no=user.username).first()
    return _ok({
        'user_id': user.id,
        'username': user.username,
        'name': user.name or user.username,
        'driver': {
            'id': driver.id,
            'driver_id': driver.driver_id,
            'name': driver.name,
            'phone1': driver.phone1,
            'status': driver.status,
            'vehicle_id': driver.vehicle_id,
        } if driver else None,
    })


# ── GET /api/v1/dashboard/stats ───────────────────────────────────────────────
@api_bp.route('/dashboard/stats', methods=['GET'])
@jwt_required
def mobile_dashboard_stats():
    """Returns KPI summary for mobile dashboard."""
    from models import Driver, Vehicle, DriverAttendance, FuelExpense
    from sqlalchemy import func
    from app import db
    import datetime as dt

    today = dt.date.today()
    active_drivers = Driver.query.filter_by(status='Active').count()
    total_vehicles = Vehicle.query.count()
    assigned_vehicles = Vehicle.query.filter(Vehicle.district_id.isnot(None)).count()
    today_attendance = DriverAttendance.query.filter_by(attendance_date=today).count()

    try:
        from sqlalchemy import extract
        monthly_fuel = db.session.query(func.sum(FuelExpense.amount)).filter(
            extract('month', FuelExpense.fueling_date) == today.month,
            extract('year', FuelExpense.fueling_date) == today.year
        ).scalar() or 0
    except Exception:
        monthly_fuel = 0

    return _ok({
        'active_drivers': active_drivers,
        'total_vehicles': total_vehicles,
        'assigned_vehicles': assigned_vehicles,
        'today_attendance': today_attendance,
        'monthly_fuel_cost': float(monthly_fuel),
        'as_of': today.isoformat(),
    })


def _save_base64_photo(b64_string: str, folder: str = 'attendance') -> str:
    """Decode base64 image, upload to R2 (or save locally as fallback). Returns URL/path."""
    import base64
    import re
    # Strip data-URL prefix if present: data:image/jpeg;base64,<data>
    match = re.match(r'data:image/[^;]+;base64,(.+)', b64_string, re.DOTALL)
    raw_b64 = match.group(1) if match else b64_string
    try:
        image_bytes = base64.b64decode(raw_b64)
    except Exception:
        return ''
    try:
        from r2_storage import upload_image_bytes
        return upload_image_bytes(image_bytes, folder=folder)
    except Exception:
        # Fallback: save locally under uploads/
        import uuid, os
        upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads', folder)
        os.makedirs(upload_dir, exist_ok=True)
        fname = uuid.uuid4().hex + '.jpg'
        fpath = os.path.join(upload_dir, fname)
        with open(fpath, 'wb') as f:
            f.write(image_bytes)
        return f'/uploads/{folder}/{fname}'


# ── POST /api/v1/attendance/checkin ──────────────────────────────────────────
@api_bp.route('/attendance/checkin', methods=['POST'])
@jwt_required
def mobile_checkin():
    """
    Body: { "driver_id": 5, "latitude": 31.5, "longitude": 74.3, "photo_base64": "..." }
    """
    from models import Driver, DriverAttendance
    from app import db
    import datetime as dt

    body = request.get_json(silent=True) or {}
    driver_id = body.get('driver_id')
    lat = body.get('latitude')
    lng = body.get('longitude')
    photo_b64 = body.get('photo_base64', '')

    if not driver_id:
        return _err('driver_id is required.')

    driver = Driver.query.get(driver_id)
    if not driver:
        return _err('Driver not found.', 404)

    today = dt.date.today()
    now_utc = dt.datetime.utcnow()

    existing = DriverAttendance.query.filter_by(
        driver_id=driver.id, attendance_date=today
    ).first()
    if existing and existing.check_in:
        return _err('Already checked in today.')

    photo_url = _save_base64_photo(photo_b64, 'attendance') if photo_b64 else None

    try:
        if existing:
            existing.check_in = now_utc.time()
            existing.check_in_latitude = lat
            existing.check_in_longitude = lng
            if photo_url:
                existing.check_in_photo_path = photo_url
            record = existing
        else:
            record = DriverAttendance(
                driver_id=driver.id,
                attendance_date=today,
                check_in=now_utc.time(),
                check_in_latitude=lat,
                check_in_longitude=lng,
                check_in_photo_path=photo_url,
                status='Present',
            )
            db.session.add(record)
        db.session.commit()
        return _ok({'message': f'Check-in recorded for {driver.name}', 'time': str(now_utc.time())[:5]})
    except Exception as e:
        db.session.rollback()
        return _err(f'Error: {str(e)}')


# ── POST /api/v1/attendance/checkout ─────────────────────────────────────────
@api_bp.route('/attendance/checkout', methods=['POST'])
@jwt_required
def mobile_checkout():
    """
    Body: { "driver_id": 5, "latitude": 31.5, "longitude": 74.3, "photo_base64": "..." }
    """
    from models import Driver, DriverAttendance
    from app import db
    import datetime as dt

    body = request.get_json(silent=True) or {}
    driver_id = body.get('driver_id')
    lat = body.get('latitude')
    lng = body.get('longitude')
    photo_b64 = body.get('photo_base64', '')

    if not driver_id:
        return _err('driver_id is required.')

    driver = Driver.query.get(driver_id)
    if not driver:
        return _err('Driver not found.', 404)

    today = dt.date.today()
    now_utc = dt.datetime.utcnow()

    record = DriverAttendance.query.filter_by(
        driver_id=driver.id, attendance_date=today
    ).first()
    if not record or not record.check_in:
        return _err('No check-in found for today. Please check in first.')
    if record.check_out:
        return _err('Already checked out today.')

    photo_url = _save_base64_photo(photo_b64, 'attendance') if photo_b64 else None

    try:
        record.check_out = now_utc.time()
        record.check_out_latitude = lat
        record.check_out_longitude = lng
        if photo_url:
            record.check_out_photo_path = photo_url
        db.session.commit()
        return _ok({'message': f'Check-out recorded for {driver.name}', 'time': str(now_utc.time())[:5]})
    except Exception as e:
        db.session.rollback()
        return _err(f'Error: {str(e)}')


# ── GET /api/v1/driver/profile ───────────────────────────────────────────────
@api_bp.route('/driver/profile', methods=['GET'])
@jwt_required
def mobile_driver_profile():
    """Full driver profile for current user or ?driver_id=X for admins."""
    from models import User, Driver, DriverAttendance
    import datetime as dt

    uid = request.jwt_payload.get('user_id')
    user = User.query.get(uid)
    if not user:
        return _err('User not found.', 404)

    driver_id_param = request.args.get('driver_id', type=int)
    is_master = request.jwt_payload.get('is_master', False)

    if driver_id_param and is_master:
        driver = Driver.query.get(driver_id_param)
    else:
        driver = Driver.query.filter_by(cnic_no=user.username).first()

    if not driver:
        return _err('Driver profile not found for this user.', 404)

    today = dt.date.today()
    attendance_today = DriverAttendance.query.filter_by(
        driver_id=driver.id, attendance_date=today
    ).first()

    return _ok({
        'driver_id': driver.driver_id,
        'name': driver.name,
        'father_name': driver.father_name,
        'cnic_no': driver.cnic_no,
        'phone1': driver.phone1,
        'phone2': driver.phone2,
        'status': driver.status,
        'shift': driver.shift,
        'license_no': driver.license_no,
        'license_type': driver.license_type,
        'license_expiry': driver.license_expiry_date.isoformat() if driver.license_expiry_date else None,
        'cnic_expiry': driver.cnic_expiry_date.isoformat() if driver.cnic_expiry_date else None,
        'district': driver.driver_district,
        'vehicle_id': driver.vehicle_id,
        'photo_url': driver.photo_url if hasattr(driver, 'photo_url') else None,
        'today_attendance': {
            'checked_in': bool(attendance_today and attendance_today.check_in),
            'checked_out': bool(attendance_today and attendance_today.check_out),
            'check_in_time': str(attendance_today.check_in)[:5] if attendance_today and attendance_today.check_in else None,
            'check_out_time': str(attendance_today.check_out)[:5] if attendance_today and attendance_today.check_out else None,
            'status': attendance_today.status if attendance_today else None,
        } if attendance_today else None,
    })


# ── GET /api/v1/notifications ─────────────────────────────────────────────────
@api_bp.route('/notifications', methods=['GET'])
@jwt_required
def mobile_notifications():
    """Returns unread notifications for the current user."""
    from models import Notification, NotificationRead
    from app import db

    uid = request.jwt_payload.get('user_id')
    read_ids = {r.notification_id for r in NotificationRead.query.filter_by(user_id=uid).all()}
    notifications = Notification.query.order_by(Notification.created_at.desc()).limit(50).all()

    return _ok([{
        'id': n.id,
        'title': n.title,
        'message': n.message,
        'type': n.notification_type,
        'link': n.link,
        'is_read': n.id in read_ids,
        'created_at': n.created_at.isoformat() if n.created_at else None,
    } for n in notifications])


# ── GET /api/v1/drivers ───────────────────────────────────────────────────────
@api_bp.route('/drivers', methods=['GET'])
@jwt_required
def mobile_drivers():
    """Paginated driver list. Query params: ?page=1&per_page=20&search=name"""
    from models import Driver

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    search = request.args.get('search', '').strip()

    q = Driver.query
    if search:
        like = f'%{search}%'
        q = q.filter(
            Driver.name.ilike(like) |
            Driver.driver_id.ilike(like) |
            Driver.cnic_no.ilike(like)
        )
    pagination = q.order_by(Driver.name).paginate(page=page, per_page=per_page, error_out=False)
    return _ok(
        [{'id': d.id, 'driver_id': d.driver_id, 'name': d.name,
          'status': d.status, 'phone': d.phone1, 'cnic': d.cnic_no}
         for d in pagination.items],
        total=pagination.total,
        page=pagination.page,
        pages=pagination.pages,
    )


# ── GET /api/v1/drivers/<id> ──────────────────────────────────────────────────
@api_bp.route('/drivers/<int:driver_id>', methods=['GET'])
@jwt_required
def mobile_driver_detail(driver_id):
    """Single driver detail."""
    from models import Driver
    d = Driver.query.get_or_404(driver_id)
    return _ok({
        'id': d.id,
        'driver_id': d.driver_id,
        'name': d.name,
        'father_name': d.father_name,
        'cnic_no': d.cnic_no,
        'phone1': d.phone1,
        'phone2': d.phone2,
        'status': d.status,
        'license_no': d.license_no,
        'license_type': d.license_type,
        'vehicle_id': d.vehicle_id,
        'shift': d.shift,
        'district': d.driver_district,
    })


# ── GET /api/v1/vehicles ──────────────────────────────────────────────────────
@api_bp.route('/vehicles', methods=['GET'])
@jwt_required
def mobile_vehicles():
    """Paginated vehicle list. Query params: ?page=1&per_page=20&search=vehicle_no"""
    from models import Vehicle

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    search = request.args.get('search', '').strip()

    q = Vehicle.query
    if search:
        like = f'%{search}%'
        q = q.filter(
            Vehicle.vehicle_no.ilike(like) |
            Vehicle.model.ilike(like)
        )
    pagination = q.order_by(Vehicle.vehicle_no).paginate(page=page, per_page=per_page, error_out=False)
    return _ok(
        [{'id': v.id, 'vehicle_no': v.vehicle_no, 'model': v.model,
          'vehicle_type': v.vehicle_type, 'district_id': v.district_id,
          'parking_station_id': v.parking_station_id}
         for v in pagination.items],
        total=pagination.total,
        page=pagination.page,
        pages=pagination.pages,
    )
