"""Routes for Fleet Tool Workstation (120 client-side utilities)."""
from __future__ import annotations

from flask import jsonify, redirect, render_template, request, session, url_for

from app import app
from tool_workstation.registry import (
    CATEGORY_LABELS,
    TOOLS,
    get_tool,
    tool_public,
    tools_for_category,
    tools_json,
)


def _require_tool_workstation():
    """Master admin or users_manage (Administration hub)."""
    if not session.get('user_id'):
        return False
    if session.get('is_master'):
        return True
    try:
        from auth_utils import user_can_access
        if user_can_access(session.get('permissions') or [], 'users_manage'):
            return True
    except Exception:
        pass
    from flask import flash
    flash('You do not have permission to access Tool Workstation.', 'danger')
    return False


def _administration_nav_back():
    from nav_back import nav_back_context
    try:
        default_url = url_for('module_hub', hub_slug='administration')
    except Exception:
        default_url = None
    return nav_back_context(default_url, 'Back')


@app.route('/admin/tool-workstation')
def tool_workstation_index():
    if not _require_tool_workstation():
        return redirect(url_for('dashboard'))
    return render_template(
        'tool_workstation/index.html',
        tools=TOOLS,
        categories=CATEGORY_LABELS,
        tools_json=tools_json(),
        **_administration_nav_back(),
    )


@app.route('/admin/tool-workstation/tool/<slug>')
def tool_workstation_tool(slug):
    if not _require_tool_workstation():
        return redirect(url_for('dashboard'))
    tool = get_tool(slug)
    if not tool:
        from flask import flash
        flash('Tool not found.', 'warning')
        return redirect(url_for('tool_workstation_index'))
    return render_template(
        'tool_workstation/tool.html',
        tool=tool_public(tool),
        tools_json=tools_json(),
        **_administration_nav_back(),
    )


@app.route('/admin/tool-workstation/api/tools')
def tool_workstation_api_tools():
    if not _require_tool_workstation():
        return jsonify({'error': 'unauthorized'}), 403
    return jsonify({'tools': TOOLS, 'categories': CATEGORY_LABELS})
