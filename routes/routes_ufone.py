# -*- coding: utf-8 -*-
"""
Ufone BPOCOPS Portal Routes
============================
Complete fleet tracking + task management + reporting system.
Uses flat @app.route pattern (mirrors routes_tracking.py), NOT a Blueprint.

All heavy lifting is done by services/ufone_service.py which caches
live positions and tasks in memory + DB.
"""
from flask import (
    render_template, redirect, url_for, flash, request,
    session, jsonify, make_response, Response,
)
from app import app, db, csrf
from models import (
    UfoneAccount, UfoneVehicleCache, UfoneTaskCache, UfoneMaintenanceCache,
)
from services.ufone_service import (
    fetch_live_positions, fetch_task_dashboard,
    fetch_tasks_report, get_districts_cached, fetch_dashboard_counts,
    get_cached_positions, get_summary_stats, load_dashboard_snapshot,
    load_vehicles_from_db,
    get_task_detail_cached, save_task_detail_cache,
    invalidate_task_detail_cache, _sync_emergency_report_live,
    get_tehsils_cached, get_ucs_cached, fetch_maintenance,
    fetch_report_cached, note_ui_activity,
    encrypt_password, decrypt_password,
    create_account, update_account, delete_account,
    test_connection, start_polling, stop_polling, is_polling,
)
from utils import pk_now, pk_date
from datetime import datetime, timedelta
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import re
import threading

logger = logging.getLogger(__name__)

# ── Lazy autostart of polling thread (mirrors tracking module) ───────────────
_ufone_autostart_done = False


@app.before_request
def _ufone_autostart():
    global _ufone_autostart_done
    ep = (request.endpoint or '')
    if not (ep.startswith('ufone_') or ep.startswith('api_ufone_')):
        return
    # Mark UI activity so the poll loop stays in "active" (fresh) cadence.
    try:
        note_ui_activity()
    except Exception:
        pass
    if _ufone_autostart_done:
        return
    _ufone_autostart_done = True

    # Never block the HTTP request on Ufone login / first poll.
    def _bg_start():
        try:
            with app.app_context():
                if UfoneAccount.query.filter_by(is_active=True).first() and not is_polling():
                    start_polling(app)
                    logger.info("Ufone polling autostarted (background)")
        except Exception as e:
            logger.warning(f"Ufone autostart failed: {e}")

    threading.Thread(target=_bg_start, daemon=True, name='ufone-autostart').start()


# ── Helper: get active account id from query/first-active ────────────────────

def _get_account_id() -> int:
    acct_id = request.args.get('account_id', type=int)
    if acct_id:
        return acct_id
    acct = UfoneAccount.query.filter_by(is_active=True).first()
    if acct:
        return acct.id
    return 0


def _get_all_accounts():
    return UfoneAccount.query.order_by(UfoneAccount.label).all()


def _sanitize_date(s, default=None):
    if not s or not str(s).strip():
        return default or pk_date().strftime('%Y-%m-%d')
    s = str(s).strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        return s
    try:
        return datetime.strptime(s[:10], '%Y-%m-%d').strftime('%Y-%m-%d')
    except Exception:
        return default or pk_date().strftime('%Y-%m-%d')


def _soap_dates(from_date, to_date):
    fd = _sanitize_date(from_date, (pk_date() - timedelta(days=1)).strftime('%Y-%m-%d'))
    td = _sanitize_date(to_date, pk_date().strftime('%Y-%m-%d'))
    return f"{fd}T00:00:00", f"{td}T23:59:59"


def _client_for(account_id):
    """Get raw API client for write actions / specific calls."""
    from services.ufone_service import _get_client
    return _get_client(account_id)


# ════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ════════════════════════════════════════════════════════════════════════════

@app.route('/ufone')
def ufone_dashboard():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    vehicles = []
    tasks = []
    stats = {'total': 0, 'active': 0, 'inactive': 0, 'with_gps': 0, 'without_gps': 0}
    error = None

    if acct_id:
        try:
            # INSTANT path only — memory/DB cache. Never call Ufone HTTP here
            # (that was freezing the page + silencing CMD access logs).
            vehicles, tasks, stats = load_dashboard_snapshot(acct_id)
            if not vehicles and not tasks:
                error = (
                    "Cache empty — live sync running in background. "
                    "Click Refresh in a few seconds, or open Settings → Start Polling."
                )

            # Fire-and-forget warm so next load / Refresh has fresh data.
            # NOTE: ambulance force-fetch removed — the 10-min poll loop keeps
            # ufone_vehicle_cache warm; page open must NOT trigger a 1394-row
            # Ufone call. We only warm the light today-only task dashboard and
            # sync today's EMG report to DB (so cards/filters have fresh rows).
            def _warm(aid=acct_id):
                try:
                    with app.app_context():
                        fetch_task_dashboard(aid, force=True, persist=True, for_poll=True)
                        _sync_emergency_report_live(aid)
                except Exception as we:
                    logger.warning(f"ufone warm failed: {we}")

            threading.Thread(target=_warm, daemon=True, name='ufone-warm').start()
        except Exception as e:
            error = str(e)[:300]
    else:
        error = "No Ufone account configured. Add one in Settings."

    incomplete_count = 0
    for t in tasks:
        st = (t.get('status') or '').lower()
        if 'incomplete' in st or st == '1' or 'in-process' in st or 'in process' in st:
            incomplete_count += 1

    return render_template(
        'ufone/dashboard.html',
        vehicles=vehicles, tasks=tasks, stats=stats, counts=[],
        incomplete_count=incomplete_count,
        accounts=accounts, current_account_id=acct_id, error=error,
    )


