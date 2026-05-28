"""Resolve Back navigation — return to hub or Report Centre where the user opened the page (not browser history)."""
from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from flask import request, session, url_for

REPORTS_NAV_FROM = 'reports'
HISTORY_BACK = 'javascript:history.back()'
SESSION_NAV_BACK_HREF = 'nav_back_href'
SESSION_NAV_BACK_SCOPE = 'nav_back_scope'
SESSION_NAV_RETURN_BASE = 'nav_return_base'

# Analytics / reports that live primarily under Report Centre (not hub default for back)
REPORT_CENTRE_ONLY_ENDPOINTS = frozenset({
    'speed_monitoring_report', 'speed_monitoring_report_export', 'speed_monitoring_report_print',
    'speed_monitoring_report_preview', 'mileage_report', 'mileage_report_export',
    'mileage_report_print', 'mileage_report_preview', 'tracker_difference_report',
    'tracker_difference_report_export', 'tracker_difference_report_print',
    'tracker_difference_report_preview', 'unauthorized_movement_report',
    'unauthorized_movement_report_export', 'unauthorized_movement_report_print',
    'unauthorized_movement_report_preview', 'task_start_delay_report',
    'task_start_delay_report_export', 'task_start_delay_report_print',
    'task_start_delay_report_preview', 'task_turnaround_report', 'task_turnaround_report_export',
    'task_turnaround_report_print', 'task_turnaround_report_preview', 'unexecuted_task_report',
    'unexecuted_task_report_export', 'activity_log_report',
})


def get_nav_from(req=None):
    """URL/form param first; persist to session; else session value."""
    req = req or request
    nf = (req.args.get('nav_from') or req.form.get('nav_from') or '').strip()
    if nf:
        session['nav_from'] = nf
        return nf
    return (session.get('nav_from') or '').strip()


def _is_dashboard_url(url):
    if not url:
        return True
    try:
        path = (urlparse(url).path or '').rstrip('/')
        return path == '' or path.endswith('/dashboard')
    except Exception:
        return False


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
        if _is_dashboard_url(ref):
            return None
        return ref
    except Exception:
        return None


def _referrer_is_hub_or_reports(ref):
    if not ref:
        return False
    try:
        path = urlparse(ref).path or ''
        if '/hub/' in path:
            return True
        reports_path = urlparse(url_for('reports_index')).path.rstrip('/')
        if path.rstrip('/') == reports_path:
            return True
    except Exception:
        pass
    return False


def _hub_slug_for_endpoint(endpoint):
    if not endpoint:
        return None
    try:
        from hub_registry import HUB_ACTIVE_ENDPOINTS
        for slug, eps in HUB_ACTIVE_ENDPOINTS.items():
            if endpoint in eps:
                return slug
    except Exception:
        pass
    return None


def default_back_url_for_endpoint(endpoint):
    """Best default Back target: nav_from session, then owning hub, then Report Centre."""
    if not endpoint:
        return None

    nf = (session.get('nav_from') or '').strip()
    href = _href_from_nav_from(nf)
    if href:
        return href

    slug = _hub_slug_for_endpoint(endpoint)
    if slug:
        try:
            return url_for('module_hub', hub_slug=slug)
        except Exception:
            pass

    if endpoint in REPORT_CENTRE_ONLY_ENDPOINTS:
        try:
            return url_for('reports_index')
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
    if default_url and not _is_dashboard_url(default_url):
        return default_url, default_label
    fb = default_back_url_for_endpoint(request.endpoint)
    if fb:
        return fb, default_label
    try:
        return url_for('reports_index'), 'Back'
    except Exception:
        return '/', default_label


def _href_from_nav_from(nav_from):
    if not nav_from:
        return None
    url, _ = resolve_nav_back(nav_from, None, 'Back')
    if not url or url == HISTORY_BACK or _is_dashboard_url(url):
        return None
    return url


def _lock_nav_back(href, scope_endpoint):
    """Save return URL once for this report (filters/views do not change it)."""
    if not href or href == HISTORY_BACK or _is_dashboard_url(href):
        return
    session[SESSION_NAV_BACK_HREF] = href
    if scope_endpoint:
        session[SESSION_NAV_BACK_SCOPE] = scope_endpoint


def _resolve_origin_href(endpoint):
    """Best back target for a report page — hub, Report Centre, or last hub/reports visit."""
    nf = session.get('nav_from') or ''
    href = _href_from_nav_from(nf)
    if href:
        return href
    base = session.get(SESSION_NAV_RETURN_BASE)
    if base and not _is_dashboard_url(base):
        return base
    ref = _safe_referrer_url()
    if ref and _referrer_is_hub_or_reports(ref):
        return ref
    return default_back_url_for_endpoint(endpoint)


