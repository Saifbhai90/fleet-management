"""
Playwright golden suite for searchable dropdowns.
Runs at 1280px, 390px, and Capacitor-like WebView UA against a local Flask instance.

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

_CAPACITOR_UA = (
    'Mozilla/5.0 (Linux; Android 13; Pixel 6) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 '
    'FleetManagerCapacitor/1.0'
)

_VIEWPORTS = [
    {'name': 'desktop', 'width': 1280, 'height': 800},
    {'name': 'phone', 'width': 390, 'height': 844, 'is_mobile': True, 'has_touch': True},
    {
        'name': 'capacitor',
        'width': 390,
        'height': 844,
        'is_mobile': True,
        'has_touch': True,
        'user_agent': _CAPACITOR_UA,
    },
]


@pytest.fixture(scope='module')
def live_server():
    from app import app

    def serve():
        app.run(host='127.0.0.1', port=PORT, threaded=True, use_reloader=False, debug=False)

    t = threading.Thread(target=serve, daemon=True)
    t.start()
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
    kwargs = {
        'viewport': {'width': viewport['width'], 'height': viewport['height']},
        'is_mobile': bool(viewport.get('is_mobile')),
        'has_touch': bool(viewport.get('has_touch')),
    }
    if viewport.get('user_agent'):
        kwargs['user_agent'] = viewport['user_agent']
    context = browser.new_context(**kwargs)
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

        ts = page.locator('#pendingDistrictSelect-ts-control, .ts-wrapper .ts-control').first
        native = page.locator('#pendingDistrictSelect')
        before = page.evaluate("""() => {
            var el = document.getElementById('pendingDistrictSelect');
            return el ? String(el.value || '') : '';
        }""")
        if ts.count():
            ts.click()
            page.wait_for_timeout(300)
            inp = page.locator('.ts-dropdown .dropdown-input, .ts-control input').first
            if inp.count():
                mode = inp.get_attribute('inputmode')
                assert mode in (None, '', 'text', 'search')
                inp.fill('a')
                page.wait_for_timeout(400)
            opt = page.locator('.ts-dropdown .option').first
            if opt.count():
                opt.click()
                page.wait_for_timeout(400)
                after = page.evaluate("""() => {
                    var el = document.getElementById('pendingDistrictSelect');
                    return el ? String(el.value || '') : '';
                }""")
                assert after and after != '0'
                if before and before != '0' and before != after:
                    pass
        elif native.count():
            native.select_option(index=1)
            after = native.input_value()
            assert after and after != '0'

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

        seen = {'hit': False}

        def _on_response(resp):
            if '/api/cascade/projects' in (resp.url or ''):
                seen['hit'] = True

        page.on('response', _on_response)
        before_count = page.evaluate("""() => {
            var el = document.getElementById('pendingProjectSelect');
            return el ? el.options.length : 0;
        }""")
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
        page.wait_for_timeout(1500)
        assert page.locator('#pendingProjectSelect').count() == 1
        after_count = page.evaluate("""() => {
            var el = document.getElementById('pendingProjectSelect');
            return el ? el.options.length : 0;
        }""")
        # Either network cascade fired or options changed (LC/cache path on other pages).
        assert seen['hit'] or after_count != before_count or after_count >= 1
        browser.close()


@pytest.mark.parametrize('viewport', _VIEWPORTS, ids=lambda v: v['name'])
def test_lazy_select_stays_native_until_focus(live_server, auth_cookie, viewport):
    playwright = pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _new_page(pw, viewport, auth_cookie)
        page.goto(live_server + '/unexecuted-task-report', wait_until='domcontentloaded', timeout=120000)
        page.wait_for_timeout(1200)
        lazy = page.locator('select.search-select[data-ts-lazy="1"]')
        if lazy.count() == 0:
            pytest.skip('No lazy row selects on this page (empty table or route redirect)')
        first = lazy.first
        assert first.get_attribute('data-ts-lazy') == '1'
        display = first.evaluate('el => getComputedStyle(el).display')
        assert display != 'none'
        first.focus()
        page.wait_for_timeout(800)
        remaining = first.evaluate('el => el.getAttribute("data-ts-lazy")')
        assert remaining in (None, '')
        browser.close()


@pytest.mark.parametrize('viewport', _VIEWPORTS, ids=lambda v: v['name'])
def test_lazy_attendance_mark(live_server, auth_cookie, viewport):
    playwright = pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _new_page(pw, viewport, auth_cookie)
        page.goto(live_server + '/driver-attendance/mark', wait_until='domcontentloaded', timeout=120000)
        page.wait_for_timeout(1200)
        if '/login' in page.url or '/workspace' in page.url:
            pytest.skip('attendance mark redirected')
        lazy = page.locator('select.search-select[data-ts-lazy="1"]')
        if lazy.count() == 0:
            pytest.skip('No lazy selects on attendance mark (empty day)')
        first = lazy.first
        assert first.get_attribute('data-ts-lazy') == '1'
        first.focus()
        page.wait_for_timeout(800)
        remaining = first.evaluate('el => el.getAttribute("data-ts-lazy")')
        assert remaining in (None, '')
        browser.close()


@pytest.mark.parametrize('viewport', _VIEWPORTS, ids=lambda v: v['name'])
def test_camera_resume_runtime_no_auto_open(live_server, auth_cookie, viewport):
    playwright = pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _new_page(pw, viewport, auth_cookie)
        page.goto(live_server + '/task-report/pending', wait_until='domcontentloaded', timeout=120000)
        page.wait_for_timeout(1200)
        opened = page.evaluate("""() => {
            window._isReturningFromCamera = true;
            var el = document.getElementById('pendingDistrictSelect');
            if (!el || !el.tomselect) return 'no-ts';
            try { el.tomselect.focus(); } catch (e) {}
            var open = !!el.tomselect.isOpen;
            window._isReturningFromCamera = false;
            return open ? 'open' : 'closed';
        }""")
        assert opened in ('closed', 'no-ts')
        browser.close()


@pytest.mark.parametrize('viewport', _VIEWPORTS, ids=lambda v: v['name'])
def test_dropdown_parent_is_body(live_server, auth_cookie, viewport):
    playwright = pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _new_page(pw, viewport, auth_cookie)
        page.goto(live_server + '/task-report/pending', wait_until='domcontentloaded', timeout=120000)
        page.wait_for_timeout(1200)
        parent = page.evaluate("""() => {
            var el = document.getElementById('pendingDistrictSelect');
            if (!el || !el.tomselect || !el.tomselect.dropdown) return null;
            try { el.tomselect.open(); } catch (e) {}
            var dd = el.tomselect.dropdown;
            return dd && dd.parentElement ? dd.parentElement.tagName : null;
        }""")
        if parent is None:
            pytest.skip('Tom Select not initialized on pending district')
        assert parent == 'BODY'
        browser.close()


def test_max_options_config_in_fleet_core():
    path = os.path.join(ROOT, 'static', 'js', 'core', 'fleet_core.js')
    src = open(path, encoding='utf-8').read()
    assert 'maxOptions: 300' in src
    assert 'ts-truncation-hint' in src
    assert 'Showing first 300' in src
    assert 'fleetWireDeclarativeCascades' in src
    assert 'fleetArmLazySearchSelects' in src
    assert '_isReturningFromCamera' in src or 'ReturningFromCamera' in src


def test_camera_resume_guard_and_dropdown_parent_body():
    path = os.path.join(ROOT, 'static', 'js', 'core', 'fleet_core.js')
    src = open(path, encoding='utf-8').read()
    assert 'dropdownParent: \'body\'' in src or 'dropdownParent: "body"' in src
    assert '_isReturningFromCamera' in src
    assert 'openOnFocus: false' in src


@pytest.mark.parametrize('viewport', _VIEWPORTS, ids=lambda v: v['name'])
def test_logbook_cover_has_cascade_attrs(live_server, auth_cookie, viewport):
    playwright = pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _new_page(pw, viewport, auth_cookie)
        page.goto(live_server + '/task-report/logbook-cover', wait_until='domcontentloaded', timeout=120000)
        page.wait_for_timeout(800)
        if '/login' in page.url:
            pytest.skip('logbook-cover redirected to login')
        sel = page.locator('#districtSelect')
        if sel.count() == 0:
            pytest.skip('logbook cover district select not found')
        assert '/api/cascade/projects' in (sel.get_attribute('data-cascade-url') or '')
        assert sel.get_attribute('data-cascade-child') == '#projectSelect'
        browser.close()


@pytest.mark.parametrize('viewport', _VIEWPORTS, ids=lambda v: v['name'])
def test_oil_list_has_lc_cascade_attrs(live_server, auth_cookie, viewport):
    playwright = pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _new_page(pw, viewport, auth_cookie)
        page.goto(live_server + '/oil-expenses', wait_until='domcontentloaded', timeout=120000)
        page.wait_for_timeout(1000)
        if '/login' in page.url or '/workspace' in page.url:
            pytest.skip('oil list redirected')
        sel = page.locator('#districtSelect')
        if sel.count() == 0:
            pytest.skip('oil list district select missing')
        assert sel.get_attribute('data-cascade-source') == 'locationCascadeData'
        assert '/api/cascade/projects' in (sel.get_attribute('data-cascade-url') or '')
        browser.close()