@app.route('/api/ufone/positions')
def api_ufone_positions():
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account', 'vehicles': [], 'stats': {}})
    try:
        # Cache/DB only — never block KPI auto-refresh on Ufone HTTP
        vehicles, _tasks, stats = load_dashboard_snapshot(acct_id)
        return jsonify({'vehicles': vehicles, 'stats': stats, 'account_id': acct_id})
    except Exception as e:
        return jsonify({'error': str(e)[:200], 'vehicles': [], 'stats': {}}), 200


@app.route('/api/ufone/refresh', methods=['POST'])
@csrf.exempt
def api_ufone_refresh():
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account'}), 400
    try:
        # Live pull — intentional (user clicked Refresh).
        # Use poll session so Task Detail (UI session) is not blocked.
        vehicles = fetch_live_positions(acct_id, force=True, persist=True, for_poll=True)
        try:
            fetch_task_dashboard(acct_id, force=True, persist=True, for_poll=True)
        except Exception as te:
            logger.warning(f"task refresh failed: {te}")
        stats = get_summary_stats(acct_id, vehicles=vehicles)
        return jsonify({'vehicles': vehicles, 'stats': stats,
                        'refreshed_at': pk_now().isoformat()})
    except Exception as e:
        return jsonify({'error': str(e)[:200]}), 500


@app.route('/api/ufone/dashboard_count')
def api_ufone_dashboard_count():
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account'})
    try:
        client = _client_for(acct_id)
        counts = client.get_dashboard_count_ras_cow()
        return jsonify({'counts': counts})
    except Exception as e:
        return jsonify({'error': str(e)[:200]})


@app.route('/api/ufone/dashboard/counts')
def api_ufone_dashboard_counts():
    """Portal-style aggregate counts for the dashboard cards (cache-first)."""
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account', 'counts': {}})
    try:
        force = request.args.get('force') in ('1', 'true', 'yes')
        counts = fetch_dashboard_counts(acct_id, force=force)
        return jsonify({'counts': counts, 'account_id': acct_id})
    except Exception as e:
        return jsonify({'error': str(e)[:200], 'counts': {}}), 200


# ════════════════════════════════════════════════════════════════════════════
# LIVE MAP
# ════════════════════════════════════════════════════════════════════════════

@app.route('/ufone/map')
def ufone_map():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    vehicles = []
    stats = {}
    error = None
    if acct_id:
        try:
            # DB-first: serve cached/DB positions instantly (no blocking Ufone
            # call on page open). The 10-min poll loop keeps them warm; a
            # background warm refreshes for the next load.
            vehicles, _tasks, stats = load_dashboard_snapshot(acct_id)

            def _warm(aid=acct_id):
                try:
                    with app.app_context():
                        fetch_live_positions(aid, force=True, persist=True, for_poll=True)
                except Exception as we:
                    logger.warning(f"ufone map warm failed: {we}")

            threading.Thread(target=_warm, daemon=True, name='ufone-map-warm').start()
        except Exception as e:
            error = str(e)[:300]
    else:
        error = "No Ufone account configured."
    return render_template(
        'ufone/live_map.html', vehicles=vehicles, stats=stats,
        accounts=accounts, current_account_id=acct_id, error=error,
    )


# ════════════════════════════════════════════════════════════════════════════
# AMBULANCE LIST + DETAIL
# ════════════════════════════════════════════════════════════════════════════

@app.route('/ufone/vehicles')
def ufone_vehicles():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    vehicles = []
    stats = {}
    error = None
    if acct_id:
        try:
            # DB-first: instant snapshot from cache/DB; warm in background so
            # page open never blocks on a 1394-row live getAmbulanceList.
            vehicles, _tasks, stats = load_dashboard_snapshot(acct_id)

            def _warm(aid=acct_id):
                try:
                    with app.app_context():
                        fetch_live_positions(aid, force=True, persist=True, for_poll=True)
                except Exception as we:
                    logger.warning(f"ufone vehicles warm failed: {we}")

            threading.Thread(target=_warm, daemon=True, name='ufone-veh-warm').start()
        except Exception as e:
            error = str(e)[:300]
    return render_template(
        'ufone/ambulance_list.html', vehicles=vehicles, stats=stats,
        accounts=accounts, current_account_id=acct_id, error=error,
    )


