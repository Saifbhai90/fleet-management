"""Resolve Back navigation from hub / Report Centre via nav_from query param."""
from __future__ import annotations

from urllib.parse import quote

from flask import request, url_for

REPORTS_NAV_FROM = 'reports'


def get_nav_from(req=None):
    req = req or request
    return (req.args.get('nav_from') or req.form.get('nav_from') or '').strip()


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


def nav_back_context(default_url, default_label='Back', req=None, show_without_nav_from=False):
    """
    Template context: nav_back_url, nav_back_label, nav_from.
    When show_without_nav_from is False, nav_back_url is None unless nav_from is set.
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
