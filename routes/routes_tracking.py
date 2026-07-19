"""
PortalXS Fleet Tracking Portal Routes
======================================
Live tracking dashboard, vehicle detail, history playback, trips,
fleet reports, trends, alerts, and settings.

Integrates with PortalXS SOAP API via services/portalxs_service.py.
"""
from flask import (
    render_template, redirect, url_for, flash, request,
    session, jsonify, make_response, Response,
)
from app import app, db, csrf
from models import (
    PortalXSAccount, PortalXSVehicleMapping, PortalXSAlertCache,
    Vehicle,
)
from services.portalxs_service import (
    fetch_live_positions, fetch_history, fetch_trips,
    fetch_fleet_report, fetch_trends, fetch_mileage,
    fetch_alerts, fetch_geofences,
    get_cached_positions, get_summary_stats,
    get_all_vehicles_for_account, link_vehicle, auto_link_vehicles,
    create_account, update_account, delete_account,
    test_connection, encrypt_password, decrypt_password,
    start_polling,
)
from utils import pk_now, pk_date
from datetime import datetime, timedelta
import csv
import io
import json

from routes import _nav_back_ctx


# ── Helper: get active account (first active, or by query param) ─────────────

def _sanitize_date(s: str, default: str = None) -> str:
    """Ensure date string is YYYY-MM-DD (strip spaces, validate format)."""
    import re as _re
    if not s or not s.strip():
        return default or pk_date().strftime('%Y-%m-%d')
    s = s.strip()
    if _re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        return s
    # Try to parse and reformat
    try:
        from datetime import datetime as _dt
        return _dt.strptime(s[:10], '%Y-%m-%d').strftime('%Y-%m-%d')
    except Exception:
        return default or pk_date().strftime('%Y-%m-%d')


def _soap_dates(from_date: str, to_date: str) -> tuple:
    """Build SOAP-compatible date range (fdt, tdt) from YYYY-MM-DD inputs."""
    fd = _sanitize_date(from_date)
    td = _sanitize_date(to_date)
    return f"{fd}T00:00:00", f"{td}T23:59:59"


def _get_account_id() -> int:
    """Get the active account ID from query param or first active account."""
    acct_id = request.args.get('account_id', type=int)
    if acct_id:
        return acct_id
    acct = PortalXSAccount.query.filter_by(is_active=True).first()
    if acct:
        return acct.id
    return 0


def _get_all_accounts():
    return PortalXSAccount.query.order_by(PortalXSAccount.label).all()


# ════════════════════════════════════════════════════════════════════════════
# DASHBOARD - Live tracking map
# ════════════════════════════════════════════════════════════════════════════

@app.route('/tracking')
def tracking_dashboard():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    vehicles = []
    stats = {'total': 0, 'moving': 0, 'stopped': 0, 'idle': 0}
    error = None

    if acct_id:
        try:
            vehicles = fetch_live_positions(acct_id, force=False)
            stats = get_summary_stats(acct_id)
        except Exception as e:
            error = str(e)[:300]
    else:
        error = "No PortalXS account configured. Add one in Settings."

    return render_template(
        'tracking/dashboard.html',
        vehicles=vehicles,
        stats=stats,
        accounts=accounts,
        current_account_id=acct_id,
        error=error,
        **_nav_back_ctx(url_for('tracking_dashboard')),
    )


@app.route('/api/tracking/positions')
def api_tracking_positions():
    """API endpoint for auto-refresh: return cached/fresh positions as JSON."""
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account configured', 'vehicles': [], 'stats': {}})
    try:
        vehicles = fetch_live_positions(acct_id, force=False)
        stats = get_summary_stats(acct_id)
        return jsonify({'vehicles': vehicles, 'stats': stats, 'account_id': acct_id})
    except Exception as e:
        return jsonify({'error': str(e)[:300], 'vehicles': [], 'stats': {}}), 200