@app.route('/api/ufone/vehicles')
def api_ufone_vehicles():
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account', 'vehicles': []})
    try:
        # Cache/DB only — never block on Ufone HTTP. The poll loop + page-open
        # warm keep this fresh.
        vehicles, _tasks, _stats = load_dashboard_snapshot(acct_id)
        return jsonify({'vehicles': vehicles, 'account_id': acct_id})
    except Exception as e:
        return jsonify({'error': str(e)[:200], 'vehicles': []})


@app.route('/ufone/vehicle/<regno>')
def ufone_vehicle_detail(regno):
    acct_id = _get_account_id()
    if not acct_id:
        flash("No Ufone account configured.", "danger")
        return redirect(url_for('ufone_vehicles'))
    vehicles = get_cached_positions(acct_id)
    vehicle = next((v for v in vehicles if v.get('reg_no') == regno), None)
    if not vehicle:
        try:
            vehicles = fetch_live_positions(acct_id, force=True)
            vehicle = next((v for v in vehicles if v.get('reg_no') == regno), None)
        except Exception as e:
            flash(f"Error: {e}", "danger")
            return redirect(url_for('ufone_vehicles'))
    if not vehicle:
        flash(f"Vehicle {regno} not found.", "warning")
        return redirect(url_for('ufone_vehicles'))
    return render_template(
        'ufone/vehicle_detail.html', vehicle=vehicle, regno=regno,
        current_account_id=acct_id,
    )


# ════════════════════════════════════════════════════════════════════════════
# TRACK NEAREST AMBULANCE
# ════════════════════════════════════════════════════════════════════════════

@app.route('/ufone/track')
def ufone_track():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    districts = []
    if acct_id:
        try:
            districts = get_districts_cached(acct_id)
        except Exception:
            pass
    return render_template(
        'ufone/track_ambulance.html', districts=districts,
        accounts=accounts, current_account_id=acct_id,
    )


# ════════════════════════════════════════════════════════════════════════════
# CASCADE DROPDOWNS (district/tehsil/UC)
# ════════════════════════════════════════════════════════════════════════════

@app.route('/api/ufone/districts')
def api_ufone_districts():
    """Master district list [{code, name}] for filter dropdown (cached 1h)."""
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'districts': []})
    try:
        return jsonify({'districts': get_districts_cached(acct_id)})
    except Exception as e:
        return jsonify({'districts': [], 'error': str(e)[:200]})


@app.route('/api/ufone/tehsils/<int:district_code>')
def api_ufone_tehsils(district_code):
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account'}), 400
    try:
        return jsonify({'tehsils': get_tehsils_cached(acct_id, str(district_code))})
    except Exception as e:
        return jsonify({'error': str(e)[:200]}), 500


@app.route('/api/ufone/ucs/<int:tehsil_code>')
def api_ufone_ucs(tehsil_code):
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account'}), 400
    try:
        return jsonify({'ucs': get_ucs_cached(acct_id, str(tehsil_code))})
    except Exception as e:
        return jsonify({'error': str(e)[:200]}), 500


# ════════════════════════════════════════════════════════════════════════════
# TASKS - dashboard list, detail, actions
# ════════════════════════════════════════════════════════════════════════════

@app.route('/ufone/tasks')
def ufone_emergency_tasks():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    tasks = []
    error = None
    from_date = _sanitize_date(request.args.get('from_date'), pk_date().strftime('%Y-%m-%d'))
    to_date = _sanitize_date(request.args.get('to_date'), pk_date().strftime('%Y-%m-%d'))
    district = request.args.get('district', '')
    force = request.args.get('force') == '1'
    if acct_id:
        try:
            # DB-first (Phase 1): reads emergency_task_record; only syncs from
            # Ufone when stale (>3 min for today, never for historical). No live
            # call on page open when the 3-min poll loop keeps rows warm.
            tasks = fetch_tasks_report(
                acct_id, start_date=from_date, end_date=to_date,
                district=district, force=force,
            )
        except Exception as e:
            error = str(e)[:300]
    return render_template(
        'ufone/emergency_tasks.html', tasks=tasks, error=error,
        accounts=accounts, current_account_id=acct_id,
        from_date=from_date, to_date=to_date, district=district,
    )


def _cached_task_detail(acct_id, task_id):
    """Local DB row -> detail dict (instant, no Ufone HTTP)."""
    try:
        row = UfoneTaskCache.query.filter_by(
            account_id=acct_id, task_id=str(task_id)
        ).first()
        if not row:
            return {}
        if row.raw_json:
            try:
                detail = json.loads(row.raw_json)
                if detail:
                    return detail
            except Exception:
                pass
        return {
            'id': row.task_id,
            'TaskId': row.task_id,
            'name': row.patient_name,
            'phone': row.phone,
            'address': row.address,
            'Ambulance': row.ambulance_reg,
            'Status': row.status,
            'district_name': row.district,
            'tehsil_name': row.tehsil,
            'facility_name': row.facility,
            'RequestFrom': row.request_from,
            'Distance': float(row.distance) if row.distance is not None else None,
        }
    except Exception:
        return {}


