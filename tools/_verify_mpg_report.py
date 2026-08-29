# -*- coding: utf-8 -*-
"""Verify the MPG Report: desktop grid polish, phone layout, and save round-trip.

The two behaviours that regressed in production are covered explicitly:

  1. On a phone / in the Capacitor app the card layout must be on screen at first
     paint, even when the external scripts in base.html are still loading. The
     old build only switched layouts at DOMContentLoaded, so a slow link showed
     the desktop form first.
  2. Saving inputs must not lose ?nav_from (which used to bring back the
     Employee-Workspace variant of the page) and must not raise IntegrityError
     when a row for the same employee/vehicle/range already exists.

Screenshots land in tools/_shots/.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('SKIP_STARTUP_TASKS', '1')
os.environ.setdefault('DATABASE_URL', 'sqlite:///db/local.db')

from playwright.sync_api import sync_playwright  # noqa: E402

from app import app  # noqa: E402

PORT = 5107
BASE = f'http://127.0.0.1:{PORT}'
SHOTS = ROOT / 'tools' / '_shots'
REPORT = '/workspace/reports/mpg?nav_from=reports&from_date=01-08-2026&to_date=30-08-2026'

PHONE = {'width': 390, 'height': 844}
DESKTOP = {'width': 1440, 'height': 900}

failures: list[str] = []


def check(label: str, ok: bool, detail: str = '') -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def session_cookie(domain: str = '127.0.0.1') -> dict:
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
        'domain': domain,
        'path': '/',
    }


def serve() -> None:
    app.run(host='127.0.0.1', port=PORT, threaded=True, use_reloader=False, debug=False)


def wait_for_server(page) -> None:
    for _ in range(60):
        try:
            page.goto(f'{BASE}/health', timeout=2000)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError('local server did not come up')


def audit_desktop(ctx) -> None:
    page = ctx.new_page()
    page.goto(BASE + REPORT, wait_until='domcontentloaded', timeout=120000)
    page.wait_for_timeout(2000)

    print('\n== desktop 1440x900 ==')
    state = page.evaluate("""() => {
        const page = document.querySelector('.mpg-report-page');
        const table = document.getElementById('workspaceMpgReportTable');
        const th = table && table.querySelector('thead th.mpg-sticky-sr');
        const veh = table && table.querySelector('tbody td.mpg-sticky-veh');
        const foot = table && table.querySelector('tfoot tr');
        const wrap = document.querySelector('.mpg-table-wrap');
        const cs = el => el ? getComputedStyle(el) : null;
        return {
            mobileClass: !!(page && page.classList.contains('is-mobile-layout')),
            rows: table ? table.querySelectorAll('tbody tr.mpg-data-row').length : 0,
            headSticky: th ? cs(th).position : null,
            vehSticky: veh ? cs(veh).position : null,
            footCells: foot ? foot.cells.length : 0,
            headCells: table ? table.querySelectorAll('thead th').length : 0,
            wrapScrolls: wrap ? cs(wrap).overflowY : null,
            inputTinted: (() => {
                const td = table && table.querySelector('tbody td.mpg-input-cell');
                return td ? cs(td).backgroundColor : null;
            })(),
            docWidth: document.documentElement.scrollWidth,
            viewport: window.innerWidth,
        };
    }""")
    print('   ', state)
    check('desktop keeps the table layout', not state['mobileClass'])
    check('desktop renders data rows', state['rows'] > 0, f"rows={state['rows']}")
    check('header row is pinned', state['headSticky'] == 'sticky', str(state['headSticky']))
    check('vehicle column is pinned', state['vehSticky'] == 'sticky', str(state['vehSticky']))
    check('totals row matches header width',
          state['footCells'] == state['headCells'],
          f"foot={state['footCells']} head={state['headCells']}")
    check('editable columns are tinted',
          state['inputTinted'] not in (None, 'rgba(0, 0, 0, 0)'),
          str(state['inputTinted']))
    check('no horizontal page overflow',
          state['docWidth'] <= state['viewport'] + 1,
          f"doc={state['docWidth']} viewport={state['viewport']}")

    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / 'mpg-desktop.png'))

    # Scroll the grid to the editable columns: the point of pinning is that the
    # vehicle stays readable while a reading is typed 15 columns to the right.
    page.evaluate("""() => {
        const wrap = document.querySelector('.mpg-table-wrap');
        wrap.scrollLeft = wrap.scrollWidth;
        wrap.scrollTop = 240;
    }""")
    page.wait_for_timeout(400)
    scrolled = page.evaluate("""() => {
        const wrap = document.querySelector('.mpg-table-wrap');
        const wrapBox = wrap.getBoundingClientRect();
        const veh = wrap.querySelector('tbody td.mpg-sticky-veh');
        const head = wrap.querySelector('thead th.mpg-sticky-sr');
        const foot = wrap.querySelector('tfoot td.mpg-sticky-veh');
        const box = el => { const r = el.getBoundingClientRect(); return {left: Math.round(r.left - wrapBox.left), top: Math.round(r.top - wrapBox.top)}; };
        return {
            scrolledRight: wrap.scrollLeft > 200,
            vehicle: box(veh),
            header: box(head),
            footer: Math.round(foot.getBoundingClientRect().bottom - wrapBox.bottom),
            vehicleText: veh.innerText.trim().split('\\n')[0],
        };
    }""")
    print('   scrolled:', scrolled)
    check('grid scrolls sideways', scrolled['scrolledRight'] is True)
    check('vehicle column stays pinned to the left',
          scrolled['vehicle']['left'] <= 56, str(scrolled['vehicle']))
    check('header row stays pinned to the top',
          scrolled['header']['top'] <= 2, str(scrolled['header']))
    check('totals row stays pinned to the bottom',
          abs(scrolled['footer']) <= 2, str(scrolled['footer']))
    check('pinned cell still names a vehicle',
          bool(scrolled['vehicleText']), scrolled['vehicleText'])
    page.screenshot(path=str(SHOTS / 'mpg-desktop-scrolled.png'))
    page.close()


def audit_phone(ctx) -> None:
    page = ctx.new_page()
    page.goto(BASE + REPORT, wait_until='domcontentloaded', timeout=120000)
    page.wait_for_timeout(2000)

    print('\n== phone 390x844 ==')
    state = page.evaluate("""() => {
        const page = document.querySelector('.mpg-report-page');
        const table = document.getElementById('workspaceMpgReportTable');
        const thead = table && table.querySelector('thead');
        const foot = table && table.querySelector('tfoot');
        const row = table && table.querySelector('tbody tr.mpg-data-row');
        const cs = el => el ? getComputedStyle(el) : null;
        return {
            mobileClass: !!(page && page.classList.contains('is-mobile-layout')),
            theadHidden: thead ? cs(thead).display === 'none' : null,
            footHidden: foot ? cs(foot).display === 'none' : true,
            rowIsCard: row ? cs(row).display === 'grid' : null,
            saveBar: (() => {
                const bar = document.querySelector('.mpg-m-save-bar');
                return bar ? cs(bar).display : null;
            })(),
            docWidth: document.documentElement.scrollWidth,
            viewport: window.innerWidth,
        };
    }""")
    print('   ', state)
    check('phone uses the mobile layout', state['mobileClass'])
    check('desktop header is hidden', state['theadHidden'] is True)
    check('totals row is hidden on phone', state['footHidden'] is True)
    check('rows render as cards', state['rowIsCard'] is True, str(state['rowIsCard']))
    check('save bar is present', state['saveBar'] == 'block', str(state['saveBar']))
    check('no horizontal page overflow',
          state['docWidth'] <= state['viewport'] + 1,
          f"doc={state['docWidth']} viewport={state['viewport']}")

    page.screenshot(path=str(SHOTS / 'mpg-phone.png'), full_page=False)
    page.close()


def audit_slow_native(browser) -> None:
    """The regression the user reported: slow link in the app showed the web form."""
    print('\n== app webview on a slow link ==')
    ctx = browser.new_context(viewport=DESKTOP, user_agent='Mozilla/5.0 CapacitorApp')
    ctx.add_cookies([
        session_cookie(),
        {'name': 'fleet_native_app', 'value': '1', 'domain': '127.0.0.1', 'path': '/'},
    ])
    page = ctx.new_page()

    # base.html loads fleet_core/fleet_ui with `defer` and a few more scripts at
    # the end of the body. Those do not block parsing, but they do hold back
    # DOMContentLoaded — which is the exact window in which the phone used to
    # show the desktop table. Stall only those, so the body still paints.
    def stall(route):
        time.sleep(4)
        route.continue_()

    for pattern in (
        '**/js/core/fleet_core.js*',
        '**/js/core/fleet_ui.js*',
        '**/js/core/fleet_mobile.js*',
        '**/js/legacy_android_gpu.js*',
        '**/js/session_sounds.js*',
        '**/js/fleet_biometric_toggle.js*',
        '**/js/gps_attendance_pending_upload.js*',
        '**/js/fleet_notifications_ui.js*',
        '**/lucide*',
    ):
        page.route(pattern, stall)

    page.goto(BASE + REPORT, wait_until='commit', timeout=120000)
    deadline = time.time() + 25
    state = {}
    while time.time() < deadline:
        state = page.evaluate("""() => {
            const page = document.querySelector('.mpg-report-page');
            const row = document.querySelector('#workspaceMpgReportTable tbody tr.mpg-data-row');
            return page ? {
                found: true,
                mobileClass: page.classList.contains('is-mobile-layout'),
                readyState: document.readyState,
                rowVisible: !!row,
            } : {found: false};
        }""")
        if state.get('found') and state.get('rowVisible'):
            break
        time.sleep(0.2)
    print('   ', state)
    check('report body reached the browser', state.get('found') is True)
    check('mobile layout is active before scripts finish', state.get('mobileClass') is True)
    check('checked while the document was still loading',
          state.get('readyState') in ('loading', 'interactive'), str(state.get('readyState')))
    page.screenshot(path=str(SHOTS / 'mpg-native-slow.png'))
    page.close()
    ctx.close()


def audit_save(ctx) -> None:
    """Save twice: the second POST is the one that used to raise IntegrityError."""
    print('\n== save inputs round-trip ==')
    page = ctx.new_page()
    page.goto(BASE + REPORT, wait_until='domcontentloaded', timeout=120000)
    page.wait_for_timeout(1500)

    has_input = page.locator('input.current-odoo-input').count()
    if not has_input:
        check('report exposes an editable reading', False, 'no rows to save')
        page.close()
        return

    for attempt, value in enumerate(('320975', '320999'), start=1):
        page.fill('input.current-odoo-input >> nth=0', value)
        page.once('dialog', lambda d: d.accept())
        page.click('#mpgDesktopSaveBtn')
        page.wait_for_load_state('domcontentloaded', timeout=120000)
        page.wait_for_timeout(1200)
        url = page.url
        body = page.locator('body').inner_text()
        ok = 'Internal Server Error' not in body and 'saved successfully' in body
        check(f'save #{attempt} succeeds', ok, url.split('?')[-1][:90])
        check(f'save #{attempt} keeps nav_from', 'nav_from=reports' in url, url)
        check(f'save #{attempt} keeps the Report Center header',
              page.locator('#mpgTopBar').count() == 1)

    page.close()


def main() -> int:
    threading.Thread(target=serve, daemon=True).start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        boot = browser.new_context()
        wait_for_server(boot.new_page())
        boot.close()

        for name, viewport in (('desktop', DESKTOP), ('phone', PHONE)):
            ctx = browser.new_context(viewport=viewport,
                                      is_mobile=name == 'phone',
                                      has_touch=name == 'phone')
            ctx.add_cookies([session_cookie()])
            if name == 'desktop':
                audit_desktop(ctx)
                audit_save(ctx)
            else:
                audit_phone(ctx)
            ctx.close()

        audit_slow_native(browser)
        browser.close()

    print('\n' + ('ALL CHECKS PASSED' if not failures
                  else f'{len(failures)} FAILED: ' + '; '.join(failures)))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