@app.route('/api/tracking/refresh', methods=['POST'])
def api_tracking_refresh():
    """Force refresh positions from PortalXS."""
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account configured'}), 400
    try:
        vehicles = fetch_live_positions(acct_id, force=True)
        stats = get_summary_stats(acct_id)
        return jsonify({'vehicles': vehicles, 'stats': stats, 'refreshed_at': pk_now().isoformat()})
    except Exception as e:
        return jsonify({'error': str(e)[:300]}), 500


# ════════════════════════════════════════════════════════════════════════════
# VEHICLE DETAIL
# ════════════════════════════════════════════════════════════════════════════

@app.route('/tracking/vehicle/<regno>')
def tracking_vehicle_detail(regno):
    acct_id = _get_account_id()
    if not acct_id:
        flash("No PortalXS account configured.", "danger")
        return redirect(url_for('tracking_dashboard'))

    vehicles = get_cached_positions(acct_id)
    vehicle = next((v for v in vehicles if v.get('RegNo') == regno), None)

    if not vehicle:
        try:
            vehicles = fetch_live_positions(acct_id, force=True)
            vehicle = next((v for v in vehicles if v.get('RegNo') == regno), None)
        except Exception as e:
            flash(f"Error fetching vehicle: {e}", "danger")
            return redirect(url_for('tracking_dashboard'))

    if not vehicle:
        flash(f"Vehicle {regno} not found.", "warning")
        return redirect(url_for('tracking_dashboard'))

    # Get today's trips summary
    today = pk_date()
    fdt = today.strftime('%Y-%m-%dT00:00:00')
    tdt = today.strftime('%Y-%m-%dT23:59:59')
    today_trips = []
    today_mileage = {}
    try:
        today_trips = fetch_trips(acct_id, regno, fdt, tdt)
    except Exception:
        pass
    try:
        today_mileage = fetch_mileage(acct_id, regno, fdt, tdt)
    except Exception:
        pass

    # Find internal vehicle mapping
    mapping = PortalXSVehicleMapping.query.filter_by(
        account_id=acct_id, portalxs_regno=regno
    ).first()

    return render_template(
        'tracking/vehicle_detail.html',
        vehicle=vehicle,
        regno=regno,
        today_trips=today_trips,
        today_mileage=today_mileage,
        mapping=mapping,
        current_account_id=acct_id,
        **_nav_back_ctx(url_for('tracking_dashboard')),
    )


# ════════════════════════════════════════════════════════════════════════════
# HISTORY / PLAYBACK
# ════════════════════════════════════════════════════════════════════════════

@app.route('/tracking/history')
def tracking_history():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    vehicles_list = get_all_vehicles_for_account(acct_id) if acct_id else []

    regno = request.args.get('regno', '')
    from_date = _sanitize_date(request.args.get('from_date', ''), (pk_date() - timedelta(days=1)).strftime('%Y-%m-%d'))
    to_date = _sanitize_date(request.args.get('to_date', ''), pk_date().strftime('%Y-%m-%d'))

    history_points = []
    error = None
    if regno and acct_id:
        fdt, tdt = _soap_dates(from_date, to_date)
        try:
            history_points = fetch_history(acct_id, regno, fdt, tdt)
        except Exception as e:
            error = str(e)[:300]

    return render_template(
        'tracking/history.html',
        vehicles_list=vehicles_list,
        selected_regno=regno,
        from_date=from_date,
        to_date=to_date,
        history_points=history_points,
        error=error,
        accounts=accounts,
        current_account_id=acct_id,
        **_nav_back_ctx(url_for('tracking_dashboard')),
    )


@app.route('/api/tracking/history')
def api_tracking_history():
    """API endpoint for AJAX history fetch."""
    acct_id = request.args.get('account_id', type=int) or _get_account_id()
    regno = request.args.get('regno', '')
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')
    if not acct_id or not regno:
        return jsonify({'error': 'Missing account_id or regno'}), 400
    fdt, tdt = _soap_dates(from_date, to_date)
    try:
        points = fetch_history(acct_id, regno, fdt, tdt)
        return jsonify({'points': points, 'count': len(points)})
    except Exception as e:
        return jsonify({'error': str(e)[:300]}), 500