@app.route('/ufone/task/<int:task_id>')
def ufone_task_detail(task_id):
    """Task detail for the popup — DB cache-first (Phase 1).

    Default: read ufone_task_detail_cache (full 76-field detail + comments).
    Falls back to UfoneTaskCache.raw_json (list-level snapshot) if no full cache.
    ?live=1: quick live fetch (12s timeout) + upsert into detail cache.
    Never hangs the modal — always returns something, with from_cache flag.
    """
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account'}), 400

    want_live = request.args.get('live') == '1'

    # 1. Full detail+comments from DB cache (instant)
    if not want_live:
        detail, comments, synced_at = get_task_detail_cached(acct_id, task_id)
        if detail:
            return jsonify({'detail': detail, 'comments': comments or [],
                            'from_cache': True})
        # Fall back to list-level snapshot
        snap = _cached_task_detail(acct_id, task_id)
        if snap:
            return jsonify({'detail': snap, 'comments': [], 'from_cache': True})

    # 2. Live fetch + cache
    detail = {}
    comments = []
    live_error = None
    try:
        client = _client_for(acct_id)
        detail = client.get_task_detail(task_id, quick=True) or {}
        try:
            comments = client.get_task_comments(task_id, quick=True) or []
        except Exception as ce:
            live_error = str(ce)[:200]
    except Exception as e:
        live_error = str(e)[:200]

    if detail:
        # Persist full detail + comments to DB for future instant reads
        save_task_detail_cache(acct_id, task_id, detail, comments)
        payload = {'detail': detail, 'comments': comments}
        if live_error:
            payload['warning'] = live_error
        return jsonify(payload)

    # 3. Live failed — serve whatever cache we have
    detail, comments, _ = get_task_detail_cached(acct_id, task_id)
    if detail:
        return jsonify({'detail': detail, 'comments': comments or [],
                        'from_cache': True,
                        'warning': live_error or 'Live fetch unavailable'})
    snap = _cached_task_detail(acct_id, task_id)
    if snap:
        return jsonify({'detail': snap, 'comments': [], 'from_cache': True,
                        'warning': live_error or 'Live fetch unavailable'})

    return jsonify({'error': live_error or 'Task not found',
                    'detail': {}, 'comments': []}), 502


@app.route('/api/ufone/task/<int:task_id>/comments')
def api_ufone_task_comments(task_id):
    """Comments — DB cache-first (5 min for open tasks, forever for closed).
    ?live=1 forces a live refresh + re-cache."""
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account'}), 400
    want_live = request.args.get('live') == '1'
    if not want_live:
        _detail, comments, _ = get_task_detail_cached(acct_id, task_id, max_age_seconds=300)
        if comments is not None:
            return jsonify({'comments': comments})
    try:
        client = _client_for(acct_id)
        comments = client.get_task_comments(task_id) or []
        # Re-cache comments alongside existing detail
        detail, _, _ = get_task_detail_cached(acct_id, task_id)
        save_task_detail_cache(acct_id, task_id, detail or {}, comments)
        return jsonify({'comments': comments})
    except Exception as e:
        return jsonify({'error': str(e)[:200]}), 500


@app.route('/api/ufone/task/<int:task_id>/comment', methods=['POST'])
@csrf.exempt
def api_ufone_task_comment_save(task_id):
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account'}), 400
    comment_type = request.json.get('comment_type', '')
    comments = request.json.get('comments', '')
    if not comment_type or not comments:
        return jsonify({'error': 'Comment type and comments required'}), 400
    try:
        client = _client_for(acct_id)
        client.save_task_comment(task_id, comment_type, comments)
        # Invalidate detail cache so next read re-fetches with new comment
        invalidate_task_detail_cache(acct_id, task_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)[:200]}), 500


@app.route('/api/ufone/task/<int:task_id>/feedback', methods=['POST'])
@csrf.exempt
def api_ufone_task_feedback_save(task_id):
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account'}), 400
    feedback = request.json.get('feedback', '')
    if not feedback:
        return jsonify({'error': 'Feedback required'}), 400
    try:
        client = _client_for(acct_id)
        client.save_task_feedback(task_id, feedback)
        invalidate_task_detail_cache(acct_id, task_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)[:200]}), 500


@app.route('/api/ufone/task/<int:task_id>/complete', methods=['POST'])
@csrf.exempt
def api_ufone_task_complete(task_id):
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account'}), 400
    amb_id = request.json.get('amb_id', '')
    received_by = request.json.get('received_by', '')
    is_received = request.json.get('is_received', '')
    try:
        client = _client_for(acct_id)
        client.set_task_complete(task_id, amb_id, received_by, is_received)
        # Invalidate detail cache + update UfoneTaskCache status locally
        invalidate_task_detail_cache(acct_id, task_id)
        try:
            row = UfoneTaskCache.query.filter_by(
                account_id=acct_id, task_id=str(task_id)).first()
            if row:
                row.status = 'Complete'
                db.session.commit()
        except Exception:
            db.session.rollback()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)[:200]}), 500


