"""Static-only inventory: migrated vs KEEP-CUSTOM (no Flask boot)."""
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
T = os.path.join(ROOT, 'templates')

MIGRATED = [
    'task_report_pending.html',
    'task_report_vehicle_period_detail.html',
    'unexecuted_task_report.html',
    'maintenance_baseline_alert_report.html',
    'vehicle_reading_setup_list.html',
    'maintenance_expense_history.html',
    'without_task_list.html',
    'without_task_form.html',
    'without_task_edit.html',
    'red_task_list.html',
    'red_task_form.html',
    'red_task_edit.html',
    'penalty_record_list.html',
    'penalty_record_form.html',
    'logbook_cover_list.html',
    'oil_expense_list.html',
    'fuel_expense_list.html',
    'maintenance_expense_list.html',
    'maintenance_work_order_list.html',
    'oil_work_order_list.html',
    'oil_work_order_form.html',
    'maintenance_work_order_form.html',
]
KEEP = [
    'oil_expense_form.html',
    'maintenance_expense_form.html',
    'vehicle_reading_setup_form.html',
    os.path.join('workspace', 'mpg_report.html'),
]

fails = 0
print('=== MIGRATED ===')
for f in MIGRATED:
    p = os.path.join(T, f)
    src = open(p, encoding='utf-8').read()
    has = ('data-cascade-child' in src) or ('data_cascade_child' in src)
    url = ('data-cascade-url' in src) or ('data_cascade_url' in src)
    hand = 'get_projects_by_district' in src
    ok = has and url and not hand
    print(('OK' if ok else 'FAIL'), f)
    if not ok:
        fails += 1

print('=== KEEP (API unify, custom JS) ===')
for f in KEEP:
    p = os.path.join(T, f)
    src = open(p, encoding='utf-8').read()
    legacy = 'get_projects_by_district' in src
    api = '/api/cascade/projects' in src
    ok = (not legacy) and api
    print(('OK' if ok else 'FAIL'), f, 'api=%s legacy=%s' % (api, legacy))
    if not ok:
        fails += 1

fuel = open(os.path.join(ROOT, 'static', 'js', 'fuel_cascade.js'), encoding='utf-8').read()
ok_fuel = ('get_projects_by_district' not in fuel) and ('/api/cascade/projects' in fuel)
print(('OK' if ok_fuel else 'FAIL'), 'fuel_cascade.js')
if not ok_fuel:
    fails += 1

base = open(os.path.join(T, 'base.html'), encoding='utf-8').read()
core = open(os.path.join(ROOT, 'static', 'js', 'core', 'fleet_core.js'), encoding='utf-8').read()
checks = [
    ("hash fleet_core", "fleet_static_hash('js/core/fleet_core.js')" in base),
    ("hash fuel_cascade includes", "fleet_static_hash('js/fuel_cascade.js')" in open(os.path.join(T, 'fuel_expense_form.html'), encoding='utf-8').read()),
    ("hash fm_hub", "fleet_static_hash('css/fm_hub_pages.css')" in base),
    ("safety skips lazy", "data-ts-lazy" in base and "getAttribute('data-ts-lazy')" in base),
    ("LC cascade helpers", '_fleetParseLocationCascade' in core),
    ("truncation hint", 'ts-truncation-hint' in core),
    ("native EndCascade", core.count('window.fleetEndCascade(sel)') >= 2),
]
print('=== CORE ===')
for name, ok in checks:
    print(('OK' if ok else 'FAIL'), name)
    if not ok:
        fails += 1

print('FAILS', fails)
raise SystemExit(1 if fails else 0)