# ════════════════════════════════════════════════════════════════════════════
# TRIPS
# ════════════════════════════════════════════════════════════════════════════

@app.route('/tracking/trips')
def tracking_trips():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    vehicles_list = get_all_vehicles_for_account(acct_id) if acct_id else []

    regno = request.args.get('regno', '')
    from_date = _sanitize_date(request.args.get('from_date', ''))
    to_date = _sanitize_date(request.args.get('to_date', ''))

    trips = []
    error = None
    if regno and acct_id:
        fdt, tdt = _soap_dates(from_date, to_date)
        try:
            trips = fetch_trips(acct_id, regno, fdt, tdt)
        except Exception as e:
            error = str(e)[:300]

    # Summary
    total_distance = sum(t.get('Mileage', 0) for t in trips)
    total_trips = len(trips)

    return render_template(
        'tracking/trips.html',
        vehicles_list=vehicles_list,
        selected_regno=regno,
        from_date=from_date,
        to_date=to_date,
        trips=trips,
        total_distance=total_distance,
        total_trips=total_trips,
        error=error,
        accounts=accounts,
        current_account_id=acct_id,
        **_nav_back_ctx(url_for('tracking_dashboard')),
    )


@app.route('/tracking/trips/export/csv')
def tracking_trips_export_csv():
    acct_id = _get_account_id()
    regno = request.args.get('regno', '')
    from_date = _sanitize_date(request.args.get('from_date', ''))
    to_date = _sanitize_date(request.args.get('to_date', ''))
    if not acct_id or not regno:
        return Response('Missing parameters', status=400)

    fdt, tdt = _soap_dates(from_date, to_date)
    try:
        trips = fetch_trips(acct_id, regno, fdt, tdt)
    except Exception as e:
        return Response(f'Error: {e}', status=500)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Vehicle', 'Trip Start', 'Start Location', 'Trip End', 'End Location',
                     'Mileage (km)', 'Max Speed', 'Avg Speed', 'Status'])
    for t in trips:
        writer.writerow([
            regno,
            t.get('IGON_RDT', ''),
            t.get('IGON_LandMark', ''),
            t.get('IGOFF_RDT', ''),
            t.get('IGOFF_LandMark', ''),
            t.get('Mileage', 0),
            t.get('MaxSpeed', 0),
            t.get('AvgSpeed', 0),
            t.get('TripStatus', ''),
        ])

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv'
    resp.headers['Content-Disposition'] = f'attachment; filename=trips_{regno}_{from_date}_{to_date}.csv'
    return resp


# ════════════════════════════════════════════════════════════════════════════
# FLEET REPORT
# ════════════════════════════════════════════════════════════════════════════

@app.route('/tracking/fleet-report')
def tracking_fleet_report():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    vehicles_list = get_all_vehicles_for_account(acct_id) if acct_id else []

    from_date = _sanitize_date(request.args.get('from_date', ''))
    to_date = _sanitize_date(request.args.get('to_date', ''))

    reports = []
    error = None
    if acct_id:
        fdt, tdt = _soap_dates(from_date, to_date)
        # Fetch report for each vehicle
        for v in vehicles_list:
            try:
                r = fetch_fleet_report(acct_id, v['portalxs_regno'], fdt, tdt)
                if r:
                    for item in r:
                        item['vehicle_no'] = v.get('vehicle_no') or v['portalxs_regno']
                        reports.append(item)
            except Exception as e:
                error = str(e)[:300]
                break

    # Sort by score descending (driver ranking)
    reports.sort(key=lambda x: x.get('VehicleScore', 0), reverse=True)

    return render_template(
        'tracking/fleet_report.html',
        vehicles_list=vehicles_list,
        from_date=from_date,
        to_date=to_date,
        reports=reports,
        error=error,
        accounts=accounts,
        current_account_id=acct_id,
        **_nav_back_ctx(url_for('tracking_dashboard')),
    )