@app.route('/api/ufone/tasks/dashboard')
def api_ufone_tasks_dashboard():
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account', 'tasks': []})
    try:
        live = request.args.get('live', '').lower() in ('1', 'true', 'yes')
        if live:
            tasks = fetch_task_dashboard(acct_id, force=True, persist=True)
        else:
            _v, tasks, _s = load_dashboard_snapshot(acct_id)
        return jsonify({'tasks': tasks})
    except Exception as e:
        return jsonify({'error': str(e)[:200], 'tasks': []})


@app.route('/api/ufone/tasks/filtered')
def api_ufone_tasks_filtered():
    """Dashboard filter section: all-district task report with local filters.

    Params: from_date, to_date (YYYY-MM-DD), district (Ufone code),
    vehicle (reg-no substring), status (incomplete/completed/cancelled).
    DB-first (Phase 1): reads emergency_task_record (source='api'). Only
    syncs from Ufone when today's rows are stale (>3 min) or missing — the
    3-min poll loop keeps them warm, so filter Apply is normally instant
    and NEVER hits Ufone.
    """
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account', 'tasks': []}), 400

    today = pk_date().strftime('%Y-%m-%d')
    from_date = _sanitize_date(request.args.get('from_date'), today)
    to_date = _sanitize_date(request.args.get('to_date'), today)
    district = (request.args.get('district') or '').strip()
    vehicle = (request.args.get('vehicle') or '').strip().lower()
    status = (request.args.get('status') or '').strip().lower()
    force = request.args.get('force') == '1'

    try:
        tasks = fetch_tasks_report(
            acct_id, start_date=from_date, end_date=to_date,
            district=district, force=force,
        )
    except Exception as e:
        msg = str(e)[:200]
        # Friendlier message for Ufone server timeouts / connection errors
        if 'ConnectTimeout' in msg or 'Max retries exceeded' in msg or 'ConnectionError' in msg:
            msg = ('Ufone server se connect nahi ho pa raha (timeout). '
                   'Cards cached data se chal rahe hain. '
                   'Dobara Apply karein — ya thodi der baad try karein.')
        return jsonify({'error': msg, 'tasks': []}), 502

    if vehicle:
        tasks = [t for t in tasks
                 if vehicle in str(t.get('ambulance') or '').lower()]
    if status:
        def _st(t):
            s = str(t.get('status') or '').lower()
            if 'incomplete' in s or s == '1' or 'in-process' in s or 'in process' in s:
                return 'incomplete'
            if 'cancel' in s:
                return 'cancelled'
            if 'complete' in s:
                return 'completed'
            return 'other'
        tasks = [t for t in tasks if _st(t) == status]

    incomplete = sum(
        1 for t in tasks
        if 'incomplete' in str(t.get('status') or '').lower()
        or str(t.get('status') or '') == '1'
        or 'in-process' in str(t.get('status') or '').lower()
        or 'in process' in str(t.get('status') or '').lower()
    )
    completed = sum(
        1 for t in tasks
        if 'complete' in str(t.get('status') or '').lower()
        and 'incomplete' not in str(t.get('status') or '').lower()
    )
    cancelled = sum(
        1 for t in tasks
        if 'cancel' in str(t.get('status') or '').lower()
    )

    # Card stats: filtered tasks ki unique ambulances × local vehicle cache
    fleet = get_cached_positions(acct_id) or load_vehicles_from_db(acct_id) or []
    by_reg = {
        str(v.get('reg_no') or '').strip().lower(): v
        for v in fleet if v.get('reg_no')
    }
    task_regs = {
        str(t.get('ambulance') or '').strip()
        for t in tasks if str(t.get('ambulance') or '').strip()
    }
    matched = [by_reg[r.lower()] for r in task_regs if r.lower() in by_reg]
    # Prefer district-name match on full fleet when enough vehicles have district filled
    dist_name = ''
    if district:
        try:
            for d in get_districts_cached(acct_id):
                if str(d.get('code')) == str(district):
                    dist_name = str(d.get('name') or '').strip()
                    break
        except Exception:
            dist_name = ''
    fleet_in_district = []
    if dist_name:
        dn = ''.join(ch for ch in dist_name.lower() if ch.isalnum())
        for v in fleet:
            vd = ''.join(ch for ch in str(v.get('district') or '').lower() if ch.isalnum())
            if vd and (vd == dn or dn in vd or vd in dn):
                fleet_in_district.append(v)
    use_fleet = fleet_in_district if len(fleet_in_district) > 0 else matched
    vehicle_stats = {
        'total': len(use_fleet) if use_fleet else len(task_regs),
        'active': sum(1 for v in use_fleet if str(v.get('status')) == '1'),
        'inactive': sum(1 for v in use_fleet if str(v.get('status')) == '2'),
        'with_gps': sum(1 for v in use_fleet if v.get('has_gps')),
    }

    return jsonify({
        'tasks': tasks,
        'counts': {
            'total': len(tasks),
            'incomplete': incomplete,
            'completed': completed,
            'cancelled': cancelled,
        },
        'vehicle_stats': vehicle_stats,
        'from_date': from_date, 'to_date': to_date,
        'district': district,
    })


