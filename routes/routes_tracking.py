"""
PortalXS Fleet Tracking Portal Routes
======================================
Live tracking dashboard, vehicle detail, history playback, trips,
fleet reports, trends, alerts, and settings.

Integrates with PortalXS SOAP API via services/portalxs_service.py.
"""
from flask import (
    render_template, redirect, url_for, flash, request,
    session, jsonify, make_response, Response, current_app,
)
from app import app, db, csrf
from models import (
    PortalXSAccount, PortalXSVehicleMapping,
    Vehicle,
)
from services.portalxs_service import (
    fetch_live_positions, fetch_mileage,
    fetch_fleet_report, fetch_fleet_report_bulk, fetch_trends_with_status,
    fetch_fleet_report_batch, fleet_report_cached,
    fetch_alerts, fetch_geofences, list_cached_alerts, fetch_nearest_vehicles,
    nearest_reference_position,
    get_cached_positions, get_summary_stats,
    get_all_vehicles_for_account, link_vehicle, auto_link_vehicles,
    create_account, update_account, delete_account,
    test_connection, encrypt_password, decrypt_password,
    start_polling, stop_polling, is_polling,
    consume_position_warning, friendly_portalxs_error,
)
from services.mileage_record_service import (
    aggregate_range_rows,
    daily_mileage_trend,
    fetch_and_upsert_batch,
    get_mileage_sync_status_display,
    mark_sync_status,
    normalize_reg_key,
    pending_regnos_for_day,
    plan_days_for_range,
)
from services.activity_record_service import (
    clear_activity_sync_remarks,
    ensure_activity_for_range,
    ensure_history_points_for_range,
    get_activity_sync_status_display,
    mark_activity_sync_status,
)
from services.trip_record_service import ensure_trips_for_range, load_trips_from_db
from services.device_health_service import (
    default_window as device_health_window,
    device_event_log,
    device_event_summary,
    reporting_gaps,
)
from services.activity_rollup_service import (
    coverage as rollup_coverage,
    dwell_by_location,
    dwell_by_vehicle,
    ensure_for_request as ensure_rollup_days,
    format_duration,
)
from services.fleet_score_service import (
    coverage as fleet_score_coverage,
    daily_fleet_score,
    default_window as fleet_score_window,
    score_movers,
    snapshot_running as fleet_score_snapshot_running,
    start_snapshot as start_fleet_score_snapshot,
    vehicle_score_summary,
)
from services.ignition_report_service import (
    coverage as ignition_coverage,
    default_window as ignition_window,
    ignition_by_vehicle,
    ignition_daily,
    ignition_log,
    refresh_vehicle as refresh_ignition_vehicle,
)
from utils import pk_now, pk_date, parse_date, safe_float
from datetime import datetime, timedelta, date
import csv
import io
import json

from routes import _nav_back_ctx

import logging

logger = logging.getLogger(__name__)


def _ufone_tasks_for_tracking() -> dict:
    try:
        from services.ufone_service import build_active_ufone_tasks_by_reg
        return build_active_ufone_tasks_by_reg()
    except Exception as e:
        logger.warning('ufone tasks for tracking map failed: %s', e)
        return {}


# ── Helper: get active account (first active, or by query param) ─────────────

def _sanitize_date(s: str, default: str = None) -> str:
    """Ensure date string is YYYY-MM-DD (accepts dd-mm-yyyy or yyyy-mm-dd)."""
    if not s or not str(s).strip():
        return default or pk_date().strftime('%Y-%m-%d')
    parsed = parse_date(s)
    if parsed:
        return parsed.strftime('%Y-%m-%d')
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


# ── Auto-start polling on first tracking request (survives server restarts) ───

_polling_autostart_done = False


@app.before_request
def _tracking_polling_autostart():
    """Lazy-start the background polling thread the first time any tracking
    page/API is hit after a server (re)start — no manual button needed."""
    global _polling_autostart_done
    if _polling_autostart_done:
        return
    ep = request.endpoint or ''
    if not (ep.startswith('tracking_') or ep.startswith('api_tracking_')):
        return
    try:
        if PortalXSAccount.query.filter_by(is_active=True).first():
            _polling_autostart_done = True
            start_polling(app)
    except Exception:
        pass


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
            error = consume_position_warning(acct_id)
        except Exception as e:
            error = friendly_portalxs_error(e)
            vehicles = get_cached_positions(acct_id)
            if vehicles:
                stats = get_summary_stats(acct_id)
            else:
                logger.warning('tracking_dashboard fetch failed acct=%s: %s', acct_id, e)
    else:
        error = "No PortalXS account configured. Add one in Settings."

    return render_template(
        'tracking/dashboard.html',
        vehicles=vehicles,
        stats=stats,
        accounts=accounts,
        current_account_id=acct_id,
        error=error,
        ufone_tasks_by_reg=_ufone_tasks_for_tracking(),
        **_nav_back_ctx(url_for('tracking_dashboard')),
    )


@app.route('/api/tracking/ufone-active-tasks')
def api_tracking_ufone_active_tasks():
    """Today's open Ufone tasks keyed by normalized vehicle reg (Fleet map pulse)."""
    return jsonify({'tasks_by_reg': _ufone_tasks_for_tracking()})


@app.route('/api/tracking/positions')
def api_tracking_positions():
    """API endpoint for auto-refresh: return cached/fresh positions as JSON."""
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account configured', 'vehicles': [], 'stats': {}})
    try:
        vehicles = fetch_live_positions(acct_id, force=False)
        stats = get_summary_stats(acct_id)
        warning = consume_position_warning(acct_id)
        return jsonify({
            'vehicles': vehicles,
            'stats': stats,
            'account_id': acct_id,
            'ufone_tasks_by_reg': _ufone_tasks_for_tracking(),
            'warning': warning,
        })
    except Exception as e:
        return jsonify({
            'error': friendly_portalxs_error(e),
            'vehicles': [],
            'stats': {},
            'warning': None,
        }), 200