# ════════════════════════════════════════════════════════════════════════════
# TRENDS
# ════════════════════════════════════════════════════════════════════════════

@app.route('/tracking/trends')
def tracking_trends():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    vehicles_list = get_all_vehicles_for_account(acct_id) if acct_id else []

    regno = request.args.get('regno', vehicles_list[0]['portalxs_regno'] if vehicles_list else '')
    from_date = _sanitize_date(request.args.get('from_date', ''), (pk_date() - timedelta(days=7)).strftime('%Y-%m-%d'))
    to_date = _sanitize_date(request.args.get('to_date', ''))

    trends = []
    error = None
    if regno and acct_id:
        fdt, tdt = _soap_dates(from_date, to_date)
        try:
            trends = fetch_trends(acct_id, regno, fdt, tdt)
        except Exception as e:
            error = str(e)[:300]

    return render_template(
        'tracking/trends.html',
        vehicles_list=vehicles_list,
        selected_regno=regno,
        from_date=from_date,
        to_date=to_date,
        trends=trends,
        error=error,
        accounts=accounts,
        current_account_id=acct_id,
        **_nav_back_ctx(url_for('tracking_dashboard')),
    )


# ════════════════════════════════════════════════════════════════════════════
# ALERTS
# ════════════════════════════════════════════════════════════════════════════

@app.route('/tracking/alerts')
def tracking_alerts():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()

    alerts = []
    error = None
    if acct_id:
        try:
            alerts = fetch_alerts(acct_id)
        except Exception as e:
            error = str(e)[:300]
            # Fall back to DB cached alerts
            cached = PortalXSAlertCache.query.filter_by(account_id=acct_id).order_by(
                PortalXSAlertCache.created_at.desc()
            ).limit(200).all()
            alerts = [{
                'regno': a.regno,
                'alert_type': a.alert_type,
                'alert_msg': a.alert_msg,
                'alert_time': a.alert_time.isoformat() if a.alert_time else '',
                'severity': a.severity,
            } for a in cached]

    return render_template(
        'tracking/alerts.html',
        alerts=alerts,
        error=error,
        accounts=accounts,
        current_account_id=acct_id,
        **_nav_back_ctx(url_for('tracking_dashboard')),
    )


# ════════════════════════════════════════════════════════════════════════════
# SETTINGS - Account management + vehicle linking
# ════════════════════════════════════════════════════════════════════════════

@app.route('/tracking/settings')
def tracking_settings():
    accounts = _get_all_accounts()
    return render_template(
        'tracking/settings.html',
        accounts=accounts,
        **_nav_back_ctx(url_for('tracking_dashboard')),
    )


@app.route('/tracking/settings/account/new', methods=['POST'])
def tracking_settings_account_new():
    label = request.form.get('label', 'Default').strip()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    if not username or not password:
        flash("Username and password are required.", "danger")
        return redirect(url_for('tracking_settings'))
    try:
        acct_id = create_account(label, username, password)
        flash(f"Account '{label}' created successfully ({acct_id}).", "success")
    except Exception as e:
        flash(f"Error creating account: {e}", "danger")
    return redirect(url_for('tracking_settings'))


@app.route('/tracking/settings/account/<int:acct_id>/edit', methods=['POST'])
def tracking_settings_account_edit(acct_id):
    label = request.form.get('label', '').strip()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    is_active = request.form.get('is_active') == 'on'
    try:
        update_account(acct_id, label=label or None, username=username or None,
                       password=password if password else None, is_active=is_active)
        flash("Account updated successfully.", "success")
    except Exception as e:
        flash(f"Error updating account: {e}", "danger")
    return redirect(url_for('tracking_settings'))