def sync_nav_from_session():
    """On report open: lock where user came from. Hub/Report Centre store their URL for the next open."""
    nf = (request.args.get('nav_from') or request.form.get('nav_from') or '').strip()

    if request.endpoint == 'module_hub':
        slug = (request.view_args or {}).get('hub_slug')
        if slug:
            session['nav_from'] = f'hub:{slug}'
        session[SESSION_NAV_RETURN_BASE] = request.url
        session.pop(SESSION_NAV_BACK_HREF, None)
        session.pop(SESSION_NAV_BACK_SCOPE, None)
        return

    if request.endpoint == 'reports_index':
        session['nav_from'] = REPORTS_NAV_FROM
        session[SESSION_NAV_RETURN_BASE] = request.url
        session.pop(SESSION_NAV_BACK_HREF, None)
        session.pop(SESSION_NAV_BACK_SCOPE, None)
        return

    if request.endpoint == 'dashboard':
        session.pop(SESSION_NAV_BACK_HREF, None)
        session.pop(SESSION_NAV_BACK_SCOPE, None)
        return

    endpoint = request.endpoint or ''
    if not endpoint:
        return

    # Click from hub/reports tile (?nav_from=...) — save origin immediately
    if nf:
        session['nav_from'] = nf
        href = _href_from_nav_from(nf) or session.get(SESSION_NAV_RETURN_BASE)
        if not href:
            href = default_back_url_for_endpoint(endpoint)
        if href:
            _lock_nav_back(href, endpoint)
        return

    # Filter / View on same report — keep first locked URL
    if session.get(SESSION_NAV_BACK_SCOPE) == endpoint and session.get(SESSION_NAV_BACK_HREF):
        locked = session.get(SESSION_NAV_BACK_HREF)
        if locked and not _is_dashboard_url(locked):
            return

    href = _resolve_origin_href(endpoint)
    if href:
        _lock_nav_back(href, endpoint)


def _pick_final_back_url(default_url, nav_from):
    """Always locked session URL; never dashboard or history.back()."""
    locked = session.get(SESSION_NAV_BACK_HREF)
    if locked and not _is_dashboard_url(locked):
        return locked

    href = _href_from_nav_from(nav_from or session.get('nav_from') or '')
    if not href:
        href = session.get(SESSION_NAV_RETURN_BASE)
    if href and _is_dashboard_url(href):
        href = None
    if not href and default_url and not _is_dashboard_url(default_url):
        href = default_url
    if not href:
        href = default_back_url_for_endpoint(request.endpoint)
    if not href:
        try:
            href = url_for('reports_index')
        except Exception:
            href = None
    if not href:
        slug = _hub_slug_for_endpoint(request.endpoint)
        if slug:
            try:
                href = url_for('module_hub', hub_slug=slug)
            except Exception:
                href = None
    if href and not _is_dashboard_url(href):
        _lock_nav_back(href, request.endpoint)
    if href:
        return href
    try:
        return url_for('reports_index')
    except Exception:
        return default_url if default_url and not _is_dashboard_url(default_url) else None


def nav_back_context(default_url=None, default_label='Back', req=None, show_without_nav_from=True):
    """Always returns nav_back_url so templates can force-show Back."""
    del show_without_nav_from
    del req
    nf = get_nav_from()
    final_url = _pick_final_back_url(default_url, nf)
    return {
        'nav_back_url': final_url,
        'nav_back_label': default_label,
        'nav_from': nf or '',
        'nav_back_use_history': False,
    }


def build_auto_nav_back():
    """Global template fallback when a route omits nav_back_url."""
    nf = get_nav_from()
    final_url = _pick_final_back_url(None, nf)
    return {
        'nav_back_url_auto': final_url,
        'nav_back_label_auto': 'Back',
        'nav_from': nf or '',
        'nav_back_use_history': False,
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
    from urllib.parse import quote
    nf = nav_from if nav_from is not None else get_nav_from(req)
    return ('&nav_from=' + quote(nf, safe='')) if nf else ''


def hub_nav_from(slug):
    return f'hub:{slug}'


def merge_nav_from_into_url(url, nav_from=None):
    """Append nav_from query param so refresh/bookmark keeps Back origin."""
    nf = (nav_from if nav_from is not None else get_nav_from() or '').strip()
    if not nf or not url:
        return url
    try:
        parts = urlparse(url)
        q = parse_qs(parts.query, keep_blank_values=True)
        q['nav_from'] = [nf]
        new_query = urlencode(q, doseq=True)
        return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))
    except Exception:
        return url