@app.route('/ufone/tasks/counts')
def ufone_task_counts():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    daily = []
    monthly = []
    error = None
    from_date = _sanitize_date(request.args.get('from_date'),
                                (pk_date() - timedelta(days=7)).strftime('%Y-%m-%d'))
    to_date = _sanitize_date(request.args.get('to_date'), pk_date().strftime('%Y-%m-%d'))
    force = request.args.get('force') == '1'
    if acct_id:
        try:
            params = {'from_date': from_date, 'to_date': to_date}
            daily = fetch_report_cached(
                acct_id, 'daily_task_count',
                lambda c: c.get_daily_task_count(from_date, to_date),
                params=params, max_age_seconds=600, for_poll=force)
            monthly = fetch_report_cached(
                acct_id, 'monthly_task_count',
                lambda c: c.get_monthly_task_count(pk_date().strftime('%Y-%m')),
                params={'month': pk_date().strftime('%Y-%m')},
                max_age_seconds=3600, for_poll=force)
        except Exception as e:
            error = str(e)[:300]
    return render_template(
        'ufone/task_counts.html', daily=daily, monthly=monthly, error=error,
        accounts=accounts, current_account_id=acct_id,
        from_date=from_date, to_date=to_date,
    )


# ════════════════════════════════════════════════════════════════════════════
# REPORTS - history, ignition, distance, maintenance, patients
# ════════════════════════════════════════════════════════════════════════════

@app.route('/ufone/history')
def ufone_history():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    return render_template(
        'ufone/vehicle_history.html', accounts=accounts,
        current_account_id=acct_id,
    )


@app.route('/ufone/ignition')
def ufone_ignition():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    return render_template(
        'ufone/ignition_report.html', accounts=accounts,
        current_account_id=acct_id,
    )


@app.route('/ufone/distance')
def ufone_distance():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    from_date = _sanitize_date(request.args.get('from_date'),
                                (pk_date() - timedelta(days=1)).strftime('%Y-%m-%d'))
    to_date = _sanitize_date(request.args.get('to_date'), pk_date().strftime('%Y-%m-%d'))
    district = request.args.get('district', '')
    records = []
    error = None
    force = request.args.get('force') == '1'
    if acct_id:
        try:
            params = {'from_date': from_date, 'to_date': to_date, 'district': district}
            records = fetch_report_cached(
                acct_id, 'distance',
                lambda c: c.get_distance_report(from_date, to_date, district),
                params=params, max_age_seconds=600, for_poll=force)
        except Exception as e:
            error = str(e)[:300]
    return render_template(
        'ufone/distance_report.html', records=records, error=error,
        accounts=accounts, current_account_id=acct_id,
        from_date=from_date, to_date=to_date, district=district,
    )


@app.route('/ufone/maintenance')
def ufone_maintenance():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    records = []
    error = None
    force = request.args.get('force') == '1'
    if acct_id:
        try:
            records = fetch_maintenance(acct_id, force=force)
        except Exception as e:
            error = str(e)[:300]
    return render_template(
        'ufone/maintenance.html', records=records, error=error,
        accounts=accounts, current_account_id=acct_id,
    )


@app.route('/ufone/patients')
def ufone_patient_reports():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    from_date = _sanitize_date(request.args.get('from_date'),
                                (pk_date() - timedelta(days=1)).strftime('%Y-%m-%d'))
    to_date = _sanitize_date(request.args.get('to_date'), pk_date().strftime('%Y-%m-%d'))
    district = request.args.get('district', '')
    records = []
    error = None
    force = request.args.get('force') == '1'
    if acct_id:
        try:
            params = {'from_date': from_date, 'to_date': to_date, 'district': district}
            records = fetch_report_cached(
                acct_id, 'patients',
                lambda c: c.get_patients(from_date, to_date, district),
                params=params, max_age_seconds=600, for_poll=force)
        except Exception as e:
            error = str(e)[:300]
    return render_template(
        'ufone/patient_reports.html', records=records, error=error, tab='regular',
        accounts=accounts, current_account_id=acct_id,
        from_date=from_date, to_date=to_date, district=district,
    )


@app.route('/ufone/patients/ussd')
def ufone_patient_reports_ussd():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    from_date = _sanitize_date(request.args.get('from_date'),
                                (pk_date() - timedelta(days=1)).strftime('%Y-%m-%d'))
    to_date = _sanitize_date(request.args.get('to_date'), pk_date().strftime('%Y-%m-%d'))
    district = request.args.get('district', '')
    records = []
    error = None
    force = request.args.get('force') == '1'
    if acct_id:
        try:
            params = {'from_date': from_date, 'to_date': to_date, 'district': district}
            records = fetch_report_cached(
                acct_id, 'patients_ussd',
                lambda c: c.get_patients_ussd(from_date, to_date, district),
                params=params, max_age_seconds=600, for_poll=force)
        except Exception as e:
            error = str(e)[:300]
    return render_template(
        'ufone/patient_reports.html', records=records, error=error, tab='ussd',
        accounts=accounts, current_account_id=acct_id,
        from_date=from_date, to_date=to_date, district=district,
    )