@app.route('/api/tracking/refresh', methods=['POST'])
def api_tracking_refresh():
    """Force refresh positions from PortalXS."""
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account configured'}), 400
    try:
        vehicles = fetch_live_positions(acct_id, force=True)
        stats = get_summary_stats(acct_id)
        warning = consume_position_warning(acct_id)
        return jsonify({
            'vehicles': vehicles,
            'stats': stats,
            'refreshed_at': pk_now().isoformat(),
            'ufone_tasks_by_reg': _ufone_tasks_for_tracking(),
            'warning': warning,
        })
    except Exception as e:
        return jsonify({
            'error': friendly_portalxs_error(e),
            'vehicles': [],
            'stats': {},
            'warning': None,
        }), 200


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

    # Get today's trips summary (DB-first; today always refreshes from PortalXS)
    today = pk_date()
    today_trips = []
    today_mileage = {}
    try:
        today_trips, _terr, _tsrc = ensure_trips_for_range(
            acct_id, regno, today, today,
            vehicle_no=(vehicle.get('RegNo') or regno),
        )
        today_trips = [t for t in today_trips if float(t.get('Mileage') or 0) > 0]
    except Exception:
        pass
    try:
        fdt = today.strftime('%Y-%m-%dT00:00:00')
        tdt = today.strftime('%Y-%m-%dT23:59:59')
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
    today = pk_date().strftime('%Y-%m-%d')
    from_date = _sanitize_date(request.args.get('from_date', ''), today)
    to_date = _sanitize_date(request.args.get('to_date', ''), today)

    history_points = []
    trips = []
    error = None
    gps_source_label = ''
    trips_source_label = ''
    prefer_db = request.args.get('refresh') != '1'
    live_refresh = not prefer_db
    if regno and acct_id:
        group_name = ''
        vehicle_no = ''
        for v in vehicles_list:
            if v.get('portalxs_regno') == regno:
                group_name = v.get('group_name') or ''
                vehicle_no = v.get('vehicle_no') or ''
                break
        try:
            fd = datetime.strptime(from_date, '%Y-%m-%d').date()
            td = datetime.strptime(to_date, '%Y-%m-%d').date()
            # GPS activity ensure also co-syncs trips into vehicle_trip_record.
            history_points, hist_err, gps_source_label = ensure_history_points_for_range(
                acct_id, regno, fd, td,
                vehicle_no=vehicle_no, group_name=group_name,
                prefer_db=prefer_db,
            )
            if hist_err:
                hist_msg = f'History: {hist_err}'
                error = f'{error}; {hist_msg}' if error else hist_msg
            # Load trips from DB (already refreshed above). Today was API→DB; past DB-first.
            day = fd
            while day <= td:
                trips.extend(load_trips_from_db(day, regno, vehicle_no))
                day += timedelta(days=1)
            trips_source_label = gps_source_label or 'db'
        except Exception as e:
            hist_err = str(e)[:300]
            error = f'{error}; History: {hist_err}' if error else f'History: {hist_err}'
            logger.warning('tracking_history gps/trips failed regno=%s: %s', regno, e)
            try:
                db.session.rollback()
            except Exception:
                pass

        # Hide zero-distance trips on History page (ignition on/off with no movement).
        try:
            trips = [t for t in trips if safe_float(t.get('Mileage')) > 0]
            trips.sort(key=lambda t: str(t.get('IGON_RDT') or ''))
        except Exception as e:
            logger.warning('tracking_history trip filter failed regno=%s: %s', regno, e)
            try:
                db.session.rollback()
            except Exception:
                pass

        logger.info(
            'tracking_history regno=%s from=%s to=%s trips=%s points=%s gps=%s trips_src=%s prefer_db=%s',
            regno, from_date, to_date, len(trips), len(history_points),
            gps_source_label, trips_source_label, prefer_db,
        )

    total_distance = sum(safe_float(t.get('Mileage')) for t in trips)
    total_trips = len(trips)

    return render_template(
        'tracking/history.html',
        vehicles_list=vehicles_list,
        selected_regno=regno,
        from_date=from_date,
        to_date=to_date,
        history_points=history_points,
        trips=trips,
        total_trips=total_trips,
        total_distance=total_distance,
        error=error,
        gps_source_label=gps_source_label,
        trips_source_label=trips_source_label,
        live_refresh=live_refresh,
        accounts=accounts,
        current_account_id=acct_id,
        **_nav_back_ctx(url_for('module_hub', hub_slug='fleet-tracking')),
    )


@app.route('/api/tracking/history')
def api_tracking_history():
    """API endpoint for AJAX history fetch (DB-first GPS points)."""
    acct_id = request.args.get('account_id', type=int) or _get_account_id()
    regno = request.args.get('regno', '')
    from_date = _sanitize_date(request.args.get('from_date', ''))
    to_date = _sanitize_date(request.args.get('to_date', ''))
    if not acct_id or not regno:
        return jsonify({'error': 'Missing account_id or regno'}), 400

    vehicles_list = get_all_vehicles_for_account(acct_id)
    group_name = ''
    vehicle_no = ''
    for v in vehicles_list:
        if v.get('portalxs_regno') == regno:
            group_name = v.get('group_name') or ''
            vehicle_no = v.get('vehicle_no') or ''
            break
    try:
        fd = datetime.strptime(from_date, '%Y-%m-%d').date()
        td = datetime.strptime(to_date, '%Y-%m-%d').date()
        prefer_db = request.args.get('refresh') != '1'
        points, err, src = ensure_history_points_for_range(
            acct_id, regno, fd, td,
            vehicle_no=vehicle_no, group_name=group_name,
            prefer_db=prefer_db,
        )
        payload = {'points': points, 'count': len(points), 'source': src}
        if err:
            payload['warning'] = err
        return jsonify(payload)
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({'error': str(e)[:300]}), 500


# ════════════════════════════════════════════════════════════════════════════
# TRIPS (page removed — merged into Route History & Playback)
# ════════════════════════════════════════════════════════════════════════════

@app.route('/tracking/trips')
def tracking_trips():
    """Old Trips Report URL → History page (trips panel lives there now)."""
    args = request.args.to_dict(flat=True)
    if not args.get('nav_from'):
        args['nav_from'] = 'hub:fleet-tracking'
    return redirect(url_for('tracking_history', **args))


@app.route('/tracking/trips/export/csv')
def tracking_trips_export_csv():
    acct_id = _get_account_id()
    regno = request.args.get('regno', '')
    from_date = _sanitize_date(request.args.get('from_date', ''))
    to_date = _sanitize_date(request.args.get('to_date', ''))
    if not acct_id or not regno:
        return Response('Missing parameters', status=400)

    vehicles_list = get_all_vehicles_for_account(acct_id)
    vehicle_no = ''
    for v in vehicles_list:
        if v.get('portalxs_regno') == regno:
            vehicle_no = v.get('vehicle_no') or ''
            break
    try:
        fd = datetime.strptime(from_date, '%Y-%m-%d').date()
        td = datetime.strptime(to_date, '%Y-%m-%d').date()
        trips, err, _src = ensure_trips_for_range(
            acct_id, regno, fd, td, vehicle_no=vehicle_no,
        )
        if err and not trips:
            return Response(f'Error: {err}', status=500)
    except Exception as e:
        return Response(f'Error: {e}', status=500)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Vehicle', 'Trip Start', 'Start Location', 'Trip End', 'End Location',
                     'Mileage (km)', 'Max Speed', 'Avg Speed', 'Status', 'Source'])
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
            t.get('data_source', ''),
        ])

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv'
    resp.headers['Content-Disposition'] = f'attachment; filename=trips_{regno}_{from_date}_{to_date}.csv'
    return resp


