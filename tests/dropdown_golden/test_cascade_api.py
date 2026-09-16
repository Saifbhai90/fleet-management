"""Unit checks for GET /api/cascade/<entity> adapter (Flask test client)."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('SKIP_STARTUP_TASKS', '1')

from app import app  # noqa: E402


def test_cascade_unknown_entity_404():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['user'] = 'master'
        sess['username'] = 'master'
        sess['is_master'] = True
    resp = client.get('/api/cascade/not-a-real-entity?parent=1')
    assert resp.status_code == 404
    data = resp.get_json()
    assert data.get('error') == 'unknown_entity'


def test_cascade_projects_empty_parent():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['user'] = 'master'
        sess['username'] = 'master'
        sess['is_master'] = True
    resp = client.get('/api/cascade/projects?parent=0')
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_cascade_vehicles_empty_without_parent():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['user'] = 'master'
        sess['username'] = 'master'
        sess['is_master'] = True
    resp = client.get('/api/cascade/vehicles?parent=0')
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_migrated_templates_have_declarative_cascade():
    """Every intentionally migrated page must declare data-cascade attrs (or WTForms data_cascade_*)."""
    migrated = [
        'templates/task_report_pending.html',
        'templates/task_report_vehicle_period_detail.html',
        'templates/unexecuted_task_report.html',
        'templates/maintenance_baseline_alert_report.html',
        'templates/vehicle_reading_setup_list.html',
        'templates/maintenance_expense_history.html',
        'templates/without_task_list.html',
        'templates/without_task_form.html',
        'templates/without_task_edit.html',
        'templates/red_task_list.html',
        'templates/red_task_form.html',
        'templates/red_task_edit.html',
        'templates/penalty_record_list.html',
        'templates/penalty_record_form.html',
        'templates/logbook_cover_list.html',
        'templates/oil_expense_list.html',
        'templates/fuel_expense_list.html',
        'templates/maintenance_expense_list.html',
        'templates/maintenance_work_order_list.html',
        'templates/oil_work_order_list.html',
        'templates/oil_work_order_form.html',
        'templates/maintenance_work_order_form.html',
    ]
    for rel in migrated:
        path = os.path.join(ROOT, *rel.split('/'))
        src = open(path, encoding='utf-8').read()
        has_html = 'data-cascade-child' in src
        has_wt = 'data_cascade_child' in src
        assert has_html or has_wt, '%s missing cascade attrs' % rel
        assert 'get_projects_by_district' not in src, '%s still has hand fetch' % rel


def test_hybrid_lists_use_location_cascade_source():
    hybrid = [
        'templates/oil_expense_list.html',
        'templates/fuel_expense_list.html',
        'templates/maintenance_expense_list.html',
        'templates/oil_work_order_list.html',
        'templates/maintenance_work_order_list.html',
        'templates/oil_work_order_form.html',
        'templates/maintenance_work_order_form.html',
    ]
    for rel in hybrid:
        src = open(os.path.join(ROOT, *rel.split('/')), encoding='utf-8').read()
        assert 'data-cascade-source="locationCascadeData"' in src, rel
        assert 'data-cascade-cache-prefix=' in src, rel


def test_keep_custom_forms_use_api_cascade_urls():
    """Complex forms keep custom JS but must hit /api/cascade (not legacy paths)."""
    keep = [
        'templates/oil_expense_form.html',
        'templates/maintenance_expense_form.html',
        'templates/vehicle_reading_setup_form.html',
        'templates/workspace/mpg_report.html',
        'static/js/fuel_cascade.js',
    ]
    for rel in keep:
        path = os.path.join(ROOT, *rel.split('/'))
        src = open(path, encoding='utf-8').read()
        assert 'get_projects_by_district' not in src, '%s still uses legacy projects URL' % rel
        assert '/api/cascade/projects' in src, '%s missing /api/cascade/projects' % rel


def test_core_supports_lc_cache_and_truncation_hint():
    src = open(os.path.join(ROOT, 'static', 'js', 'core', 'fleet_core.js'), encoding='utf-8').read()
    assert '_fleetParseLocationCascade' in src
    assert '_fleetCascadeCacheKey' in src
    assert 'data-cascade-source' in src
    assert 'ts-truncation-hint' in src
    assert 'Showing first 300' in src


def test_base_uses_content_hash_for_core_assets():
    base = open(os.path.join(ROOT, 'templates', 'base.html'), encoding='utf-8').read()
    assert "fleet_static_hash('js/core/fleet_core.js')" in base
    assert "fleet_static_hash('css/core/fleet_styles.css')" in base
    assert "fleet_static_hash('js/core/fleet_ui.js')" in base
    assert "fleet_static_hash('js/core/fleet_mobile.js')" in base
    assert "fleet_static_hash('css/fm_hub_pages.css')" in base
    assert "fleet_static_hash('js/fleet_notifications_ui.js')" in base
    fuel_form = open(os.path.join(ROOT, 'templates', 'fuel_expense_form.html'), encoding='utf-8').read()
    assert "fleet_static_hash('js/fuel_cascade.js')" in fuel_form


def test_safety_net_skips_lazy_selects():
    base = open(os.path.join(ROOT, 'templates', 'base.html'), encoding='utf-8').read()
    assert 'data-ts-lazy' in base
    assert "getAttribute('data-ts-lazy')" in base or 'Lazy row selects intentionally stay unwrapped' in base