@app.route('/tracking/settings/account/<int:acct_id>/delete', methods=['POST'])
def tracking_settings_account_delete(acct_id):
    try:
        delete_account(acct_id)
        flash("Account deleted successfully.", "success")
    except Exception as e:
        flash(f"Error deleting account: {e}", "danger")
    return redirect(url_for('tracking_settings'))


@app.route('/tracking/settings/account/<int:acct_id>/test', methods=['POST'])
def tracking_settings_account_test(acct_id):
    acct = db.session.get(PortalXSAccount, acct_id)
    if not acct:
        return jsonify({'success': False, 'error': 'Account not found'}), 404
    password = decrypt_password(acct.password_enc)
    result = test_connection(acct.username, password)
    if result['success']:
        acct.last_connected = pk_now()
        acct.vehicle_count = result.get('vehicle_count', 0)
        acct.last_error = None
        db.session.commit()
    else:
        acct.last_error = result.get('error', '')
        db.session.commit()
    return jsonify(result)


@app.route('/tracking/settings/account/<int:acct_id>/sync', methods=['POST'])
def tracking_settings_account_sync(acct_id):
    """Force sync vehicle list from PortalXS."""
    try:
        vehicles = fetch_live_positions(acct_id, force=True)
        flash(f"Synced {len(vehicles)} vehicles from PortalXS.", "success")
    except Exception as e:
        flash(f"Sync error: {e}", "danger")
    return redirect(url_for('tracking_settings'))


@app.route('/tracking/settings/link-vehicle', methods=['POST'])
def tracking_settings_link_vehicle():
    mapping_id = request.form.get('mapping_id', type=int)
    vehicle_id = request.form.get('vehicle_id', type=int) or None
    if not mapping_id:
        flash("Mapping ID required.", "danger")
        return redirect(url_for('tracking_settings'))
    try:
        link_vehicle(mapping_id, vehicle_id)
        flash("Vehicle link updated.", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for('tracking_settings'))


@app.route('/tracking/settings/auto-link', methods=['POST'])
def tracking_settings_auto_link():
    """Auto-link all unlinked PortalXS vehicles to internal Vehicle records by RegNo match."""
    acct_id = request.form.get('account_id', type=int)
    if not acct_id:
        flash("Account ID required.", "danger")
        return redirect(url_for('tracking_settings'))
    try:
        result = auto_link_vehicles(acct_id)
        msg = (f"Auto-link complete: {result['linked']} linked, "
               f"{result['already_linked']} already linked, "
               f"{result['unmatched']} unmatched.")
        flash(msg, "success")
        if result['unmatched_list']:
            flash("Unmatched: " + ", ".join(result['unmatched_list'][:20]) +
                  ("..." if len(result['unmatched_list']) > 20 else ""), "info")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for('tracking_settings'))


@app.route('/tracking/settings/start-polling', methods=['POST'])
def tracking_settings_start_polling():
    """Start background polling thread."""
    try:
        from flask import current_app
        start_polling(current_app._get_current_object())
        flash("Background polling started.", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for('tracking_settings'))


# ── Vehicle list for linking (API) ───────────────────────────────────────────

@app.route('/api/tracking/vehicles/<int:acct_id>')
def api_tracking_vehicles(acct_id):
    """Get all vehicles (PortalXS + internal mapping) for an account."""
    vehicles = get_all_vehicles_for_account(acct_id)
    return jsonify(vehicles)


@app.route('/api/tracking/internal-vehicles')
def api_tracking_internal_vehicles():
    """Get internal vehicles for linking dropdown."""
    q = Vehicle.query.order_by(Vehicle.vehicle_no)
    search = request.args.get('search', '').strip()
    if search:
        q = q.filter(Vehicle.vehicle_no.ilike(f'%{search}%'))
    vehicles = q.limit(50).all()
    return jsonify([{'id': v.id, 'vehicle_no': v.vehicle_no, 'model': v.model} for v in vehicles])