# ════════════════════════════════════════════════════════════════════════════
# GPS POINT / ACTIVITY REPORT
# ════════════════════════════════════════════════════════════════════════════

def _activity_point_stats(points: list) -> dict:
    moving = sum(1 for p in points if safe_float(p.get('Speed')) > 0)
    stopped = len(points) - moving
    reasons: dict[str, int] = {}
    total_distance = 0.0
    for p in points:
        r = (p.get('Reason') or 'Unknown').strip() or 'Unknown'
        reasons[r] = reasons.get(r, 0) + 1
        total_distance += safe_float(p.get('Distance'))
    reason_rows = sorted(reasons.items(), key=lambda x: (-x[1], x[0]))
    return {
        'total': len(points),
        'moving': moving,
        'stopped': stopped,
        'reasons': reason_rows,
        'total_distance': round(total_distance, 2),
    }


@app.route('/tracking/activity-report')
def tracking_activity_report():
    """GPS Point / Activity Report — same DB table as Excel Tracker Activity uploads."""
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    vehicles_list = get_all_vehicles_for_account(acct_id) if acct_id else []

    today = pk_date().strftime('%Y-%m-%d')
    regno = request.args.get('regno', '')
    from_date = _sanitize_date(request.args.get('from_date', ''), today)
    to_date = _sanitize_date(request.args.get('to_date', ''), today)
    reason_filter = (request.args.get('reason') or '').strip()

    points = []
    error = None
    data_source_label = ''
    group_name = ''
    vehicle_no = ''
    if regno and acct_id:
        for v in vehicles_list:
            if v.get('portalxs_regno') == regno:
                group_name = v.get('group_name') or ''
                vehicle_no = v.get('vehicle_no') or ''
                break
        fd = datetime.strptime(from_date, '%Y-%m-%d').date()
        td = datetime.strptime(to_date, '%Y-%m-%d').date()
        try:
            points, error, data_source_label = ensure_activity_for_range(
                acct_id, regno, fd, td,
                vehicle_no=vehicle_no, group_name=group_name,
            )
            for p in points:
                if not p.get('RegNo'):
                    p['RegNo'] = regno
            # Manual Generate stamps last-fetch time; keep fleet fail remarks unless this call failed.
            mark_day = td if td >= pk_date() else fd
            if error:
                mark_activity_sync_status(
                    mark_day,
                    source='manual',
                    account_id=acct_id,
                    fetched_count=0,
                    error_count=1,
                    errors=[f'{regno}: {error}'],
                )
            else:
                mark_activity_sync_status(
                    mark_day,
                    source='manual',
                    account_id=acct_id,
                    fetched_count=1,
                    errors=None,
                )
        except Exception as e:
            error = str(e)[:300]
            logger.warning('tracking_activity_report failed regno=%s: %s', regno, e)
            # A failed write leaves the session needing a rollback, and without one
            # every query below raises too — the page 500s instead of showing this
            # error.
            try:
                db.session.rollback()
            except Exception:
                pass
            try:
                mark_activity_sync_status(
                    pk_date(),
                    source='manual',
                    account_id=acct_id,
                    fetched_count=0,
                    error_count=1,
                    errors=[f'{regno}: {error}'],
                )
            except Exception:
                pass

    # Reasons from unfiltered set for dropdown; apply filter after
    all_reasons = sorted({
        ((p.get('Reason') or 'Unknown').strip() or 'Unknown') for p in points
    })
    if reason_filter:
        points = [
            p for p in points
            if ((p.get('Reason') or 'Unknown').strip() or 'Unknown') == reason_filter
        ]

    stats = _activity_point_stats(points)
    try:
        sync_status = get_activity_sync_status_display(acct_id or None)
    except Exception as e:
        # Status is a convenience panel; never let it hide the report itself.
        logger.warning('activity sync status display failed: %s', e)
        sync_status = None

    return render_template(
        'tracking/activity_report.html',
        vehicles_list=vehicles_list,
        selected_regno=regno,
        from_date=from_date,
        to_date=to_date,
        reason_filter=reason_filter,
        all_reasons=all_reasons,
        points=points,
        stats=stats,
        error=error,
        data_source_label=data_source_label,
        sync_status=sync_status,
        accounts=accounts,
        current_account_id=acct_id,
        **_nav_back_ctx(url_for('module_hub', hub_slug='fleet-tracking')),
    )


@app.route('/tracking/activity-report/clear-sync-remarks', methods=['POST'])
def tracking_activity_report_clear_sync_remarks():
    """Dismiss fail remarks (X button) — keeps last sync timestamps."""
    acct_id = _get_account_id()
    n = clear_activity_sync_remarks(account_id=acct_id or None)
    return jsonify({
        'ok': True,
        'cleared': n,
        'sync_status': get_activity_sync_status_display(acct_id or None),
    })


