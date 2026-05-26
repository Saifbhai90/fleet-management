"""Resolve Back navigation — hub / Report Centre / referrer / browser history fallback."""
from __future__ import annotations

from urllib.parse import quote, urlparse

from flask import request, session, url_for

REPORTS_NAV_FROM = 'reports'
HISTORY_BACK = 'javascript:history.back()'


def get_nav_from(req=None):
    """URL/form param first; persist to session; else session value."""
    req = req or request
    nf = (req.args.get('nav_from') or req.form.get('nav_from') or '').strip()
    if nf:
        session['nav_from'] = nf
        return nf
    return (session.get('nav_from') or '').strip()


def sync_nav_from_session():
    """Remember navigation origin from URL, hub page, or Report Centre."""
    nf = (request.args.get('nav_from') or request.form.get('nav_from') or '').strip()
    if nf:
        session['nav_from'] = nf
        return
    if request.endpoint == 'module_hub':
        slug = (request.view_args or {}).get('hub_slug')
        if slug:
            session['nav_from'] = f'hub:{slug}'
    elif request.endpoint == 'reports_index':
        session['nav_from'] = REPORTS_NAV_FROM


def _safe_referrer_url():
    """Same-host referrer only (open-redirect safe)."""
    ref = request.referrer
    if not ref or not isinstance(ref, str):
        return None
    try:
        cur = urlparse(request.url)
        prev = urlparse(ref)
        if prev.scheme not in ('http', 'https'):
            return None
        host = (request.host or '').split(':')[0].lower()
        ref_host = (prev.netloc or '').split(':')[0].lower()
        if not ref_host or (host and ref_host != host):
            return None
        if prev.path == cur.path and prev.query == cur.query:
            return None
        return ref
    except Exception:
        return None


def default_back_url_for_endpoint(endpoint):
    """Sensible default when nav_from and referrer are unavailable."""
    if not endpoint:
        return None
    report_endpoints = {
        'speed_monitoring_report', 'speed_monitoring_report_export', 'speed_monitoring_report_print',
        'speed_monitoring_report_preview', 'mileage_report', 'mileage_report_export', 'mileage_report_print',
        'mileage_report_preview', 'tracker_difference_report', 'tracker_difference_report_export',
        'tracker_difference_report_print', 'tracker_difference_report_preview',
        'unauthorized_movement_report', 'unauthorized_movement_report_export',
        'unauthorized_movement_report_print', 'unauthorized_movement_report_preview',
        'task_start_delay_report', 'task_start_delay_report_export', 'task_start_delay_report_print',
        'task_start_delay_report_preview', 'task_turnaround_report', 'task_turnaround_report_export',
        'task_turnaround_report_print', 'task_turnaround_report_preview', 'unexecuted_task_report',
        'unexecuted_task_report_export', 'driver_attendance_report', 'driver_attendance_daily_report',
        'driver_attendance_tra_report', 'red_task_list', 'red_task_summary', 'red_task_summary_detail',
        'without_task_list', 'task_report_logbook_cover', 'task_report_logbook_view',
        'task_report_logbook_view_all', 'task_report_list',
    }
    if endpoint in report_endpoints:
        try:
            return url_for('reports_index')
        except Exception:
            pass
    try:
        from hub_registry import HUB_ACTIVE_ENDPOINTS
        for slug, eps in HUB_ACTIVE_ENDPOINTS.items():
            if endpoint in eps:
                return url_for('module_hub', hub_slug=slug)
    except Exception:
        pass
    return None


def resolve_nav_back(nav_from, default_url, default_label='Back'):
    """Return (url, label). nav_from: reports | hub:<slug>."""
    if nav_from == REPORTS_NAV_FROM:
        try:
            return url_for('reports_index'), 'Back'
        except Exception:
            pass
    if nav_from and nav_from.startswith('hub:'):
        slug = nav_from[4:].strip()
        if slug:
            try:
                from hub_registry import HUBS
                if slug in HUBS:
                    return url_for('module_hub', hub_slug=slug), 'Back'
            except Exception:
                pass
    return default_url, default_label


def _current_endpoint_base_url():
    """Same route without query string — used after filter/view so Back does not rely on history.back()."""
    if not request.endpoint:
        return None
    try:
        return url_for(request.endpoint)
    except Exception:
        return None


def _pick_final_back_url(default_url, nav_from):
    """Hub/reports → safe referrer → base route (no query) → default hub → history."""
    if not default_url:
        default_url = default_back_url_for_endpoint(request.endpoint)
    if not default_url:
        try:
            default_url = url_for('dashboard')
        except Exception:
            default_url = '/'

    url, _label = resolve_nav_back(nav_from, default_url, 'Back')

    if nav_from:
        return url

    ref = _safe_referrer_url()
    if ref:
        return ref

    # Filter/view pages: direct link beats history.back() (avoids bfcache + stuck View "Loading…")
    if request.args:
        base = _current_endpoint_base_url()
        if base:
            return base

    if url and url not in ('/', ''):
        return url

    return HISTORY_BACK


def nav_back_context(default_url=None, default_label='Back', req=None, show_without_nav_from=True):
    """Always returns nav_back_url so templates can force-show Back."""
    del show_without_nav_from  # kept for callers; back is always shown
    nf = get_nav_from(req)
    final_url = _pick_final_back_url(default_url, nf)
    return {
        'nav_back_url': final_url,
        'nav_back_label': default_label,
        'nav_from': nf or '',
        'nav_back_use_history': final_url == HISTORY_BACK,
    }


def build_auto_nav_back():
    """Global template fallback when a route omits nav_back_url."""
    nf = get_nav_from()
    final_url = _pick_final_back_url(None, nf)
    return {
        'nav_back_url_auto': final_url,
        'nav_back_label_auto': 'Back',
        'nav_from': nf or '',
        'nav_back_use_history': final_url == HISTORY_BACK,
    }


def hub_nav_back_context(hub_slug, fallback_endpoint=None, default_label='Back'):
    """Back to module hub when opened from hub; else list/page fallback."""
    if fallback_endpoint:
        try:
            default_url = url_for(fallback_endpoint)
        except Exception:
            default_url = url_for('module_hub', hub_slug=hub_slug)
    else:
        default_url = url_for('module_hub', hub_slug=hub_slug)
    return nav_back_context(default_url, default_label)


def preserve_nav_from(params=None, req=None):
    out = dict(params or {})
    nf = get_nav_from(req)
    if nf:
        out['nav_from'] = nf
    return out


def nav_from_amp(nav_from=None, req=None):
    nf = nav_from if nav_from is not None else get_nav_from(req)
    return ('&nav_from=' + quote(nf, safe='')) if nf else ''


def hub_nav_from(slug):
    return f'hub:{slug}'
