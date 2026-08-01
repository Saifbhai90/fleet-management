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
    load_vehicles_from_db, load_today_in_process_tasks,
    get_task_detail_cached, save_task_detail_cache,
    invalidate_task_detail_cache, _sync_emergency_report_live,
    get_tehsils_cached, get_ucs_cached, fetch_maintenance,
    fetch_maintenance_log, fetch_maintenance_history,
    fetch_report_cached, note_ui_activity,
    encrypt_password, decrypt_password,
    create_account, update_account, delete_account,
    test_connection, start_polling, stop_polling, is_polling,
    bridge_only_mode, build_task_detail_from_db,
    needs_vps_task_detail_refresh, resolve_task_live_status,
    mark_detail_cache_status, _status_is_closed,
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
    # Slim first paint: do NOT load the full vehicle list into HTML (hundreds of
    # <option>s + TomSelect init). Vehicles fill after paint via /api/ufone/positions.
    vehicles = []
    tasks = []
    stats = {'total': 0, 'active': 0, 'inactive': 0, 'with_gps': 0, 'without_gps': 0}
    counts = {}
    error = None

    if acct_id:
        try:
            # Today's open EMG rows only — small seed for Task List.
            tasks = load_today_in_process_tasks(acct_id) or []
            # SQL aggregates for KPI cards — painted in HTML, no waiting on JS fetch.
            try:
                counts = fetch_dashboard_counts(acct_id) or {}
                stats['total'] = int(counts.get('total_ambulances') or 0)
            except Exception as ce:
                logger.warning(f"dashboard counts seed failed: {ce}")
                counts = {}
            if not tasks and not counts:
                error = (
                    "Cache empty — live sync running in background. "
                    "Click Refresh in a few seconds, or open Settings → Start Polling."
                )

            # Fire-and-forget warm — skip when PK VPS bridge owns Ufone HTTP.
            if not bridge_only_mode():
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

    districts = []
    if acct_id:
        try:
            districts = get_districts_cached(acct_id) or []
        except Exception:
            districts = []

    return render_template(
        'ufone/dashboard.html',
        vehicles=vehicles, tasks=tasks, stats=stats, counts=counts,
        incomplete_count=incomplete_count,
        districts=districts,
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
        from services.ufone_service import bridge_only_mode
        if bridge_only_mode():
            # PK VPS owns live Ufone — Refresh only reloads DB/memory snapshot.
            vehicles, tasks, stats = load_dashboard_snapshot(acct_id)
            return jsonify({
                'vehicles': vehicles,
                'tasks': tasks,
                'stats': stats,
                'bridge_only': True,
                'refreshed_at': pk_now().isoformat(),
            })
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
    Falls back to EMG/vehicle DB compose, then UfoneTaskCache snapshot.
    ?live=1: live Ufone fetch — skipped when UFONE_BRIDGE_ONLY (PK VPS owns HTTP).
    """
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account'}), 400

    want_live = request.args.get('live') == '1'
    bridge = bridge_only_mode()

    def _pack(detail, comments, *, from_cache=False, warning=None):
        payload = {
            'detail': detail or {},
            'comments': comments or [],
            'from_cache': from_cache,
            'bridge_only': bridge,
            'needs_vps_refresh': needs_vps_task_detail_refresh(acct_id, task_id),
        }
        if warning:
            payload['warning'] = warning
        return jsonify(payload)

    # Fallback compose (EMG/list) when getTaskDetail cache missing
    composed = build_task_detail_from_db(acct_id, task_id)

    # 1. Full detail+comments from getTaskDetail cache (close fields included)
    detail, comments, _synced = get_task_detail_cached(acct_id, task_id)
    if detail and not want_live:
        return _pack(detail, comments, from_cache=True)

    # 2. Compose from EMG + vehicle (+ list cache) — works offline / bridge
    if composed and not want_live:
        # Prefer richer detail cache if present
        if detail:
            merged = dict(composed)
            merged.update({k: v for k, v in detail.items() if v not in (None, '')})
            return _pack(merged, comments, from_cache=True)
        return _pack(composed, comments or [], from_cache=True)

    snap = _cached_task_detail(acct_id, task_id)
    if snap and not want_live:
        if composed:
            merged = dict(snap)
            merged.update({k: v for k, v in composed.items() if v not in (None, '')})
            return _pack(merged, [], from_cache=True)
        return _pack(snap, [], from_cache=True)

    # 3. Live Ufone — not available from Render in bridge mode
    if bridge:
        best = detail or composed or snap or {}
        if best:
            return _pack(best, comments or [], from_cache=True)
        return jsonify({
            'error': 'Task detail not in bridge cache yet — wait for next VPS sync',
            'detail': {}, 'comments': [], 'bridge_only': True,
        }), 404

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
        detail = {}
        comments = []

    if detail:
        save_task_detail_cache(acct_id, task_id, detail, comments)
        return _pack(detail, comments, warning=live_error)

    best = get_task_detail_cached(acct_id, task_id)[0] or composed or snap or {}
    if best:
        return _pack(best, comments or [], from_cache=True,
                     warning=live_error or 'Live fetch unavailable')

    return jsonify({'error': live_error or 'Task not found',
                    'detail': {}, 'comments': []}), 502


def _vps_detail_base_url() -> str:
    return (
        os.environ.get('UFONE_VPS_DETAIL_URL')
        or os.environ.get('UFONE_BRIDGE_DETAIL_URL')
        or 'http://185.228.92.23:8787'
    ).strip().rstrip('/')


def _request_vps_task_detail(account_id: int, task_id: int) -> dict:
    """Ask PK VPS to fetch getTaskDetail+comments and write Postgres."""
    import requests
    token = _bridge_expected_token()
    if not token:
        return {'ok': False, 'error': 'bridge token not configured'}
    url = f'{_vps_detail_base_url()}/task-detail'
    try:
        r = requests.post(
            url,
            headers={
                'X-Ufone-Bridge-Token': token,
                'User-Agent': 'fleet-manager-render/1.0',
                'Content-Type': 'application/json',
            },
            json={'task_id': str(task_id), 'account_id': int(account_id)},
            timeout=22,
        )
        try:
            data = r.json() if r.content else {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if r.status_code >= 400 and not data.get('error'):
            data['ok'] = False
            data['error'] = f'VPS HTTP {r.status_code}: {(r.text or "")[:160]}'
        return data
    except Exception as e:
        return {'ok': False, 'error': f'VPS unreachable: {e}'[:200]}


@app.route('/api/ufone/task/<int:task_id>/vps-refresh')
def api_ufone_task_vps_refresh(task_id):
    """Backend: ask VPS for live detail+comments, update DB, return payload.

    Policy:
      - Open / in-process → always hit VPS
      - Closed → VPS only once (first open after close); then DB only
    """
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account', 'detail': {}, 'comments': []}), 400

    composed = build_task_detail_from_db(acct_id, task_id) or {}

    want_vps = needs_vps_task_detail_refresh(acct_id, task_id)
    if not want_vps:
        db_detail, db_comments, _synced = get_task_detail_cached(acct_id, task_id)
        best = db_detail or composed or _cached_task_detail(acct_id, task_id) or {}
        return jsonify({
            'detail': best,
            'comments': db_comments or [],
            'from_cache': True,
            'bridge_only': bridge_only_mode(),
            'vps_refreshed': False,
            'vps_skipped': True,
            'needs_vps_refresh': False,
            'warning': None,
        })

    vps = _request_vps_task_detail(acct_id, task_id)
    detail = vps.get('detail') if isinstance(vps.get('detail'), dict) else None
    comments = vps.get('comments') if isinstance(vps.get('comments'), list) else None

    # Prefer DB read after VPS write (source of truth)
    db_detail, db_comments, _synced = get_task_detail_cached(acct_id, task_id)
    if db_detail:
        detail = db_detail
        comments = db_comments if db_comments is not None else (comments or [])
    elif detail:
        # VPS returned body but DB read missed — persist on Render too
        try:
            save_task_detail_cache(acct_id, task_id, detail, comments or [])
        except Exception:
            pass

    # After a successful post-close fetch, stamp cache closed so next open skips VPS
    live_st = resolve_task_live_status(acct_id, task_id)
    if vps.get('ok') and _status_is_closed(live_st):
        stamp = live_st
        if detail and isinstance(detail, dict) and _status_is_closed(detail.get('Status')):
            stamp = str(detail.get('Status')).strip()
        mark_detail_cache_status(acct_id, task_id, stamp)

    if detail:
        return jsonify({
            'detail': detail,
            'comments': comments or [],
            'from_cache': False,
            'bridge_only': bridge_only_mode(),
            'vps_refreshed': bool(vps.get('ok')),
            'vps_skipped': False,
            'needs_vps_refresh': needs_vps_task_detail_refresh(acct_id, task_id),
            'warning': None if vps.get('ok') else (vps.get('error') or 'VPS refresh incomplete'),
        })

    # Fallback: whatever we already have locally
    snap = _cached_task_detail(acct_id, task_id) or {}
    best = db_detail or composed or snap
    if best:
        return jsonify({
            'detail': best,
            'comments': db_comments or [],
            'from_cache': True,
            'bridge_only': bridge_only_mode(),
            'vps_refreshed': False,
            'vps_skipped': False,
            'needs_vps_refresh': True,
            'warning': vps.get('error') or 'VPS refresh failed — showing DB data',
        })
    return jsonify({
        'error': vps.get('error') or 'Task detail unavailable',
        'detail': {},
        'comments': [],
        'vps_refreshed': False,
        'vps_skipped': False,
        'needs_vps_refresh': True,
    }), 502


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

    Params: from_date, to_date (YYYY-MM-DD), task_id (PHF- optional),
    district (Ufone code), vehicle (reg-no substring),
    status (incomplete/completed/cancelled).
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
    task_id_q = (request.args.get('task_id') or '').strip()
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

    def _norm_task_id(v):
        s = str(v or '').strip().upper()
        if s.startswith('PHF-'):
            s = s[4:]
        return ''.join(ch for ch in s if ch.isalnum())

    if task_id_q:
        needle = _norm_task_id(task_id_q)
        if needle:
            tasks = [
                t for t in tasks
                if needle in _norm_task_id(t.get('task_id') or t.get('id'))
            ]

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

    # Category buckets for KPI cards (after district/vehicle/status filters)
    green = yellow = red = orange = in_process = 0
    for t in tasks:
        cat = str(t.get('category') or '').strip().lower()
        st = str(t.get('status') or '').strip().lower()
        if cat == 'green':
            green += 1
        elif cat == 'yellow':
            yellow += 1
        elif cat == 'red':
            red += 1
        elif cat == 'orange':
            orange += 1
        elif ('incomplete' in st or st == '1'
              or 'in-process' in st or 'in process' in st):
            in_process += 1
    category_counts = {
        'task_total': green + yellow + red + orange + in_process,
        'task_green': green,
        'task_yellow': yellow,
        'task_red': red,
        'task_orange': orange,
        'task_in_process': in_process,
    }

    # Card stats: filtered tasks ki unique ambulances × local vehicle cache
    # (returned for reference — dashboard Total Ambulances KPI is NOT overwritten)
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
        'category_counts': category_counts,
        'vehicle_stats': vehicle_stats,
        'from_date': from_date, 'to_date': to_date,
        'district': district,
    })


def _request_vps_emg_day(account_id: int, day: str) -> dict:
    """Ask PK VPS to fetch one-day Emergency Task Report and upsert Postgres."""
    import requests
    token = _bridge_expected_token()
    if not token:
        return {'ok': False, 'error': 'bridge token not configured'}
    url = f'{_vps_detail_base_url()}/emg-day'
    try:
        r = requests.post(
            url,
            headers={
                'X-Ufone-Bridge-Token': token,
                'User-Agent': 'fleet-manager-render/1.0',
                'Content-Type': 'application/json',
            },
            json={
                'from_date': day,
                'to_date': day,
                'account_id': int(account_id),
            },
            timeout=95,
        )
        try:
            data = r.json() if r.content else {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if r.status_code >= 400 and not data.get('error'):
            data['ok'] = False
            data['error'] = f'VPS HTTP {r.status_code}: {(r.text or "")[:160]}'
        return data
    except Exception as e:
        return {'ok': False, 'error': f'VPS unreachable: {e}'[:200]}


@app.route('/api/ufone/tasks/fetch-old-day', methods=['POST'])
@csrf.exempt
def api_ufone_fetch_old_day():
    """On-demand historical EMG fetch — ONE day only (From must equal To).

    Bridge mode: Render → PK VPS /emg-day → Ufone getAmbulanceTaskReport → DB.
    Local mode: force live fetch via fetch_tasks_report.
    """
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'ok': False, 'error': 'No account'}), 400

    data = request.get_json(silent=True) or {}
    raw_from = (data.get('from_date') or request.form.get('from_date') or '').strip()
    raw_to = (data.get('to_date') or request.form.get('to_date') or '').strip()
    if not raw_from or not raw_to:
        return jsonify({
            'ok': False,
            'error': 'From Date and To Date required',
        }), 400
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', raw_from) or not re.match(r'^\d{4}-\d{2}-\d{2}$', raw_to):
        return jsonify({'ok': False, 'error': 'Dates must be YYYY-MM-DD'}), 400
    try:
        datetime.strptime(raw_from, '%Y-%m-%d')
        datetime.strptime(raw_to, '%Y-%m-%d')
    except ValueError:
        return jsonify({'ok': False, 'error': 'Invalid calendar date'}), 400
    if raw_from != raw_to:
        return jsonify({
            'ok': False,
            'error': 'From Date and To Date must be the same day (1 day only). '
                     'Year-range fetch is blocked to protect Ufone portal load.',
        }), 400

    day = raw_from
    try:
        if bridge_only_mode():
            vps = _request_vps_emg_day(acct_id, day)
            if not vps.get('ok'):
                return jsonify({
                    'ok': False,
                    'error': vps.get('error') or 'VPS fetch failed',
                    'date': day,
                }), 502
            return jsonify({
                'ok': True,
                'date': day,
                'count': int(vps.get('count') or 0),
                'warning': vps.get('warning'),
                'via': 'vps',
            })

        tasks = fetch_tasks_report(
            acct_id, start_date=day, end_date=day, district='', force=True,
        )
        return jsonify({
            'ok': True,
            'date': day,
            'count': len(tasks or []),
            'via': 'live',
        })
    except Exception as e:
        logger.warning('fetch-old-day failed: %s', e)
        return jsonify({'ok': False, 'error': str(e)[:200], 'date': day}), 502


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


@app.route('/api/ufone/maintenance/log')
def api_ufone_maintenance_log():
    """Update Log popup data — same as portal getAmbulanceUnderMaintenance2."""
    acct_id = _get_account_id()
    if not acct_id:
        return jsonify({'error': 'No account', 'records': []}), 400
    mid = request.args.get('id') or ''
    reg_no = (request.args.get('reg_no') or '').strip()
    start_date = (request.args.get('start_date') or '').strip()
    try:
        mid_int = int(mid) if str(mid).strip().isdigit() else None
    except (TypeError, ValueError):
        mid_int = None
    try:
        records = fetch_maintenance_log(
            maint_id=mid_int, reg_no=reg_no, start_date=start_date)
        return jsonify({'records': records, 'count': len(records)})
    except Exception as e:
        logger.warning('maintenance log failed: %s', e)
        return jsonify({'error': str(e)[:200], 'records': []}), 502


@app.route('/ufone/maintenance-history')
def ufone_maintenance_history():
    """Maintenance History — statewide (anonymous) + district filter."""
    acct_id = _get_account_id()
    accounts = _get_all_accounts()
    from_date = _sanitize_date(
        request.args.get('from_date'),
        (pk_date() - timedelta(days=30)).strftime('%Y-%m-%d'))
    to_date = _sanitize_date(
        request.args.get('to_date'), pk_date().strftime('%Y-%m-%d'))
    district = (request.args.get('district') or '').strip()
    records = []
    error = None
    force = request.args.get('force') == '1'
    districts = []
    if acct_id:
        try:
            districts = get_districts_cached(acct_id) or []
        except Exception:
            districts = []
        if not districts:
            try:
                from services.ufone_api_client import UfoneClient
                raw = UfoneClient("anon", "anon").get_districts_anonymous() or []
                districts = []
                for d in raw:
                    if not isinstance(d, dict):
                        continue
                    code = d.get('district_code') or d.get('code')
                    name = (d.get('district_name') or d.get('name') or '').strip()
                    if code is not None and name:
                        districts.append({'code': str(code), 'name': name})
                districts.sort(key=lambda x: x['name'])
            except Exception:
                pass
        try:
            records = fetch_maintenance_history(
                acct_id, from_date=from_date, to_date=to_date,
                district=district, force=force)
        except Exception as e:
            error = str(e)[:300]
    return render_template(
        'ufone/maintenance_history.html',
        records=records, error=error,
        accounts=accounts, current_account_id=acct_id,
        from_date=from_date, to_date=to_date, district=district,
        districts=districts,
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
    from services.ufone_service import bridge_only_mode
    return render_template(
        'ufone/settings.html', accounts=accounts,
        polling_active=polling,
        bridge_only=bridge_only_mode(),
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

    from services.ufone_service import bridge_only_mode
    if bridge_only_mode():
        # Render must NOT call bpocops (TLS cut). Report PK VPS / DB health instead.
        from models import UfoneVehicleCache
        n = UfoneVehicleCache.query.filter_by(account_id=acct_id).count()
        latest = (UfoneVehicleCache.query.filter_by(account_id=acct_id)
                  .order_by(UfoneVehicleCache.updated_at.desc()).first())
        when = latest.updated_at.strftime('%Y-%m-%d %H:%M') if latest and latest.updated_at else 'never'
        ok = n > 0
        msg = (
            f"Bridge mode ON (PK VPS syncs Ufone). "
            f"Render does not login to bpocops. "
            f"Cache: {n} vehicles, last update {when}."
        )
        try:
            acct.last_error = None if ok else 'Bridge cache empty — check VPS ufone-bridge service'
            if ok:
                acct.last_connected = pk_now()
            db.session.commit()
        except Exception:
            db.session.rollback()
        return jsonify({'success': ok, 'message': msg, 'bridge_only': True})

    password = decrypt_password(acct.password_enc)
    ok, msg = test_connection(acct.username, password)
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
        from services.ufone_service import bridge_only_mode
        if bridge_only_mode():
            flash(
                "UFONE_BRIDGE_ONLY=1 — Render polling band rakha. "
                "Live sync PK VPS (ufone-bridge) se hoti hai.",
                "info",
            )
            return redirect(url_for('ufone_settings'))
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
    # Demo environment must never accept live VPS ingest into sample DB.
    try:
        from services.demo_env import is_demo_mode
        if is_demo_mode():
            return False
    except Exception:
        if (os.environ.get('DEMO_MODE') or '').strip().lower() in ('1', 'true', 'yes', 'on'):
            return False
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


@app.route('/api/ufone/bridge/notify', methods=['POST'])
@csrf.exempt
def api_ufone_bridge_notify():
    """Tiny task generate/close events from PK VPS (no bulk payload — avoids OOM)."""
    if not _bridge_expected_token():
        return jsonify({'ok': False, 'error': 'bridge token not configured'}), 503
    if not _bridge_token_ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    events = payload.get('events') or []
    if not isinstance(events, list):
        return jsonify({'ok': False, 'error': 'events must be a list'}), 400
    # Hard cap — never accept bulk report-sized bodies again
    events = [e for e in events if isinstance(e, dict)][:80]
    if not events:
        return jsonify({'ok': True, 'sent': 0})

    try:
        from services.ufone_service import _send_task_event_notifications
        _send_task_event_notifications(events)
        return jsonify({'ok': True, 'sent': len(events)})
    except Exception as e:
        logger.exception('bridge notify failed')
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