# ════════════════════════════════════════════════════════════════════════════
# ADMIN PAGES (patient reg / ambulance mgmt / assignment)
# ════════════════════════════════════════════════════════════════════════════

@app.route('/ufone/admin/patients')
def ufone_admin_patients():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    return render_template(
        'ufone/patient_registration.html', accounts=accounts,
        current_account_id=acct_id,
    )


@app.route('/ufone/admin/ambulances')
def ufone_admin_ambulances():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    return render_template(
        'ufone/ambulance_management.html', accounts=accounts,
        current_account_id=acct_id,
    )


@app.route('/ufone/admin/assignments')
def ufone_admin_assignments():
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    districts = []
    if acct_id:
        try:
            districts = get_districts_cached(acct_id)
        except Exception:
            pass
    return render_template(
        'ufone/ambulance_assignment.html', districts=districts, accounts=accounts,
        current_account_id=acct_id,
    )


# ════════════════════════════════════════════════════════════════════════════
# CSV EXPORTS
# ════════════════════════════════════════════════════════════════════════════

@app.route('/ufone/export/vehicles')
def ufone_export_vehicles():
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account'}), 400
    vehicles = get_cached_positions(acct_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['Reg_No', 'UTrackNo', 'District', 'Location', 'Latitude',
                'Longitude', 'Status', 'Driver', 'Driver_Cell', 'Facility'])
    for v in vehicles:
        w.writerow([v.get('reg_no'), v.get('u_track_no'), v.get('district'),
                    v.get('location'), v.get('latitude'), v.get('longitude'),
                    v.get('status'), v.get('driver_name'), v.get('driver_cell'),
                    v.get('facility_name')])
    resp = make_response(buf.getvalue())
    resp.headers['Content-Disposition'] = 'attachment; filename=ufone_vehicles.csv'
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    return resp


@app.route('/ufone/export/tasks')
def ufone_export_tasks():
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account'}), 400
    from_date = _sanitize_date(request.args.get('from_date'), pk_date().strftime('%Y-%m-%d'))
    to_date = _sanitize_date(request.args.get('to_date'), pk_date().strftime('%Y-%m-%d'))
    district = request.args.get('district', '')
    try:
        tasks = fetch_tasks_report(
            acct_id, start_date=from_date, end_date=to_date,
            district=district, force=False,
        )
    except Exception as e:
        tasks = []
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['TaskId', 'Name', 'Phone', 'Address', 'Ambulance', 'Status',
                'District', 'Tehsil', 'Facility', 'RequestFrom', 'CreatedDate'])
    for t in tasks:
        w.writerow([t.get('TaskId') or t.get('id'), t.get('Name') or t.get('name'),
                    t.get('Phone') or t.get('phone'), t.get('Address') or t.get('address'),
                    t.get('Ambulance'), t.get('Status'), t.get('District') or t.get('district_name'),
                    t.get('Tehsil') or t.get('tehsil_name'),
                    t.get('facility_name'), t.get('RequestFrom'),
                    t.get('CreatedDate') or t.get('CD')])
    resp = make_response(buf.getvalue())
    resp.headers['Content-Disposition'] = 'attachment; filename=ufone_tasks.csv'
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    return resp


@app.route('/ufone/export/distance')
def ufone_export_distance():
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account'}), 400
    from_date = _sanitize_date(request.args.get('from_date'),
                                (pk_date() - timedelta(days=1)).strftime('%Y-%m-%d'))
    to_date = _sanitize_date(request.args.get('to_date'), pk_date().strftime('%Y-%m-%d'))
    district = request.args.get('district', '')
    try:
        params = {'from_date': from_date, 'to_date': to_date, 'district': district}
        records = fetch_report_cached(
            acct_id, 'distance',
            lambda c: c.get_distance_report(from_date, to_date, district),
            params=params, max_age_seconds=600)
    except Exception:
        records = []
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['Reg_No', 'MakeModel', 'Distance', 'District', 'Location'])
    for r in records:
        w.writerow([r.get('Reg_No'), r.get('MakeModel'), r.get('Distance'),
                    r.get('District'), r.get('Location')])
    resp = make_response(buf.getvalue())
    resp.headers['Content-Disposition'] = 'attachment; filename=ufone_distance.csv'
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    return resp


# ════════════════════════════════════════════════════════════════════════════
# SETTINGS - Account CRUD + Polling
# ════════════════════════════════════════════════════════════════════════════

@app.route('/ufone/settings')
def ufone_settings():
    accounts = _get_all_accounts()
    polling = False
    try:
        polling = is_polling()
    except Exception:
        pass
    return render_template(
        'ufone/settings.html', accounts=accounts,
        polling_active=polling,
    )


