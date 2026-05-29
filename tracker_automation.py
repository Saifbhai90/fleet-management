"""
Tracker Automation Engine
Playwright-based robot that logs into TrackingWorld portal,
iterates every vehicle, downloads Activity Report XLSXs, and
packages them into a ZIP for the user to download.

Password encryption uses Fernet (cryptography package).
The SECRET_KEY from Flask config is used as Fernet key material.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import re
import threading
import time
import traceback
import zipfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── Fernet password helpers ──────────────────────────────────────────────────

def _fernet(app=None):
    """Build a Fernet instance from Flask SECRET_KEY."""
    from cryptography.fernet import Fernet
    import hashlib
    if app is None:
        from flask import current_app as _app
        secret = _app.config.get('SECRET_KEY', 'fallback-secret-key')
    else:
        secret = app.config.get('SECRET_KEY', 'fallback-secret-key')
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_password(plain: str, app=None) -> str:
    return _fernet(app).encrypt(plain.encode()).decode()


def decrypt_password(enc: str, app=None) -> str:
    try:
        return _fernet(app).decrypt(enc.encode()).decode()
    except Exception:
        return ''


# ── Temp directory for downloads ─────────────────────────────────────────────

def _jobs_dir() -> Path:
    base = Path(os.environ.get('TRACKER_JOBS_DIR', '/tmp/tracker_jobs'))
    base.mkdir(parents=True, exist_ok=True)
    return base


def job_dir(job_id: int) -> Path:
    d = _jobs_dir() / str(job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Log helper ───────────────────────────────────────────────────────────────

class JobLogger:
    def __init__(self, job_id: int, app):
        self._job_id = job_id
        self._app = app
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._last_flush: float = 0.0
        self._flush_interval = 4.0  # seconds between DB writes

    def _ts(self) -> str:
        return datetime.now().strftime('%H:%M:%S')

    def _append(self, line: str):
        with self._lock:
            self._lines.append(line)
        self._flush(force=False)

    def info(self, msg: str):
        line = f'[{self._ts()}] i {msg}'
        logger.info('Job %s: %s', self._job_id, msg)
        self._append(line)

    def ok(self, msg: str):
        line = f'[{self._ts()}] OK {msg}'
        logger.info('Job %s: %s', self._job_id, msg)
        self._append(line)

    def warn(self, msg: str):
        line = f'[{self._ts()}] WARN {msg}'
        logger.warning('Job %s: %s', self._job_id, msg)
        self._append(line)

    def error(self, msg: str):
        line = f'[{self._ts()}] ERROR {msg}'
        logger.error('Job %s: %s', self._job_id, msg)
        self._append(line)
        self._flush(force=True)  # always flush errors immediately

    def _flush(self, force: bool = False):
        now = time.time()
        if not force and (now - self._last_flush) < self._flush_interval:
            return
        self._last_flush = now
        with self._lock:
            text = '\n'.join(self._lines[-500:])
        try:
            from models import TrackerAutomationJob, db
            with self._app.app_context():
                job = db.session.get(TrackerAutomationJob, self._job_id)
                if job:
                    job.log_text = text
                    db.session.commit()
        except Exception as fe:
            logger.warning('JobLogger flush error (non-fatal): %s', fe)

    def flush_now(self):
        """Force immediate DB write — call at end of job."""
        self._flush(force=True)

    @property
    def full_log(self) -> str:
        with self._lock:
            return '\n'.join(self._lines)


# ── Captcha OCR helper ───────────────────────────────────────────────────────

def _solve_captcha_ocr(img_bytes: bytes) -> str:
    """Use pytesseract to extract 6-digit captcha text from image bytes."""
    try:
        import pytesseract
        from PIL import Image, ImageFilter, ImageEnhance
        img = Image.open(io.BytesIO(img_bytes)).convert('L')
        img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
        img = ImageEnhance.Contrast(img).enhance(3.0)
        img = img.filter(ImageFilter.SHARPEN)
        text = pytesseract.image_to_string(
            img,
            config='--psm 8 --oem 3 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
        )
        cleaned = re.sub(r'[^A-Za-z0-9]', '', text).strip()
        return cleaned
    except Exception as e:
        logger.warning('Captcha OCR failed: %s', e)
        return ''


# ── Main automation runner ────────────────────────────────────────────────────

def run_tracker_job(job_id: int, app):
    """
    Background thread entry point.
    Runs full Playwright automation: login → navigate → loop vehicles → zip.
    """
    from models import TrackerAutomationJob, TrackerAutomationSettings, db
    from utils import pk_now

    jlog = JobLogger(job_id, app)

    # ── Outer safety net: ANY unhandled exception → mark job failed ────────
    try:
        _run_tracker_job_inner(job_id, app, jlog)
    except Exception as top_e:
        tb = traceback.format_exc()
        jlog.error(f'UNHANDLED CRASH: {top_e}')
        jlog.error(f'Traceback:\n{tb}')
        _mark_failed(job_id, app, jlog)


def _run_tracker_job_inner(job_id: int, app, jlog: 'JobLogger'):
    from models import TrackerAutomationJob, TrackerAutomationSettings, db
    from utils import pk_now

    with app.app_context():
        job = db.session.get(TrackerAutomationJob, job_id)
        if not job:
            return
        settings = TrackerAutomationSettings.query.first()
        if not settings:
            job.status = 'failed'
            job.log_text = 'Settings nahi milein. Pehle credentials save karein.'
            db.session.commit()
            return

        portal_url = (settings.portal_url or '').strip().rstrip('/')
        username = (settings.username or '').strip()
        password = decrypt_password(settings.password_enc or '', app)
        date_from_str = job.date_from.strftime('%d/%m/%Y')
        date_to_str = job.date_to.strftime('%d/%m/%Y')

        job.status = 'running'
        job.started_at = pk_now()
        db.session.commit()

    jlog.info(f'Job #{job_id} shuru ho raha hai...')
    jlog.info(f'Portal: {portal_url}')
    jlog.info(f'Date range: {date_from_str} → {date_to_str}')
    jlog.flush_now()

    jlog.info('Step 1: Playwright import check...')
    jlog.flush_now()
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        jlog.ok('Playwright import OK.')
        jlog.flush_now()
    except ImportError:
        jlog.error('Playwright install nahi hai. Render build logs check karein — `playwright install chromium` hona chahiye.')
        _mark_failed(job_id, app, jlog)
        return

    dl_dir = job_dir(job_id)
    downloaded_files: list[Path] = []

    jlog.info('Step 2: Chromium browser launch ho raha hai...')
    jlog.flush_now()

    # Ensure Playwright finds the binary installed during Render build
    _pw_cache = '/opt/render/.cache/ms-playwright'
    if os.path.isdir(_pw_cache):
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', _pw_cache)
        jlog.info(f'PLAYWRIGHT_BROWSERS_PATH set to {_pw_cache}')
    jlog.flush_now()

    try:
        with sync_playwright() as pw:
            jlog.info('Step 3: Browser launching (headless mode)...')
            jlog.flush_now()
            browser = pw.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
                downloads_path=str(dl_dir),
            )
            jlog.ok('Browser launch successful.')
            jlog.flush_now()
            context = browser.new_context(
                accept_downloads=True,
                viewport={'width': 1280, 'height': 900},
            )
            page = context.new_page()
            page.set_default_timeout(30000)

            # ── Login ──────────────────────────────────────────────────────
            jlog.info('Step 4: Portal URL pe navigate kar rahe hain...')
            jlog.flush_now()
            page.goto(portal_url, wait_until='domcontentloaded', timeout=45000)
            jlog.ok(f'Page load OK. URL: {page.url}')
            jlog.flush_now()

            max_login_tries = 5
            logged_in = False
            for attempt in range(1, max_login_tries + 1):
                jlog.info(f'Login attempt {attempt}/{max_login_tries}...')
                try:
                    # Fill username
                    page.fill('input[name="username"], input[type="text"]', username, timeout=10000)
                    page.fill('input[name="password"], input[type="password"]', password, timeout=10000)

                    # Captcha
                    captcha_text = ''
                    try:
                        captcha_img = page.locator('img[id*="captcha"], img[src*="captcha"], img[class*="captcha"]').first
                        if captcha_img.count() > 0:
                            img_bytes = captcha_img.screenshot()
                            captcha_text = _solve_captcha_ocr(img_bytes)
                            jlog.info(f'Captcha OCR: "{captcha_text}"')
                            captcha_input = page.locator('input[id*="captcha"], input[name*="captcha"], input[placeholder*="captcha" i]').first
                            if captcha_input.count() > 0 and captcha_text:
                                captcha_input.fill(captcha_text)
                    except Exception as ce:
                        jlog.warn(f'Captcha element nahi mila: {ce}')

                    # Submit
                    page.click('button[type="submit"], input[type="submit"]', timeout=8000)
                    page.wait_for_load_state('domcontentloaded', timeout=20000)

                    # Check login success
                    current_url = page.url
                    page_title = page.title()

                    # Extract any error/alert message shown on page
                    portal_msg = _extract_page_message(page)
                    if portal_msg:
                        jlog.info(f'Portal message: "{portal_msg}"')

                    if _is_logged_in(page, portal_url):
                        logged_in = True
                        jlog.ok(f'Login successful! URL: {current_url}')
                        jlog.flush_now()
                        break
                    else:
                        jlog.warn(f'Login fail — Title: "{page_title}" — URL: {current_url}')
                        jlog.flush_now()
                        page.goto(portal_url, wait_until='domcontentloaded', timeout=30000)
                        time.sleep(1.5)
                except PWTimeout as te:
                    jlog.warn(f'Attempt {attempt} timeout: {te}')
                    jlog.flush_now()
                    if attempt < max_login_tries:
                        page.reload(wait_until='domcontentloaded', timeout=20000)
                        time.sleep(2)

            if not logged_in:
                jlog.error('5 attempts ke baad bhi login fail. Credentials / captcha check karein.')
                jlog.error(f'Last page title: {page.title()}')
                jlog.error(f'Last URL: {page.url}')
                _mark_failed(job_id, app, jlog)
                browser.close()
                return

            # ── Navigate to Activity Report ────────────────────────────────
            jlog.info('Step 5: Activity Report page par navigate kar rahe hain...')
            jlog.flush_now()
            nav_ok = _navigate_to_activity_report(page, jlog)
            if not nav_ok:
                jlog.error('Activity Report page nahi mila. Portal structure check karein.')
                _mark_failed(job_id, app, jlog)
                browser.close()
                return

            # ── Get vehicle list ───────────────────────────────────────────
            jlog.info('Step 6: Vehicle list extract kar rahe hain...')
            jlog.flush_now()
            vehicles = _get_vehicle_list(page, jlog)
            jlog.info(f'Step 6 done: {len(vehicles)} vehicles mile.')
            jlog.flush_now()

            with app.app_context():
                job = db.session.get(TrackerAutomationJob, job_id)
                job.total_vehicles = len(vehicles)
                db.session.commit()

            if not vehicles:
                jlog.warn('Koi vehicle nahi mila. ZIP empty hoga.')
                jlog.flush_now()

            # ── Loop each vehicle ──────────────────────────────────────────
            done_count = 0
            fail_count = 0
            for idx, vehicle in enumerate(vehicles, 1):
                veh_name = vehicle.get('name', f'Vehicle_{idx}')
                jlog.info(f'[{idx}/{len(vehicles)}] Processing: {veh_name}')

                try:
                    file_path = _download_vehicle_report(
                        page, context, vehicle, date_from_str, date_to_str,
                        dl_dir, jlog, app, job_id
                    )
                    if file_path:
                        downloaded_files.append(file_path)
                        done_count += 1
                        jlog.ok(f'{veh_name} — done ({done_count} complete)')
                    else:
                        fail_count += 1
                        jlog.warn(f'{veh_name} — koi data nahi ya download fail')
                except Exception as ve:
                    fail_count += 1
                    jlog.error(f'{veh_name} — error: {ve}')

                with app.app_context():
                    job = db.session.get(TrackerAutomationJob, job_id)
                    job.done_vehicles = done_count
                    job.failed_vehicles = fail_count
                    db.session.commit()
                jlog.flush_now()

                # Re-login check after every 10 vehicles
                if idx % 10 == 0 and not _is_logged_in(page, portal_url):
                    jlog.warn('Session expire ho gaya — re-login...')
                    _do_relogin(page, portal_url, username, password, jlog)
                    _navigate_to_activity_report(page, jlog)

            browser.close()

    except Exception as e:
        tb = traceback.format_exc()
        jlog.error(f'Engine crash: {e}')
        jlog.error(f'Traceback: {tb}')
        _mark_failed(job_id, app, jlog)
        return

    # ── Build ZIP ─────────────────────────────────────────────────────────
    jlog.info('ZIP tayyar kar rahe hain...')
    zip_path = _jobs_dir() / f'tracker_reports_job{job_id}.zip'
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for fp in downloaded_files:
                zf.write(fp, fp.name)
        jlog.ok(f'ZIP ready: {len(downloaded_files)} files ({zip_path.stat().st_size // 1024} KB)')
    except Exception as ze:
        jlog.error(f'ZIP banane mein error: {ze}')
        _mark_failed(job_id, app, jlog)
        return

    jlog.ok(f'Job #{job_id} mukammal! {done_count} reports ZIP mein.')
    jlog.flush_now()

    with app.app_context():
        from utils import pk_now
        job = db.session.get(TrackerAutomationJob, job_id)
        job.status = 'done'
        job.zip_path = str(zip_path)
        job.finished_at = pk_now()
        job.log_text = jlog.full_log
        db.session.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_logged_in(page, portal_url: str) -> bool:
    """Check if we are on a logged-in page (not login page)."""
    url = page.url.lower()
    title = (page.title() or '').lower()
    login_indicators = ['login', 'signin', 'sign-in', 'logon']
    for ind in login_indicators:
        if ind in url or ind in title:
            return False
    return True


def _extract_page_message(page) -> str:
    """
    Try to extract any visible error or success message from the portal page.
    Checks common alert/validation selectors used by ASP.NET and generic portals.
    Returns the message text or empty string.
    """
    selectors = [
        # Bootstrap alerts
        '.alert', '.alert-danger', '.alert-success', '.alert-warning', '.alert-info',
        # ASP.NET validator / label
        'span[id*="error" i]', 'span[id*="msg" i]', 'span[id*="Error" i]',
        'label[id*="error" i]', 'div[id*="error" i]',
        # Generic
        '.error-message', '.success-message', '.validation-summary-errors',
        '#lblMessage', '#lblError', '#lblStatus', '#ErrorMessage',
        'div[class*="error" i]', 'div[class*="alert" i]', 'p[class*="error" i]',
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.count() > 0:
                txt = (el.inner_text() or '').strip()
                if txt and len(txt) < 300:
                    return txt
        except Exception:
            pass
    return ''


def _do_relogin(page, portal_url: str, username: str, password: str, jlog: JobLogger):
    page.goto(portal_url, wait_until='domcontentloaded', timeout=30000)
    time.sleep(1)
    try:
        page.fill('input[name="username"], input[type="text"]', username, timeout=8000)
        page.fill('input[name="password"], input[type="password"]', password, timeout=8000)
        try:
            captcha_img = page.locator('img[id*="captcha"], img[src*="captcha"]').first
            if captcha_img.count() > 0:
                img_bytes = captcha_img.screenshot()
                captcha_text = _solve_captcha_ocr(img_bytes)
                captcha_input = page.locator('input[id*="captcha"], input[name*="captcha"]').first
                if captcha_input.count() > 0 and captcha_text:
                    captcha_input.fill(captcha_text)
        except Exception:
            pass
        page.click('button[type="submit"], input[type="submit"]', timeout=8000)
        page.wait_for_load_state('domcontentloaded', timeout=20000)
        jlog.ok('Re-login successful.')
    except Exception as re_e:
        jlog.error(f'Re-login fail: {re_e}')


def _navigate_to_activity_report(page, jlog: JobLogger) -> bool:
    """
    Try to navigate to Reporting > General > Activity Report.
    Returns True on success, False if not found.
    """
    try:
        # Try direct menu clicks
        nav_selectors = [
            'a:has-text("Reporting")',
            'a:has-text("Reports")',
            'li:has-text("Reporting") > a',
        ]
        for sel in nav_selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0:
                    el.click(timeout=6000)
                    time.sleep(0.8)
                    break
            except Exception:
                pass

        general_selectors = [
            'a:has-text("General")',
            'li:has-text("General") > a',
        ]
        for sel in general_selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0:
                    el.click(timeout=6000)
                    time.sleep(0.6)
                    break
            except Exception:
                pass

        activity_selectors = [
            'a:has-text("Activity Report")',
            'a:has-text("Activity")',
            'li:has-text("Activity Report") > a',
        ]
        for sel in activity_selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0:
                    el.click(timeout=8000)
                    page.wait_for_load_state('domcontentloaded', timeout=15000)
                    jlog.ok('Activity Report page mila.')
                    return True
            except Exception:
                pass

        # Fallback: check if we're already on it
        if 'activity' in page.url.lower() or 'report' in page.url.lower():
            return True

        jlog.warn('Activity Report link nahi mila — URL dekh kar try kar rahe hain.')
        return False
    except Exception as e:
        jlog.error(f'Navigation error: {e}')
        return False


def _get_vehicle_list(page, jlog: JobLogger) -> list[dict]:
    """Extract vehicle list from the page tree/select/table."""
    vehicles = []
    try:
        # Try select/dropdown with vehicle options
        sel_locators = [
            'select[id*="vehicle" i]',
            'select[name*="vehicle" i]',
            'select[id*="unit" i]',
        ]
        for sel in sel_locators:
            try:
                select_el = page.locator(sel).first
                if select_el.count() > 0:
                    options = select_el.locator('option').all()
                    for opt in options:
                        val = opt.get_attribute('value') or ''
                        text = (opt.inner_text() or '').strip()
                        if val and val not in ('', '0', '-1') and text:
                            vehicles.append({'value': val, 'name': text, 'type': 'select'})
                    if vehicles:
                        jlog.info(f'Vehicle dropdown se {len(vehicles)} vehicles.')
                        return vehicles
            except Exception:
                pass

        # Try tree/checkbox list
        tree_items = page.locator(
            'ul.vehicle-tree li, .tree-node, input[type="checkbox"][value*="veh"], '
            'span.tree-label, li.vehicle-item'
        ).all()
        for item in tree_items[:200]:
            try:
                text = (item.inner_text() or '').strip()
                val = item.get_attribute('data-id') or item.get_attribute('value') or text
                if text and val:
                    vehicles.append({'value': val, 'name': text, 'type': 'tree'})
            except Exception:
                pass

        if vehicles:
            return vehicles

        jlog.warn('Vehicle list auto-detect nahi ho saka.')
    except Exception as e:
        jlog.error(f'Vehicle list error: {e}')
    return vehicles


def _download_vehicle_report(
    page, context, vehicle: dict,
    date_from: str, date_to: str,
    dl_dir: Path, jlog: JobLogger, app, job_id: int
) -> Path | None:
    """
    For a single vehicle: select it, set dates, click Show/Fetch, then Excel export.
    Returns the path of downloaded file, or None.
    """
    veh_name = vehicle.get('name', '')
    veh_val = vehicle.get('value', '')

    try:
        # Select vehicle in dropdown or tree
        if vehicle.get('type') == 'select':
            page.select_option(
                'select[id*="vehicle" i], select[name*="vehicle" i], select[id*="unit" i]',
                value=veh_val,
                timeout=6000
            )
        else:
            # Click on tree node by text
            tree_node = page.locator(f'text="{veh_name}"').first
            if tree_node.count() > 0:
                tree_node.click(timeout=5000)
            time.sleep(0.3)

        # Set date range
        _set_date_fields(page, date_from, date_to, jlog)
        time.sleep(0.3)

        # Click Show/Fetch/Search button
        show_selectors = [
            'button:has-text("Show")', 'input[value="Show"]',
            'button:has-text("Fetch")', 'button:has-text("Search")',
            'button:has-text("Generate")', 'input[type="submit"]',
            'button[id*="show" i]', 'button[id*="fetch" i]',
        ]
        clicked = False
        for sel in show_selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0:
                    el.click(timeout=6000)
                    clicked = True
                    break
            except Exception:
                pass

        if not clicked:
            # Try __doPostBack
            page.evaluate("if(typeof __doPostBack !== 'undefined') __doPostBack('btnShow', '')")
            clicked = True

        page.wait_for_load_state('networkidle', timeout=25000)
        time.sleep(1)

        # Click Excel export button and capture download
        excel_selectors = [
            'a[id*="excel" i]', 'button:has-text("Excel")',
            'a:has-text("Excel")', 'img[src*="excel" i]',
            'a[href*="excel" i]', 'input[value*="Excel" i]',
            '[id*="Excel" i]', '[class*="excel" i]',
        ]
        for sel in excel_selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0:
                    with context.expect_page() as new_page_info:
                        try:
                            with page.expect_download(timeout=30000) as dl_info:
                                el.click(timeout=6000)
                            download = dl_info.value
                            safe_name = re.sub(r'[^\w\-.]', '_', veh_name)
                            date_tag = date_from.replace('/', '-')
                            file_name = f'{safe_name}_{date_tag}.xlsx'
                            save_path = dl_dir / file_name
                            # Skip if already exists
                            if save_path.exists():
                                ts = int(time.time())
                                file_name = f'{safe_name}_{date_tag}_{ts}.xlsx'
                                save_path = dl_dir / file_name
                            download.save_as(str(save_path))
                            return save_path
                        except Exception:
                            pass
                    # If new page opened instead
                    try:
                        np = new_page_info.value
                        np.close()
                    except Exception:
                        pass
            except Exception:
                pass

        # Fallback: try __doPostBack for Excel
        try:
            with page.expect_download(timeout=20000) as dl_info:
                page.evaluate("if(typeof __doPostBack !== 'undefined') __doPostBack('btnExcel', '')")
            download = dl_info.value
            safe_name = re.sub(r'[^\w\-.]', '_', veh_name)
            date_tag = date_from.replace('/', '-')
            file_name = f'{safe_name}_{date_tag}.xlsx'
            save_path = dl_dir / file_name
            if save_path.exists():
                save_path = dl_dir / f'{safe_name}_{date_tag}_{int(time.time())}.xlsx'
            download.save_as(str(save_path))
            return save_path
        except Exception:
            pass

        jlog.warn(f'{veh_name}: Excel button nahi mila ya download fail.')
        return None

    except Exception as e:
        jlog.error(f'{veh_name} download error: {e}')
        return None


def _set_date_fields(page, date_from: str, date_to: str, jlog: JobLogger):
    """Fill date From/To fields — tries multiple selectors."""
    from_selectors = [
        'input[id*="from" i][type="date"]', 'input[name*="from" i]',
        'input[id*="datefrom" i]', 'input[id*="startdate" i]',
        'input[id*="FromDate" i]', 'input[id*="DateFrom" i]',
    ]
    to_selectors = [
        'input[id*="to" i][type="date"]', 'input[name*="to" i]',
        'input[id*="dateto" i]', 'input[id*="enddate" i]',
        'input[id*="ToDate" i]', 'input[id*="DateTo" i]',
    ]

    # Convert dd/mm/yyyy → yyyy-mm-dd for type="date" inputs
    def _to_iso(dmy: str) -> str:
        try:
            d, m, y = dmy.split('/')
            return f'{y}-{m}-{d}'
        except Exception:
            return dmy

    iso_from = _to_iso(date_from)
    iso_to = _to_iso(date_to)

    for sel in from_selectors:
        try:
            el = page.locator(sel).first
            if el.count() > 0:
                inp_type = el.get_attribute('type') or ''
                el.fill(iso_from if inp_type == 'date' else date_from, timeout=5000)
                break
        except Exception:
            pass

    for sel in to_selectors:
        try:
            el = page.locator(sel).first
            if el.count() > 0:
                inp_type = el.get_attribute('type') or ''
                el.fill(iso_to if inp_type == 'date' else date_to, timeout=5000)
                break
        except Exception:
            pass


def _mark_failed(job_id: int, app, jlog: JobLogger):
    from models import TrackerAutomationJob, db
    from utils import pk_now
    with app.app_context():
        job = TrackerAutomationJob.query.get(job_id)
        if job:
            job.status = 'failed'
            job.finished_at = pk_now()
            job.log_text = jlog.full_log
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()


# ── Background thread launcher ────────────────────────────────────────────────

def launch_tracker_job(job_id: int, app):
    """Start the automation in a daemon background thread."""
    t = threading.Thread(
        target=run_tracker_job,
        args=(job_id, app),
        daemon=True,
        name=f'tracker-job-{job_id}',
    )
    t.start()
    return t