@app.route('/tracking/activity-report/export/csv')
def tracking_activity_report_export_csv():
    acct_id = _get_account_id()
    regno = request.args.get('regno', '')
    from_date = _sanitize_date(request.args.get('from_date', ''))
    to_date = _sanitize_date(request.args.get('to_date', ''))
    reason_filter = (request.args.get('reason') or '').strip()
    if not acct_id or not regno:
        return Response('Missing parameters', status=400)

    vehicles_list = get_all_vehicles_for_account(acct_id)
    group_name = ''
    vehicle_no = ''
    for v in vehicles_list:
        if v.get('portalxs_regno') == regno:
            group_name = v.get('group_name') or ''
            vehicle_no = v.get('vehicle_no') or ''
            break

    fd = datetime.strptime(from_date, '%Y-%m-%d').date()
    td = datetime.strptime(to_date, '%Y-%m-%d').date()
    try:
        points, err, _src = ensure_activity_for_range(
            acct_id, regno, fd, td,
            vehicle_no=vehicle_no, group_name=group_name,
        )
        if err and not points:
            return Response(f'Error: {err}', status=500)
    except Exception as e:
        return Response(f'Error: {e}', status=500)

    if reason_filter:
        points = [
            p for p in points
            if ((p.get('Reason') or 'Unknown').strip() or 'Unknown') == reason_filter
        ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'RegNo', 'Group', 'Record Date Time', 'Location', 'Speed',
        'Direction', 'Distance', 'Travel Time', 'Stop Time', 'Reason', 'Source',
    ])
    for p in points:
        writer.writerow([
            p.get('RegNo', '') or regno,
            p.get('Group', ''),
            p.get('RecordDateTime', ''),
            p.get('Location', ''),
            p.get('Speed', 0),
            p.get('Direction', ''),
            p.get('Distance', 0),
            p.get('TravelTime', ''),
            p.get('StopTime', ''),
            p.get('Reason', ''),
            p.get('data_source', ''),
        ])

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv'
    safe_reg = regno.replace(' ', '_')
    resp.headers['Content-Disposition'] = (
        f'attachment; filename=gps_activity_{safe_reg}_{from_date}_{to_date}.csv'
    )
    return resp


# ════════════════════════════════════════════════════════════════════════════
# FLEET REPORT
# ════════════════════════════════════════════════════════════════════════════

def _fleet_report_names(vehicles_list: list) -> dict:
    return {v['portalxs_regno']: (v.get('vehicle_no') or v['portalxs_regno'])
            for v in vehicles_list}


def _apply_fleet_report_names(reports: list, names: dict) -> None:
    for item in reports:
        key = item.get('_regno') or item.get('RegNo', '')
        item['vehicle_no'] = names.get(key, item.get('RegNo', '') or key)


def _rank_fleet_reports(reports: list) -> list:
    reports.sort(key=lambda x: safe_float(x.get('VehicleScore')), reverse=True)
    return reports


@app.route('/tracking/fleet-report')
def tracking_fleet_report():
    """Render from cache only.

    One SOAP call per vehicle means a full fleet takes far longer than a single
    request may last, so the remaining vehicles are fetched by the browser in
    small batches via /tracking/fleet-report/fetch-batch.
    """
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    vehicles_list = get_all_vehicles_for_account(acct_id) if acct_id else []

    from_date = _sanitize_date(request.args.get('from_date', ''))
    to_date = _sanitize_date(request.args.get('to_date', ''))

    reports = []
    error = None
    pending_total = 0
    if acct_id and vehicles_list:
        fdt, tdt = _soap_dates(from_date, to_date)
        names = _fleet_report_names(vehicles_list)
        try:
            reports, missing = fleet_report_cached(acct_id, list(names.keys()), fdt, tdt)
        except Exception as e:
            logger.warning('fleet report cache read failed acct=%s: %s', acct_id, e)
            reports, missing = [], list(names.keys())
        pending_total = len(missing)
        _apply_fleet_report_names(reports, names)

    return render_template(
        'tracking/fleet_report.html',
        vehicles_list=vehicles_list,
        from_date=from_date,
        to_date=to_date,
        reports=_rank_fleet_reports(reports),
        error=error,
        pending_total=pending_total,
        total_vehicles=len(vehicles_list),
        accounts=accounts,
        current_account_id=acct_id,
        **_nav_back_ctx(url_for('tracking_dashboard')),
    )


@app.route('/tracking/fleet-report/fetch-batch', methods=['POST'])
def tracking_fleet_report_fetch_batch():
    """Fetch the next slice of vehicles for the fleet report."""
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'ok': False, 'error': 'No account configured'}), 400

    body = request.json or {}
    from_date = _sanitize_date(body.get('from_date') or '')
    to_date = _sanitize_date(body.get('to_date') or '')
    try:
        batch_size = int(body.get('batch_size') or 8)
    except (TypeError, ValueError):
        batch_size = 8
    batch_size = max(1, min(batch_size, 12))

    vehicles_list = get_all_vehicles_for_account(acct_id)
    if not vehicles_list:
        return jsonify({'ok': False, 'error': 'No vehicles'}), 400

    names = _fleet_report_names(vehicles_list)
    fdt, tdt = _soap_dates(from_date, to_date)

    cached_rows, missing = fleet_report_cached(acct_id, list(names.keys()), fdt, tdt)
    total = len(names)
    if not missing:
        _apply_fleet_report_names(cached_rows, names)
        return jsonify({
            'ok': True, 'complete': True, 'done': total, 'total': total,
            'batch_rows': [], 'rows': _rank_fleet_reports(cached_rows), 'error': None,
        })

    targets = missing[:batch_size]
    try:
        result = fetch_fleet_report_batch(acct_id, targets, fdt, tdt)
    except Exception as e:
        logger.exception('fleet report batch failed acct=%s', acct_id)
        return jsonify({'ok': False, 'error': friendly_portalxs_error(e)[:240]}), 500

    batch_rows = result['rows']
    _apply_fleet_report_names(batch_rows, names)
    done_after = total - len(missing) + len(result['done_regnos'])
    complete = done_after >= total

    payload = {
        'ok': True,
        'complete': complete,
        'done': done_after,
        'total': total,
        'batch_rows': _rank_fleet_reports(batch_rows),
        'error': '; '.join(result['errors'][:3]) if result['errors'] else None,
    }
    if complete:
        rows, _ = fleet_report_cached(acct_id, list(names.keys()), fdt, tdt)
        _apply_fleet_report_names(rows, names)
        payload['rows'] = _rank_fleet_reports(rows)
    return jsonify(payload)


@app.route('/tracking/fleet-report/export/csv')
def tracking_fleet_report_export_csv():
    """Export fleet report as CSV (uses same 5-min cache as the page)."""
    acct_id = _get_account_id()
    from_date = _sanitize_date(request.args.get('from_date', ''))
    to_date = _sanitize_date(request.args.get('to_date', ''))
    if not acct_id:
        return Response('No account configured', status=400)

    vehicles_list = get_all_vehicles_for_account(acct_id)
    if not vehicles_list:
        return Response('No vehicles', status=400)

    fdt, tdt = _soap_dates(from_date, to_date)
    regno_to_name = {v['portalxs_regno']: (v.get('vehicle_no') or v['portalxs_regno'])
                     for v in vehicles_list}
    reports, error = fetch_fleet_report_bulk(acct_id, list(regno_to_name.keys()), fdt, tdt)
    if error and not reports:
        return Response(f'Error: {error}', status=500)
    reports.sort(key=lambda x: x.get('VehicleScore', 0), reverse=True)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Rank', 'Vehicle', 'Score', 'Fuel (ltr)', 'Trips',
                     'Duration (h)', 'Distance (km)', 'Alerts'])
    for i, r in enumerate(reports, 1):
        writer.writerow([
            i,
            regno_to_name.get(r.get('_regno', ''), r.get('RegNo', '')),
            r.get('VehicleScore', 0),
            r.get('FuelConsumption', 0),
            r.get('Trips', 0),
            round((r.get('Duration', 0) or 0) / 3600, 1),
            r.get('Distance', 0),
            r.get('Alerts', 0),
        ])

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv'
    resp.headers['Content-Disposition'] = f'attachment; filename=fleet_report_{from_date}_{to_date}.csv'
    return resp


