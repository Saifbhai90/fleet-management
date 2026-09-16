import os, re, sys
os.environ.setdefault('SKIP_STARTUP_TASKS', '1')
sys.path.insert(0, os.getcwd())
from app import app
c = app.test_client()
with c.session_transaction() as s:
    s['user_id'] = 1
    s['user'] = 'master'
    s['username'] = 'master'
    s['is_master'] = True
r = c.get('/task-report/pending')
html = r.get_data(as_text=True)
print('pending_status', r.status_code)
print('has_cascade_attr', 'data-cascade-child' in html)
m = re.search(r'fleet_core\.js\?v=([^"&]+)', html)
print('fleet_core_v', m.group(1) if m else None)
m2 = re.search(r'fleet_styles\.css\?v=([^"&]+)', html)
print('fleet_styles_v', m2.group(1) if m2 else None)
base = open('templates/base.html', encoding='utf-8').read()
print('safety_skips_lazy', "getAttribute('data-ts-lazy')" in base or 'data-ts-lazy' in base)
r2 = c.get('/api/cascade/projects?parent=0')
print('cascade_empty', r2.status_code, r2.get_json())
r3 = c.get('/unexecuted-task-report')
h3 = r3.get_data(as_text=True)
print('unexecuted_status', r3.status_code)
print('unexecuted_lazy', 'data-ts-lazy="1"' in h3)
r4 = c.get('/driver-attendance/mark')
print('att_mark_status', r4.status_code)
print('att_mark_lazy', b'data-ts-lazy="1"' in r4.data)
