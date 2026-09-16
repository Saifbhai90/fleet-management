"""Render-check migrated cascade pages (auth session)."""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault('SKIP_STARTUP_TASKS', '1')

from app import app  # noqa: E402


def main():
    c = app.test_client()
    with c.session_transaction() as s:
        s['user_id'] = 1
        s['user'] = 'master'
        s['username'] = 'master'
        s['is_master'] = True

    pages = [
        '/task-report/pending',
        '/task-report/logbook-cover',
        '/unexecuted-task-report',
        '/maintenance-baseline-alert-report',
        '/expenses/vehicle-reading-setups',
        '/maintenance-expenses/history',
        '/vehicle-move-without-task',
        '/vehicle-move-without-task/new',
        '/red-task',
        '/red-task/new',
        '/penalty-record',
        '/penalty-record/new',
    ]
    fails = 0
    for p in pages:
        r = c.get(p)
        t = r.get_data(as_text=True)
        has = 'data-cascade-child' in t
        url = '/api/cascade/' in t
        hand = 'get_projects_by_district' in t
        ok = r.status_code == 200 and has and url and not hand
        print('%s %s cascade=%s api=%s hand=%s' % (r.status_code, p, has, url, hand))
        if not ok:
            fails += 1

    for base in ['/vehicle-move-without-task', '/red-task', '/penalty-record']:
        r = c.get(base)
        html = r.get_data(as_text=True)
        m = re.search(re.escape(base) + r'/(\d+)/edit', html)
        if not m:
            print('no edit id for', base)
            continue
        ep = base + '/%s/edit' % m.group(1)
        rr = c.get(ep)
        tt = rr.get_data(as_text=True)
        has = 'data-cascade-child' in tt
        url = '/api/cascade/projects' in tt
        print('%s %s cascade=%s api=%s' % (rr.status_code, ep, has, url))
        sn = re.search(r'<select[^>]*id="districtSelect"[^>]*>', tt)
        print('  snippet', (sn.group(0)[:260] if sn else 'NO districtSelect'))
        if rr.status_code != 200 or not has or not url:
            fails += 1

    print('FAILS', fails)
    return 1 if fails else 0


if __name__ == '__main__':
    raise SystemExit(main())