# ════════════════════════════════════════════════════════════════════════════
# VEHICLE MILEAGE REPORT
# Uses vehicle_mileage_record (same table as Excel upload).
# Today → always PortalXS full refresh (skip Excel-protected regs) + upsert.
# Past → DB if present, else PortalXS fill once.
# Range → per-day then sum for display.
# ════════════════════════════════════════════════════════════════════════════

def _parse_ymd(s: str) -> date:
    return datetime.strptime(_sanitize_date(s), '%Y-%m-%d').date()


def _mileage_display_names(vehicles_list: list) -> dict:
    names = {}
    for v in vehicles_list:
        display = v.get('vehicle_no') or v.get('portalxs_regno') or ''
        for raw in (v.get('portalxs_regno'), v.get('vehicle_no')):
            if not raw:
                continue
            names[str(raw)] = display
            key = normalize_reg_key(raw)
            if key:
                names[key] = display
    return names


def _apply_mileage_display_names(rows: list, names: dict) -> None:
    for item in rows:
        raw = item.get('_regno') or item.get('vehicle_no') or ''
        key = normalize_reg_key(raw)
        item['vehicle_no'] = names.get(key) or names.get(raw) or item.get('vehicle_no') or raw


@app.route('/tracking/mileage-report')
def tracking_mileage_report():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    vehicles_list = get_all_vehicles_for_account(acct_id) if acct_id else []

    from_date = _sanitize_date(request.args.get('from_date', ''))
    to_date = _sanitize_date(request.args.get('to_date', ''))
    run_query = ('from_date' in request.args) or ('to_date' in request.args)

    rows = []
    error = None
    day_plan = []
    pending_total = 0
    sync_status = get_mileage_sync_status_display(acct_id or None)
    if run_query and acct_id:
        fd = _parse_ymd(from_date)
        td = _parse_ymd(to_date)
        rows = aggregate_range_rows(fd, td)
        day_plan = plan_days_for_range(fd, td)
        for day in day_plan:
            if not day.get('needs_fetch'):
                day['pending'] = 0
                day['total'] = 0
                continue
            pending = pending_regnos_for_day(acct_id, _parse_ymd(day['date']), mode=day['mode'])
            day['pending'] = len(pending)
            day['total'] = len(pending)
            pending_total += len(pending)
        _apply_mileage_display_names(rows, _mileage_display_names(vehicles_list))

    return render_template(
        'tracking/mileage_report.html',
        vehicles_list=vehicles_list,
        from_date=from_date,
        to_date=to_date,
        rows=rows,
        error=error,
        accounts=accounts,
        current_account_id=acct_id,
        report_ready=run_query,
        day_plan=day_plan,
        pending_total=pending_total,
        total_vehicles=len(vehicles_list),
        sync_status=sync_status,
        **_nav_back_ctx(url_for('tracking_dashboard')),
    )


@app.route('/tracking/mileage-report/fetch-one', methods=['POST'])
def tracking_mileage_report_fetch_one():
    """Fetch next batch of vehicles from PortalXS for one day → upsert DB.

    Uses parallel SOAP (batch) to stay fast without hitting Render's ~30s limit.
    """
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'ok': False, 'error': 'No account configured'}), 400
    body = request.json or {}
    from_date = _sanitize_date(body.get('from_date') or request.form.get('from_date') or '')
    to_date = _sanitize_date(body.get('to_date') or request.form.get('to_date') or '')
    day_s = _sanitize_date(body.get('day') or from_date)
    mode = (body.get('mode') or '').strip() or None
    try:
        batch_size = int(body.get('batch_size') or 10)
    except (TypeError, ValueError):
        batch_size = 10
    batch_size = max(1, min(batch_size, 16))

    vehicles_list = get_all_vehicles_for_account(acct_id)
    if not vehicles_list:
        return jsonify({'ok': False, 'error': 'No vehicles'}), 400

    task_date = _parse_ymd(day_s)
    if not mode:
        from services.mileage_record_service import day_fetch_mode
        mode = day_fetch_mode(task_date)

    pending = pending_regnos_for_day(acct_id, task_date, mode=mode)
    names = _mileage_display_names(vehicles_list)

    done_regnos = body.get('done_regnos') or []
    if isinstance(done_regnos, str):
        done_regnos = [done_regnos]
    done_set = {str(x) for x in done_regnos}

    if mode == 'refresh_all':
        remaining_list = [p for p in pending if p['portalxs_regno'] not in done_set]
        total = len(pending)
    else:
        remaining_list = pending
        total = len(vehicles_list)

    if not remaining_list:
        rows = aggregate_range_rows(_parse_ymd(from_date), _parse_ymd(to_date))
        _apply_mileage_display_names(rows, names)
        return jsonify({
            'ok': True, 'complete': True, 'source': 'db',
            'done': len(done_set) if mode == 'refresh_all' else (total - len(remaining_list)),
            'total': total, 'remaining': 0, 'rows': rows, 'day': day_s, 'mode': mode,
            'done_regnos': [], 'batch_rows': [],
        })

    targets = remaining_list[:batch_size]
    try:
        result = fetch_and_upsert_batch(
            acct_id, targets, task_date, max_workers=8, deadline_sec=18,
        )
    except Exception as e:
        current_app.logger.exception('mileage fetch-batch failed day=%s', day_s)
        return jsonify({'ok': False, 'error': str(e)[:240]}), 500

    batch_rows = result.get('rows') or []
    for row in batch_rows:
        key = row.get('_regno') or ''
        display = names.get(normalize_reg_key(key)) or names.get(key) or row.get('vehicle_no') or key
        row['vehicle_no'] = display

    new_done = list(result.get('done_regnos') or [t['portalxs_regno'] for t in targets])
    done_after = len(done_set) + len(new_done)
    if mode == 'refresh_all':
        remaining_after = max(0, total - done_after)
    else:
        remaining_after = len(pending_regnos_for_day(acct_id, task_date, mode=mode))
        done_after = total - remaining_after

    complete = remaining_after <= 0
    err_list = result.get('errors') or []
    payload = {
        'ok': True,
        'complete': complete,
        'source': 'portalxs',
        'done': done_after,
        'total': max(total, done_after),
        'remaining': remaining_after,
        'batch_rows': batch_rows,
        'row': batch_rows[0] if batch_rows else None,
        'done_regnos': new_done,
        'regno': new_done[0] if new_done else '',
        'day': day_s,
        'mode': mode,
        'error': '; '.join(err_list[:3]) if err_list else None,
        'fetched': result.get('fetched') or 0,
    }
    if complete:
        mark_sync_status(
            task_date,
            source='manual',
            account_id=acct_id,
            fetched_count=done_after,
            error_count=len(err_list),
        )
        rows = aggregate_range_rows(_parse_ymd(from_date), _parse_ymd(to_date))
        _apply_mileage_display_names(rows, names)
        payload['rows'] = rows
        payload['sync_status'] = get_mileage_sync_status_display(acct_id)
    return jsonify(payload)


