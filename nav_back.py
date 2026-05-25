"""Resolve Back navigation from hub / Report Centre via nav_from query param."""
from __future__ import annotations

from urllib.parse import quote

from flask import request, url_for

REPORTS_NAV_FROM = 'reports'


def get_nav_from(req=None):
    """Query/form param first, then session (survives POST filters and redirects)."""
    from flask import session
    req = req or request
    nf = (req.args.get('nav_from') or req.form.get('nav_from') or '').strip()
    if not nf:
        nf = (session.get('nav_from') or '').strip()
    return nf


def sync_nav_from_session():
    """Remember navigation origin from URL, hub page, or Report Centre."""
    from flask import session
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


def default_back_url_for_endpoint(endpoint):
    """Fallback Back target when nav_from is missing (sidebar / bookmark)."""
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


def build_auto_nav_back():
    """Context for templates: always compute a Back URL for the current page."""
    from flask import request as req
    ep = req.endpoint or ''
    default = default_back_url_for_endpoint(ep)
    if not default:
        return {'nav_back_url_auto': None, 'nav_back_label_auto': 'Back', 'nav_from': get_nav_from()}
    nf = get_nav_from()
    url, label = resolve_nav_back(nf, default)
    return {'nav_back_url_auto': url, 'nav_back_label_auto': label, 'nav_from': nf}


def preserve_nav_from(params=None, req=None):
    """Copy nav_from from current request into url_for kwargs / redirect params."""
    out = dict(params or {})
    nf = get_nav_from(req)
    if nf:
        out['nav_from'] = nf
    return out


def resolve_nav_back(nav_from, default_url, default_label='Back'):
    """Return (url, label). nav_from: reports | hub:<slug>."""
    if nav_from == REPORTS_NAV_FROM:
        try:
            return url_for('reports_index'), 'Back'
        except Exception:
            pass
    if nav_from.startswith('hub:'):
        slug = nav_from[4:].strip()
        if slug:
            try:
                from hub_registry import HUBS
                if slug in HUBS:
                    return url_for('module_hub', hub_slug=slug), 'Back'
            except Exception:
                pass
    return default_url, default_label


def nav_back_context(default_url, default_label='Back', req=None, show_without_nav_from=True):
    """
    Template context: nav_back_url, nav_back_label, nav_from.
    Back is shown by default; resolves hub/reports when nav_from is set (or in session).
    """
    nf = get_nav_from(req)
    if not nf and not show_without_nav_from:
        return {'nav_back_url': None, 'nav_back_label': 'Back', 'nav_from': ''}
    url, label = resolve_nav_back(nf or '', default_url, default_label)
    if not nf:
        return {'nav_back_url': default_url, 'nav_back_label': default_label, 'nav_from': ''}
    return {'nav_back_url': url, 'nav_back_label': label, 'nav_from': nf}


def nav_from_amp(nav_from=None, req=None):
    """Append &nav_from=... for template hrefs (empty if none)."""
    nf = nav_from if nav_from is not None else get_nav_from(req)
    return ('&nav_from=' + quote(nf, safe='')) if nf else ''


def hub_nav_from(slug):
    return f'hub:{slug}'
