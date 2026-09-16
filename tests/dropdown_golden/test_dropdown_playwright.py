"""
Playwright golden suite for searchable dropdowns.
Runs at 1280px and 390px against a local Flask instance.

  python -m pytest tests/dropdown_golden/test_dropdown_playwright.py -q

Requires: playwright browsers installed (`playwright install chromium`).
"""
from __future__ import print_function

import os
import sys
import threading
import time

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('SKIP_STARTUP_TASKS', '1')

PORT = int(os.environ.get('DROPDOWN_GOLDEN_PORT', '5127'))
BASE = 'http://127.0.0.1:%d' % PORT

_VIEWPORTS = [
    {'name': 'desktop', 'width': 1280, 'height': 800},
    {'name': 'phone', 'width': 390, 'height': 844, 'is_mobile': True, 'has_touch': True},
]


@pytest.fixture(scope='module')
def live_server():
    from app import app

    def serve():
        app.run(host='127.0.0.1', port=PORT, threaded=True, use_reloader=False, debug=False)

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    # Wait until accepting connections
    import urllib.request
    deadline = time.time() + 40
    last_err = None
    while time.time() < deadline:
        try:
            urllib.request.urlopen(BASE + '/login', timeout=2)
            break
        except Exception as e:
            last_err = e
            time.sleep(0.4)
    else:
        pytest.skip('Flask golden server did not start: %s' % last_err)
    yield BASE


@pytest.fixture(scope='module')
def auth_cookie(live_server):
    from app import app
    serializer = app.session_interface.get_signing_serializer(app)
    value = serializer.dumps({
        'user_id': 1,
        'user': 'master',
        'username': 'master',
        'is_master': True,
        'portalxs_account_id': 1,
    })
    return {
        'name': app.config.get('SESSION_COOKIE_NAME', 'session'),
        'value': value,
        'domain': '127.0.0.1',
        'path': '/',
    }


def _new_page(pw, viewport, cookie):
    browser = pw.chromium.launch()
    context = browser.new_context(
        viewport={'width': viewport['width'], 'height': viewport['height']},
        is_mobile=bool(viewport.get('is_mobile')),
        has_touch=bool(viewport.get('has_touch')),
    )
    context.add_cookies([cookie])
    page = context.new_page()
    return browser, context, page


@pytest.mark.parametrize('viewport', _VIEWPORTS, ids=lambda v: v['name'])
def test_open_search_pick_and_inputmode(live_server, auth_cookie, viewport):
    playwright = pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import sync_playwright

    errors = []
    with sync_playwright() as pw:
        browser, context, page = _new_page(pw, viewport, auth_cookie)
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        page.goto(live_server + '/task-report/pending', wait_until='domcontentloaded', timeout=120000)
        page.wait_for_timeout(1500)

        # Prefer Tom Select control if present
        ts = page.locator('#pendingDistrictSelect-ts-control, .ts-wrapper .ts-control').first
        native = page.locator('#pendingDistrictSelect')
        if ts.count():
            ts.click()
            page.wait_for_timeout(300)
            inp = page.locator('.ts-dropdown .dropdown-input, .ts-control input').first
            if inp.count():
                mode = inp.get_attribute('inputmode')
                # Text keyboard guard: must not be numeric/decimal/tel on search box
                assert mode in (None, '', 'text', 'search')
                inp.fill('a')
                page.wait_for_timeout(400)
            # Pick first option if list open
            opt = page.locator('.ts-dropdown .option').first
            if opt.count():
                opt.click()
                page.wait_for_timeout(400)
        elif native.count():
            native.select_option(index=1)

        assert not errors, 'page errors: %s' % errors
        browser.close()


@pytest.mark.parametrize('viewport', _VIEWPORTS, ids=lambda v: v['name'])
def test_cascade_freshness_attrs_present(live_server, auth_cookie, viewport):
    playwright = pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _new_page(pw, viewport, auth_cookie)
        page.goto(live_server + '/task-report/pending', wait_until='domcontentloaded', timeout=120000)
        page.wait_for_timeout(1000)
        child = page.locator('#pendingDistrictSelect').get_attribute('data-cascade-child')
        url = page.locator('#pendingDistrictSelect').get_attribute('data-cascade-url')
        assert child == '#pendingProjectSelect'
        assert url and '/api/cascade/projects' in url
        # Trigger change and ensure project select still in DOM (TS or native)
        page.evaluate("""() => {
            var el = document.getElementById('pendingDistrictSelect');
            if (!el) return;
            if (el.tomselect) {
                var opts = Object.keys(el.tomselect.options || {});
                var pick = opts.find(function(v){ return v && v !== '0'; });
                if (pick) el.tomselect.setValue(pick, true);
                el.dispatchEvent(new Event('change', { bubbles: true }));
            } else if (el.options.length > 1) {
                el.selectedIndex = 1;
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }""")
        page.wait_for_timeout(1200)
        assert page.locator('#pendingProjectSelect').count() == 1
        browser.close()


@pytest.mark.parametrize('viewport', _VIEWPORTS, ids=lambda v: v['name'])
def test_lazy_select_stays_native_until_focus(live_server, auth_cookie, viewport):
    playwright = pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _new_page(pw, viewport, auth_cookie)
        # Page may 302 if route differs — try unexecuted report
        page.goto(live_server + '/unexecuted-task-report', wait_until='domcontentloaded', timeout=120000)
        page.wait_for_timeout(1200)
        lazy = page.locator('select.search-select[data-ts-lazy="1"]')
        if lazy.count() == 0:
            pytest.skip('No lazy row selects on this page (empty table or route redirect)')
        first = lazy.first
        assert first.get_attribute('data-ts-lazy') == '1'
        # Native should be visible (CSS exception for lazy)
        display = first.evaluate('el => getComputedStyle(el).display')
        assert display != 'none'
        first.focus()
        page.wait_for_timeout(800)
        # After focus, lazy flag removed and TS may wrap
        remaining = first.evaluate('el => el.getAttribute("data-ts-lazy")')
        assert remaining in (None, '')
        browser.close()


def test_max_options_config_in_fleet_core():
    """>300 option truncation is enforced in Tom Select config (maxOptions: 300)."""
    path = os.path.join(ROOT, 'static', 'js', 'core', 'fleet_core.js')
    src = open(path, encoding='utf-8').read()
    assert 'maxOptions: 300' in src
    assert 'fleetWireDeclarativeCascades' in src
    assert 'fleetArmLazySearchSelects' in src
    assert '_isReturningFromCamera' in src or 'ReturningFromCamera' in src