@app.route('/tracking/mileage-report/export/csv')
def tracking_mileage_report_export_csv():
    """Export vehicle mileage report as CSV from vehicle_mileage_record."""
    acct_id = _get_account_id()
    from_date = _sanitize_date(request.args.get('from_date', ''))
    to_date = _sanitize_date(request.args.get('to_date', ''))
    if not acct_id:
        return Response('No account configured', status=400)

    vehicles_list = get_all_vehicles_for_account(acct_id)
    names = _mileage_display_names(vehicles_list)
    rows = aggregate_range_rows(_parse_ymd(from_date), _parse_ymd(to_date))
    if not rows:
        return Response('No mileage data for this date. Generate the report first.', status=400)
    _apply_mileage_display_names(rows, names)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Reg No', 'Date From', 'Time From', 'Date To', 'Time To', 'Mileage', 'PtoP'])
    for r in rows:
        writer.writerow([
            r.get('ID', ''),
            r.get('vehicle_no') or r.get('_regno', ''),
            r.get('DateFrom', ''),
            r.get('TimeFrom', ''),
            r.get('DateTo', ''),
            r.get('TimeTo', ''),
            r.get('Mileage', 0),
            r.get('PToP', 0),
        ])

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv'
    resp.headers['Content-Disposition'] = f'attachment; filename=mileage_report_{from_date}_{to_date}.csv'
    return resp


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
    warning = None
    trend_source = ''
    if regno and acct_id:
        fdt, tdt = _soap_dates(from_date, to_date)
        try:
            trends, warning = fetch_trends_with_status(acct_id, regno, fdt, tdt)
            trend_source = 'PortalXS' if trends else ''
        except Exception as e:
            db.session.rollback()
            error = friendly_portalxs_error(e)
            logger.warning('tracking_trends fetch failed regno=%s: %s', regno, e)

        # PortalXS's trends endpoint is frequently down for a vehicle. Our own
        # per-day mileage records cover the same range, so chart those instead
        # of showing an empty page.
        if not trends:
            selected = next((v for v in vehicles_list if v['portalxs_regno'] == regno), None)
            try:
                trends = daily_mileage_trend(
                    regno, (selected or {}).get('vehicle_no'),
                    _parse_ymd(from_date), _parse_ymd(to_date),
                )
            except Exception as e:
                db.session.rollback()
                logger.warning('tracking_trends db fallback failed regno=%s: %s', regno, e)
                trends = []
            if any(safe_float(t.get('Mileage')) > 0 for t in trends):
                trend_source = 'Saved mileage records'
            else:
                trends = []

    return render_template(
        'tracking/trends.html',
        vehicles_list=vehicles_list,
        selected_regno=regno,
        from_date=from_date,
        to_date=to_date,
        trends=trends,
        trend_source=trend_source,
        warning=warning,
        error=error,
        accounts=accounts,
        current_account_id=acct_id,
        **_nav_back_ctx(url_for('tracking_dashboard')),
    )


# ════════════════════════════════════════════════════════════════════════════
# DEVICE HEALTH / TAMPER
# ════════════════════════════════════════════════════════════════════════════

@app.route('/tracking/device-health')
def tracking_device_health():
    """Which GPS units are failing, and which have been unplugged.

    Reads the activity stream the trackers already write, so there is no SOAP
    call and nothing to wait for.
    """
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    vehicles_list = get_all_vehicles_for_account(acct_id) if acct_id else []

    default_from, default_to = device_health_window(7)
    from_date = _sanitize_date(request.args.get('from_date', ''),
                               default_from.strftime('%Y-%m-%d'))
    to_date = _sanitize_date(request.args.get('to_date', ''),
                             default_to.strftime('%Y-%m-%d'))
    regno = request.args.get('regno', '').strip()

    rows = []
    events = []
    gaps = []
    coverage_info = None
    error = None
    if acct_id:
        fd, td = _parse_ymd(from_date), _parse_ymd(to_date)
        try:
            # Reporting gaps read the daily rollup, so make sure it covers the
            # window before asking it which vehicles went quiet.
            ensure_rollup_days(fd, td)
            coverage_info = rollup_coverage(fd, td)
            rows = device_event_summary(fd, td, regno)
            events = device_event_log(fd, td, regno, limit=400)
            gaps = reporting_gaps(fd, td, vehicles_list, regno)
        except Exception as e:
            db.session.rollback()
            error = str(e)[:240]
            logger.exception('device health report failed acct=%s', acct_id)

    names = _mileage_display_names(vehicles_list)
    for row in rows:
        key = normalize_reg_key(row['vehicle_no'])
        row['display_name'] = names.get(key) or row['vehicle_no']
    for event in events:
        key = normalize_reg_key(event['vehicle_no'])
        event['display_name'] = names.get(key) or event['vehicle_no']

    return render_template(
        'tracking/device_health.html',
        vehicles_list=vehicles_list,
        selected_regno=regno,
        from_date=from_date,
        to_date=to_date,
        rows=rows,
        events=events,
        gaps=gaps,
        coverage=coverage_info,
        error=error,
        tamper_count=sum(1 for r in rows if r['tamper_suspected']),
        critical_count=sum(1 for r in rows if r['status'] == 'critical'),
        silent_count=sum(1 for g in gaps if g['silent']),
        accounts=accounts,
        current_account_id=acct_id,
        **_nav_back_ctx(url_for('tracking_dashboard')),
    )


