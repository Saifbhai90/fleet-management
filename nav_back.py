"""Back navigation — same hub mapping as sidebar highlight (hub_registry), plus nav_from override."""
from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from flask import request, session, url_for

REPORTS_NAV_FROM = 'reports'
REPORT_CENTRE_URL_KEY = 'reports_index'

# Human-readable labels for each nav_from origin key.
# hub:<slug> labels are resolved dynamically from hub_registry.HUBS at runtime.
NAV_FROM_LABELS: dict[str, str] = {
    'reports': 'Report Center',
}


def nav_back_label_for(nav_from: str | None) -> str:
    """Resolve a human-readable source name for the given nav_from key.

    Examples:
        'reports'        -> 'Report Center'
        'hub:attendance' -> 'Attendance Hub'
        'hub:finance'    -> 'Finance Hub'
        None / unknown   -> 'Back'
    """
    nf = (nav_from or '').strip()
    if not nf:
        return 'Back'
    if nf in NAV_FROM_LABELS:
        return NAV_FROM_LABELS[nf]
    if nf.startswith('hub:'):
        slug = nf[4:].strip()
        try:
            from hub_registry import HUBS
            hub = HUBS.get(slug)
            if hub and hub.get('title'):
                return hub['title'] + ' Hub'
        except Exception:
            pass
        return slug.replace('-', ' ').title() + ' Hub'
    return 'Back'


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


def _reports_index_url():
    try:
        return url_for(REPORT_CENTRE_URL_KEY)
    except Exception:
        return None


def back_url_for_request(endpoint=None, nav_from=None, default_url=None):
    """
    Resolve Back target — mirrors sidebar logic:
    1) nav_from=reports → Report Centre
    2) nav_from=hub:<slug> → that hub
    3) current endpoint's owning hub (hub_slug_for_endpoint) — same as sidebar active-link
    4) route default_url / Report Centre fallback
    """
    ep = endpoint or (request.endpoint if request else None)
    nf = (nav_from if nav_from is not None else get_nav_from() or '').strip()

    if nf == REPORTS_NAV_FROM:
        u = _reports_index_url()
        if u:
            return u

    if nf.startswith('hub:'):
        from hub_registry import hub_url_for_slug
        u = hub_url_for_slug(nf[4:].strip())
        if u:
            return u

    from hub_registry import hub_url_for_endpoint
    u = hub_url_for_endpoint(ep)
    if u and not _is_dashboard_url(u):
        return u

    if default_url and not _is_dashboard_url(default_url):
        return default_url

    u = _reports_index_url()
    return u or '/'


def nav_back_context(default_url=None, default_label=None, req=None, show_without_nav_from=True):
    del show_without_nav_from
    del req
    nf = get_nav_from()
    from hub_registry import hub_slug_for_endpoint
    final_url = back_url_for_request(nav_from=nf, default_url=default_url)
    label = default_label if default_label is not None else nav_back_label_for(nf)
    return {
        'nav_back_url': final_url,
        'nav_back_label': label,
        'nav_from': nf or '',
        'nav_back_hub_slug': hub_slug_for_endpoint(request.endpoint) or '',
        'nav_back_use_history': False,
    }


def build_auto_nav_back():
    nf = get_nav_from()
    from hub_registry import hub_slug_for_endpoint
    return {
        'nav_back_url_auto': back_url_for_request(nav_from=nf),
        'nav_back_label_auto': nav_back_label_for(nf),
        'nav_from': nf or '',
        'nav_back_hub_slug': hub_slug_for_endpoint(request.endpoint) or '',
        'nav_back_use_history': False,
    }


def hub_nav_back_context(hub_slug, fallback_endpoint=None, default_label=None):
    try:
        default_url = url_for('module_hub', hub_slug=hub_slug)
    except Exception:
        default_url = None
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


# Keep sync on hub/reports visits so nav_from=reports / hub:X stays accurate when opening tiles
def sync_nav_from_session():
    nf = (request.args.get('nav_from') or request.form.get('nav_from') or '').strip()
    if request.endpoint == 'module_hub':
        slug = (request.view_args or {}).get('hub_slug')
        if slug:
            session['nav_from'] = f'hub:{slug}'
        return
    if request.endpoint == 'reports_index':
        session['nav_from'] = REPORTS_NAV_FROM
        return
    if nf:
        session['nav_from'] = nf