@app.route('/ufone/settings/account/new', methods=['GET', 'POST'])
def ufone_settings_account_new():
    if request.method == 'POST':
        label = request.form.get('label', 'Default').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role', 'Operator').strip()
        if not username or not password:
            flash("Username aur password zaroori hain.", "danger")
            return redirect(url_for('ufone_settings_account_new'))
        try:
            acct_id = create_account(label, username, password, role)
            flash(f"Account '{label}' create ho gaya (id={acct_id}).", "success")
            return redirect(url_for('ufone_settings'))
        except Exception as e:
            flash(f"Error: {e}", "danger")
            return redirect(url_for('ufone_settings_account_new'))

    # GET request - render the form page
    return render_template('ufone/account_form.html')


@app.route('/ufone/settings/account/<int:acct_id>/edit', methods=['POST'])
def ufone_settings_account_edit(acct_id):
    label = request.form.get('label', '').strip()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()  # optional
    role = request.form.get('role', 'Operator').strip()
    is_active = request.form.get('is_active') == 'on'
    try:
        update_account(acct_id, label=label or None, username=username or None,
                       password=password or None, role=role, is_active=is_active)
        flash("Account update ho gaya.", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for('ufone_settings'))


@app.route('/ufone/settings/account/<int:acct_id>/delete', methods=['POST'])
def ufone_settings_account_delete(acct_id):
    try:
        delete_account(acct_id)
        flash(f"Account {acct_id} delete ho gaya.", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for('ufone_settings'))


@app.route('/ufone/settings/account/<int:acct_id>/test', methods=['POST'])
def ufone_settings_account_test(acct_id):
    acct = UfoneAccount.query.get(acct_id)
    if not acct:
        return jsonify({'success': False, 'error': 'Account not found'}), 404
    password = decrypt_password(acct.password_enc)
    ok, msg = test_connection(acct.username, password)
    # Update last_error
    try:
        acct.last_error = None if ok else msg
        if ok:
            acct.last_connected = pk_now()
        db.session.commit()
    except Exception:
        db.session.rollback()
    return jsonify({'success': ok, 'message': msg})


@app.route('/ufone/settings/start-polling', methods=['POST'])
def ufone_settings_start_polling():
    try:
        start_polling(app)
        flash("Background polling shuru ho gayi.", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for('ufone_settings'))


@app.route('/ufone/settings/stop-polling', methods=['POST'])
def ufone_settings_stop_polling():
    try:
        stop_polling()
        flash("Background polling band ho gayi.", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for('ufone_settings'))


# ════════════════════════════════════════════════════════════════════════════
# PK VPS bridge ingest (token auth — no session cookie)
# ════════════════════════════════════════════════════════════════════════════

def _bridge_expected_token() -> str:
    """Prefer UFONE_BRIDGE_TOKEN; else derive from SECRET_KEY (same on Render + VPS)."""
    explicit = (os.environ.get('UFONE_BRIDGE_TOKEN') or '').strip()
    if explicit:
        return explicit
    secret = (os.environ.get('SECRET_KEY') or '').strip()
    if not secret:
        return ''
    return hmac.new(secret.encode('utf-8'), b'ufone-bridge-v1', hashlib.sha256).hexdigest()


def _bridge_token_ok() -> bool:
    expected = _bridge_expected_token()
    if not expected:
        return False
    got = (request.headers.get('X-Ufone-Bridge-Token') or '').strip()
    if not got:
        auth = (request.headers.get('Authorization') or '').strip()
        if auth.lower().startswith('bearer '):
            got = auth[7:].strip()
    return bool(got) and hmac.compare_digest(got, expected)


@app.route('/api/ufone/bridge/ingest', methods=['POST'])
@csrf.exempt
def api_ufone_bridge_ingest():
    """Receive Ufone cache payloads from the Pakistan VPS bridge worker."""
    if not _bridge_expected_token():
        return jsonify({'ok': False, 'error': 'bridge token not configured'}), 503
    if not _bridge_token_ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    account_id = payload.get('account_id') or request.args.get('account_id', type=int)
    try:
        account_id = int(account_id)
    except (TypeError, ValueError):
        account_id = 0
    if not account_id:
        return jsonify({'ok': False, 'error': 'account_id required'}), 400

    acct = UfoneAccount.query.get(account_id)
    if not acct or not acct.is_active:
        return jsonify({'ok': False, 'error': 'account not found or inactive'}), 404

    try:
        from services.ufone_service import ingest_bridge_payload
        result = ingest_bridge_payload(account_id, payload)
        try:
            acct.last_connected = pk_now()
            acct.last_error = None
            db.session.commit()
        except Exception:
            db.session.rollback()
        return jsonify({'ok': True, 'result': result})
    except Exception as e:
        logger.exception('bridge ingest failed')
        try:
            acct.last_error = str(e)[:500]
            db.session.commit()
        except Exception:
            db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)[:300]}), 500


@app.route('/api/ufone/bridge/health', methods=['GET'])
@csrf.exempt
def api_ufone_bridge_health():
    """Lightweight health check for the VPS worker (token required)."""
    if not _bridge_token_ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    from services.ufone_service import bridge_only_mode, is_polling
    return jsonify({
        'ok': True,
        'bridge_only': bridge_only_mode(),
        'polling': is_polling(),
        'time': pk_now().isoformat(),
    })