# ════════════════════════════════════════════════════════════════════════════
# STOPPAGE / DWELL TIME BY LOCATION
# ════════════════════════════════════════════════════════════════════════════

@app.route('/tracking/dwell-report')
def tracking_dwell_report():
    """Where the fleet spends its standing time.

    Served from vehicle_stop_location_daily; any days of the range that have
    not been rolled up yet are built here within a time budget, and the page
    reports the shortfall rather than stalling on a wide range.
    """
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    vehicles_list = get_all_vehicles_for_account(acct_id) if acct_id else []

    default_from, default_to = device_health_window(7)
    from_date = _sanitize_date(request.args.get('from_date', ''),
                               default_from.strftime('%Y-%m-%d'))
    to_date = _sanitize_date(request.args.get('to_date', ''),
                             default_to.strftime('%Y-%m-%d'))
    regno = request.args.get('regno', '').strip()

    locations = []
    per_vehicle = []
    build_info = None
    coverage_info = None
    error = None
    if acct_id:
        fd, td = _parse_ymd(from_date), _parse_ymd(to_date)
        try:
            build_info = ensure_rollup_days(fd, td)
            coverage_info = rollup_coverage(fd, td)
            locations = dwell_by_location(fd, td, regno, limit=100)
            per_vehicle = dwell_by_vehicle(fd, td, regno, limit=60)
        except Exception as e:
            db.session.rollback()
            error = str(e)[:240]
            logger.exception('dwell report failed acct=%s', acct_id)

    names = _mileage_display_names(vehicles_list)
    for row in per_vehicle:
        key = normalize_reg_key(row['vehicle_no'])
        row['display_name'] = names.get(key) or row['vehicle_no']

    total_seconds = sum(r['stop_seconds'] for r in locations)
    return render_template(
        'tracking/dwell_report.html',
        total_stop_text=format_duration(total_seconds),
        vehicles_list=vehicles_list,
        selected_regno=regno,
        from_date=from_date,
        to_date=to_date,
        locations=locations,
        per_vehicle=per_vehicle,
        coverage=coverage_info,
        build_info=build_info,
        error=error,
        total_stop_seconds=total_seconds,
        total_stop_hours=round(total_seconds / 3600.0, 1),
        total_visits=sum(r['visits'] for r in locations),
        accounts=accounts,
        current_account_id=acct_id,
        **_nav_back_ctx(url_for('tracking_dashboard')),
    )


# ════════════════════════════════════════════════════════════════════════════
# FLEET SCORE TREND - history of the fleet report's VehicleScore
# ════════════════════════════════════════════════════════════════════════════

@app.route('/tracking/score-trend')
def tracking_score_trend():
    """How fleet and per-vehicle scores moved over time.

    Reads only what has already been snapshotted into fleet_score_daily. The
    live fleet report costs one SOAP call per vehicle per day, so a range is
    never fetched on page load — the page states how much of the window is
    ready and offers to snapshot the rest.
    """
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    vehicles_list = get_all_vehicles_for_account(acct_id) if acct_id else []

    default_from, default_to = fleet_score_window(30)
    from_date = _sanitize_date(request.args.get('from_date', ''),
                               default_from.strftime('%Y-%m-%d'))
    to_date = _sanitize_date(request.args.get('to_date', ''),
                             default_to.strftime('%Y-%m-%d'))

    daily = []
    per_vehicle = []
    movers = {'improved': [], 'declined': [], 'split_date': None}
    coverage_info = None
    error = None
    if acct_id:
        fd, td = _parse_ymd(from_date), _parse_ymd(to_date)
        try:
            coverage_info = fleet_score_coverage(acct_id, fd, td)
            daily = daily_fleet_score(acct_id, fd, td)
            per_vehicle = vehicle_score_summary(acct_id, fd, td, limit=100)
            movers = score_movers(acct_id, fd, td, limit=5)
        except Exception as e:
            db.session.rollback()
            error = str(e)[:240]
            logger.exception('score trend failed acct=%s', acct_id)

    names = _mileage_display_names(vehicles_list)
    for row in per_vehicle:
        key = normalize_reg_key(row['reg_no'])
        row['display_name'] = names.get(key) or row['reg_no']

    scores = [d['avg_score'] for d in daily]
    return render_template(
        'tracking/score_trend.html',
        vehicles_list=vehicles_list,
        from_date=from_date,
        to_date=to_date,
        daily=daily,
        per_vehicle=per_vehicle,
        movers=movers,
        coverage=coverage_info,
        error=error,
        avg_score=round(sum(scores) / len(scores), 1) if scores else 0,
        best_day=max(daily, key=lambda d: d['avg_score']) if daily else None,
        worst_day=min(daily, key=lambda d: d['avg_score']) if daily else None,
        snapshot_running=fleet_score_snapshot_running(),
        accounts=accounts,
        current_account_id=acct_id,
        **_nav_back_ctx(url_for('tracking_dashboard')),
    )


@app.route('/tracking/score-trend/snapshot', methods=['POST'])
def tracking_score_trend_snapshot():
    """Kick off a snapshot of the days this window is still missing.

    One day is ~48 SOAP calls, so this cannot run inside the request; it starts
    a worker and the page reports progress on reload.
    """
    acct_id = _get_account_id()
    from_date = _sanitize_date(request.form.get('from_date', ''))
    to_date = _sanitize_date(request.form.get('to_date', ''))
    if not acct_id:
        flash('Koi PortalXS account active nahi hai.', 'warning')
        return redirect(url_for('tracking_score_trend'))

    fd, td = _parse_ymd(from_date), _parse_ymd(to_date)
    started = start_fleet_score_snapshot(acct_id, fd, td)
    if started is None:
        flash('Snapshot pehle se chal raha hai — thori dair mein page refresh karein.', 'info')
    elif started == 0:
        flash('Is range ke sab din pehle se snapshot ho chuke hain.', 'info')
    else:
        flash(f'{started} din ka snapshot background mein shuru ho gaya. '
              f'Har din takreeban {len(get_all_vehicles_for_account(acct_id) or [])} '
              f'SOAP calls leta hai, to thora waqt lagega.', 'success')
    return redirect(url_for('tracking_score_trend',
                            from_date=from_date, to_date=to_date))


# ════════════════════════════════════════════════════════════════════════════
# IGNITION ON/OFF - PortalXS trip cycles (not Ufone)
# ════════════════════════════════════════════════════════════════════════════

@app.route('/tracking/ignition-report')
def tracking_ignition_report():
    """Every ignition on→off cycle from PortalXS, including idle (0 km) ones.

    History already shows moving trips; this page keeps the cycles where the
    engine ran without leaving the spot, which History hides. Source is always
    PortalXS via vehicle_trip_record — never Ufone.
    """
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    vehicles_list = get_all_vehicles_for_account(acct_id) if acct_id else []

    default_from, default_to = ignition_window(7)
    from_date = _sanitize_date(request.args.get('from_date', ''),
                               default_from.strftime('%Y-%m-%d'))
    to_date = _sanitize_date(request.args.get('to_date', ''),
                             default_to.strftime('%Y-%m-%d'))
    regno = request.args.get('regno', '').strip()

    per_vehicle = []
    cycles = []
    daily = []
    coverage_info = None
    source_label = ''
    error = None
    if acct_id:
        fd, td = _parse_ymd(from_date), _parse_ymd(to_date)
        try:
            coverage_info = ignition_coverage(fd, td)
            # Selecting a vehicle refreshes that unit from PortalXS so the
            # detail is live; the fleet summary stays DB-backed (one SOAP call
            # per vehicle per day would turn a page load into minutes).
            if regno:
                selected = next(
                    (v for v in vehicles_list if v.get('portalxs_regno') == regno),
                    None,
                )
                refreshed, err, source_label = refresh_ignition_vehicle(
                    acct_id, regno, fd, td,
                    vehicle_no=(selected or {}).get('vehicle_no') or '',
                )
                if err and not refreshed:
                    error = err
            per_vehicle = ignition_by_vehicle(fd, td, regno, limit=80)
            cycles = ignition_log(fd, td, regno, limit=400)
            daily = ignition_daily(fd, td, regno)
        except Exception as e:
            db.session.rollback()
            error = str(e)[:240]
            logger.exception('ignition report failed acct=%s', acct_id)

    names = _mileage_display_names(vehicles_list)
    for row in per_vehicle:
        key = normalize_reg_key(row['vehicle_no'])
        row['display_name'] = names.get(key) or row['vehicle_no']
    for row in cycles:
        key = normalize_reg_key(row['vehicle_no'])
        row['display_name'] = names.get(key) or row['vehicle_no']

    total_cycles = sum(r['cycles'] for r in per_vehicle)
    idle_cycles = sum(r['idle_cycles'] for r in per_vehicle)
    on_seconds = sum(r['on_seconds'] for r in per_vehicle)
    return render_template(
        'tracking/ignition_report.html',
        vehicles_list=vehicles_list,
        selected_regno=regno,
        from_date=from_date,
        to_date=to_date,
        per_vehicle=per_vehicle,
        cycles=cycles,
        daily=daily,
        coverage=coverage_info,
        source_label=source_label,
        error=error,
        total_cycles=total_cycles,
        idle_cycles=idle_cycles,
        moving_cycles=total_cycles - idle_cycles,
        total_on_text=format_duration(on_seconds),
        total_distance=round(sum(r['distance'] for r in per_vehicle), 1),
        accounts=accounts,
        current_account_id=acct_id,
        **_nav_back_ctx(url_for('tracking_dashboard')),
    )


# ════════════════════════════════════════════════════════════════════════════
# DISPATCH ASSIST - nearest vehicle to a reference vehicle
# ════════════════════════════════════════════════════════════════════════════

@app.route('/tracking/dispatch')
def tracking_dispatch():
    """Nearest vehicles to a chosen one, with their current task state.

    The upstream endpoint anchors on a single vehicle and returns its
    neighbours in proximity order, so the reference vehicle is the emergency's
    location stand-in: pick the unit closest to the scene.
    """
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    vehicles_list = get_all_vehicles_for_account(acct_id) if acct_id else []

    regno = request.args.get('regno', '').strip()
    only_free = request.args.get('only_free', '') == '1'

    nearby = []
    error = None
    if acct_id and regno:
        try:
            nearby = fetch_nearest_vehicles(acct_id, regno)
        except Exception as e:
            db.session.rollback()
            error = friendly_portalxs_error(e)
            logger.warning('dispatch nearest fetch failed regno=%s: %s', regno, e)

    busy = _ufone_tasks_for_tracking() if nearby else {}
    names = _mileage_display_names(vehicles_list)
    for row in nearby:
        key = normalize_reg_key(row['regno'])
        row['display_name'] = names.get(key) or row['regno']
        task = busy.get(row['regno']) or busy.get(key) or {}
        row['task'] = task
        row['available'] = not task
        row['is_reference'] = key == normalize_reg_key(regno)

    # When the anchor comes back among its own neighbours it is not a dispatch
    # candidate; when it does not, its position still has to be shown.
    candidates = [r for r in nearby if not r['is_reference']]
    reference = next((r for r in nearby if r['is_reference']), None)
    if reference is None and regno:
        reference = nearest_reference_position(acct_id, regno)
    if only_free:
        candidates = [r for r in candidates if r['available']]

    return render_template(
        'tracking/dispatch.html',
        vehicles_list=vehicles_list,
        selected_regno=regno,
        only_free=only_free,
        reference=reference,
        candidates=candidates,
        free_count=sum(1 for r in candidates if r['available']),
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
    history = []
    error = None
    if acct_id:
        try:
            alerts = fetch_alerts(acct_id)
        except Exception as e:
            db.session.rollback()
            error = friendly_portalxs_error(e)
            logger.warning('tracking_alerts live fetch failed acct=%s: %s', acct_id, e)
        # History always comes from the cache so the page has content even when
        # PortalXS currently reports no open alerts.
        try:
            history = list_cached_alerts(acct_id, limit=300)
        except Exception as e:
            db.session.rollback()
            logger.warning('tracking_alerts history load failed acct=%s: %s', acct_id, e)

    live_keys = {(a.get('regno'), a.get('alert_type'), a.get('alert_time')) for a in alerts}
    history = [h for h in history
               if (h.get('regno'), h.get('alert_type'), h.get('alert_time')) not in live_keys]

    return render_template(
        'tracking/alerts.html',
        alerts=alerts,
        history=history,
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
        polling_active=is_polling(),
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


@app.route('/tracking/settings/stop-polling', methods=['POST'])
def tracking_settings_stop_polling():
    """Stop background polling thread."""
    try:
        stop_polling()
        flash("Background polling stopped.", "success")
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
