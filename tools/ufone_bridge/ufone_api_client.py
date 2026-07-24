# -*- coding: utf-8 -*-
"""
Ufone BPOCOPS API Client (Complete)
====================================
Direct REST/SOAP-like client for Ufone BPOCOPS ambulance portal.

Standalone — NO Flask dependencies (use from any Python script).

Auth: AES-128-CBC encrypted login. reCAPTCHA is browser-only; server
does NOT validate the token, so we bypass it.

Session is persisted to ufone_session_{key}.json so restarts don't
re-login (avoids history entries).

USAGE:
    from services.ufone_api_client import UfoneClient
    c = UfoneClient("Faisalabad", "irmnch@fsd")
    c.connect()                          # login (or reuse session)
    ambulances = c.get_ambulance_list()  # 1394 ambulances
    tasks = c.get_ambulance_task_dashboard()
    c.save_task_comment(task_id=123, comment_type="Call to Driver",
                        comments="Called, no answer")
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from typing import Any, Optional

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

logger = logging.getLogger(__name__)

# ============================================================
#  CONFIG
# ============================================================
BASE_URL = "https://bpocops.ufone.com"
AES_KEY = AES_IV = b'9090808080809090'  # hardcoded in login page JS
SESSION_DIR = os.environ.get("UFONE_SESSION_DIR", os.getcwd())
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF = (1, 2, 4)
# Tuple (connect, read): connect fails FAST when Ufone server is down (so the
# poll loop doesn't hang 40s×3 = 2 min per cycle), read stays 40s for the heavy
# 30-40s getAmbulanceTaskReport query.
_REQUEST_TIMEOUT = (12, 40)


def to_ufone_date(value: str) -> str:
    """Normalize dates to Ufone's MM/DD/YYYY format (ASP.NET pages expect this).

    Accepts YYYY-MM-DD, MM/DD/YYYY, or empty. Leaves unknown strings unchanged.
    """
    if not value:
        return ""
    s = str(value).strip()
    if re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", s):
        return s
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%m/%d/%Y")
        except ValueError:
            return s
    return s


# ============================================================
#  CLIENT
# ============================================================
class UfoneClient:
    """Standalone Ufone BPOCOPS REST client."""

    def __init__(self, username: str, password: str, session_key: Optional[str] = None):
        self.username = username
        self.password = password
        self.session_key = session_key or username
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        })
        self.logged_in = False
        self._lock = threading.RLock()
        self.session_file = os.path.join(
            SESSION_DIR, f"ufone_session_{self.session_key}.json"
        )

    # ──────────────────────────────────────────────────────
    #  Crypto
    # ──────────────────────────────────────────────────────
    @staticmethod
    def _encrypt(text: str) -> str:
        c = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
        return base64.b64encode(c.encrypt(pad(text.encode(), 16))).decode()

    @staticmethod
    def _to_ufone_date(value: str) -> str:
        return to_ufone_date(value)
    # ──────────────────────────────────────────────────────
    #  Session persistence (cookies)
    # ──────────────────────────────────────────────────────
    def _save_session(self):
        try:
            with open(self.session_file, "w") as f:
                json.dump({
                    "cookies": self.session.cookies.get_dict(),
                    "username": self.username,
                    "saved_at": datetime.now().isoformat(),
                }, f)
        except Exception as e:
            logger.warning(f"session save failed: {e}")

    def _load_session(self) -> bool:
        if not os.path.exists(self.session_file):
            return False
        try:
            data = json.load(open(self.session_file))
            if data.get("username") != self.username:
                return False
            # age check (12 hours max)
            saved = data.get("saved_at", "")
            if saved:
                age = (datetime.now() - datetime.fromisoformat(saved)).total_seconds()
                if age > 12 * 3600:
                    return False
            for k, v in (data.get("cookies") or {}).items():
                self.session.cookies.set(k, v, domain="bpocops.ufone.com")
            return True
        except Exception:
            return False

    # ──────────────────────────────────────────────────────
    #  Login
    # ──────────────────────────────────────────────────────
    def login(self):
        """Login with AES-encrypted credentials (captcha bypassed)."""
        r = self.session.get(f"{BASE_URL}/Login.aspx", timeout=_REQUEST_TIMEOUT)
        vs = re.search(r'__VIEWSTATE"\s+value="([^"]+)"', r.text)
        vsg = re.search(r'__VIEWSTATEGENERATOR"\s+value="([^"]+)"', r.text)
        ev = re.search(r'__EVENTVALIDATION"\s+value="([^"]+)"', r.text)
        if not (vs and vsg and ev):
            raise RuntimeError("Login page parse failed (ViewState missing)")
        data = {
            "__VIEWSTATE": vs.group(1),
            "__VIEWSTATEGENERATOR": vsg.group(1),
            "__EVENTVALIDATION": ev.group(1),
            "HDusername": self._encrypt(self.username),
            "HDPassword": self._encrypt(self.password),
            "txtUserName": "",
            "txtPassword": "",
            "responseCaptcha": "bypass",  # server doesn't validate
            "btnLogin": "Login",
        }
        r = self.session.post(f"{BASE_URL}/Login.aspx", data=data,
                              allow_redirects=True, timeout=_REQUEST_TIMEOUT)
        if "Welcome" in r.url or "Dashboard" in r.text:
            self.logged_in = True
            self._save_session()
            return True
        raise RuntimeError(f"Login failed. Final URL: {r.url}")

    def connect(self, reuse_session: bool = True):
        """Login or reuse persisted session. Verifies with a probe call."""
        with self._lock:
            if reuse_session and self._load_session():
                # Quick probe — default 40s x3 retries would stall the UI
                try:
                    self.logged_in = True  # _call requires this
                    self._call("Dashboard.aspx", "checkSessionIsLogin",
                               visit_page=False, timeout=10, retries=1)
                    return
                except Exception:
                    self.logged_in = False
                    logger.info("ufone session expired/slow, re-login")
            self.login()

    # ──────────────────────────────────────────────────────
    #  Core AJAX call
    # ──────────────────────────────────────────────────────
    def _build_body(self, params: Optional[dict]) -> str:
        """Build JS-style body: {'k':'v', 'k2':'v2'}"""
        if not params:
            return "{}"
        items = ", ".join(f"'{k}':'{v}'" for k, v in params.items())
        return "{" + items + "}"

    def _call(self, page: str, method: str, params: Optional[dict] = None,
              visit_page: bool = True, raw: bool = False,
              timeout: Optional[float] = None,
              retries: Optional[int] = None) -> Any:
        """Call ASP.NET page method. Returns response['d'] or raw response.

        timeout/retries override module defaults for interactive calls
        that must fail fast instead of blocking the UI.
        """
        if not self.logged_in:
            raise RuntimeError("Pehle connect()/login() call karein.")
        req_timeout = timeout or _REQUEST_TIMEOUT
        attempts = retries if retries is not None else _RETRY_ATTEMPTS
        url = f"{BASE_URL}/{page}/{method}"
        # One HTTP call at a time per client. ASP.NET SessionId is locked
        # server-side for the duration of a request — concurrent calls on the
        # same cookie jar queue up and appear as Read timeouts.
        with self._lock:
            if visit_page:
                try:
                    self.session.get(f"{BASE_URL}/{page}", timeout=req_timeout)
                except Exception:
                    pass  # non-critical
            body = self._build_body(params)
            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE_URL}/{page}",
            }
            # retry on transient errors
            last_err = None
            for attempt in range(attempts):
                try:
                    r = self.session.post(url, data=body.encode("utf-8"),
                                          headers=headers, timeout=req_timeout)
                    if r.status_code == 200:
                        try:
                            data = r.json()
                            return data if raw else data.get("d", data)
                        except ValueError:
                            return r.text
                    if r.status_code == 302 or r.status_code == 401:
                        # session expired / unauthorized — re-login once
                        if attempt == 0:
                            try:
                                self.login()
                                continue
                            except Exception:
                                pass
                        last_err = f"HTTP {r.status_code}: {r.text[:150]}"
                except (requests.ConnectionError, requests.Timeout) as e:
                    last_err = str(e)
                    if attempt < attempts - 1:
                        time.sleep(_RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)])
            raise RuntimeError(f"{page}/{method} failed: {last_err}")

    # ══════════════════════════════════════════════════════
    #  MASTER DATA
    # ══════════════════════════════════════════════════════
    def get_districts(self) -> list:
        return self._call("AmbulanceAssignment.aspx", "getDistrict")

    def get_districts_anonymous(self) -> list:
        """District master list without login (same WebMethod as portal)."""
        return self._call_anonymous(
            "AmbulanceAssignment.aspx", "getDistrict", {}) or []

    def get_tehsils(self, district_code: str) -> list:
        return self._call("AmbulanceAssignment.aspx", "getTehsil",
                          {"districtCode": str(district_code)})

    def get_union_councils(self, tehsil_code: str) -> list:
        return self._call("AmbulanceAssignment.aspx", "getUnionCouncil",
                          {"tehsilCode": str(tehsil_code)})

    # ══════════════════════════════════════════════════════
    #  LIVE TRACKING
    # ══════════════════════════════════════════════════════
    def get_ambulance_list(self, district: str = "", tehsil: str = "",
                           union_council: str = "") -> list:
        """All ambulances (1394 with empty filters) or filtered."""
        return self._call("Amb_loc.aspx", "getAmbulanceList", {
            "District": district, "Tehsil": tehsil, "UnionCouncil": union_council,
        })

    def get_ambulance_near(self, district: str = "", tehsil: str = "",
                           union_council: str = "", ambulance: str = "") -> list:
        """Live near ambulances. district must be non-empty to get results."""
        return self._call("TrackingAmbulance.aspx", "getAmbulanceNear", {
            "District": district, "Tehsil": tehsil,
            "UnionCouncil": union_council, "Amnbulance": ambulance,
        })

    def get_all_ambulances_all_districts(self) -> list:
        """Iterate all districts, collect ambulances (slower but complete)."""
        all_items = []
        for d in self.get_districts():
            code = str(d.get("district_code"))
            try:
                items = self.get_ambulance_near(district=code)
                all_items.extend(items)
            except Exception as e:
                logger.warning(f"district {code} failed: {e}")
        return all_items

    # ══════════════════════════════════════════════════════
    #  TASK MANAGEMENT
    # ══════════════════════════════════════════════════════
    def get_task_dashboard(self, start_date: str = "", end_date: str = "",
                           district: str = "", tehsil: str = "",
                           union_council: str = "", visit_page: bool = True) -> list:
        """Today's active/incomplete tasks. Dates: YYYY-MM-DD or MM/DD/YYYY."""
        return self._call("Dashboard.aspx", "getAmbulanceTaskDashboard", {
            "startDate": self._to_ufone_date(start_date),
            "endDate": self._to_ufone_date(end_date),
            "District": district, "Tehsil": tehsil, "UnionCouncil": union_council,
        }, visit_page=visit_page)

    def get_task_detail(self, task_id, quick: bool = False) -> dict:
        """Full task detail (76 fields). Returns single dict.

        quick=True: interactive UI call — skip page visit, short timeout,
        single attempt so the popup never hangs for minutes.
        """
        kw = {'visit_page': False, 'timeout': 12, 'retries': 1} if quick else {}
        r = self._call("Dashboard.aspx", "getTaskDetail",
                       {"id": str(task_id)}, **kw)
        return r[0] if isinstance(r, list) and r else (r or {})

    def get_task_comments(self, task_id, quick: bool = False) -> list:
        kw = {'visit_page': False, 'timeout': 12, 'retries': 1} if quick else {}
        return self._call("TaskReport.aspx", "getTaskComments",
                          {"taskId": str(task_id)}, **kw)

    def get_emergency_tasks(self, start_date: str = "", end_date: str = "",
                            district: str = "", tehsil: str = "",
                            union_council: str = "", task_id: str = "",
                            visit_page: bool = True) -> list:
        """Emergency task report (large export). Dates: YYYY-MM-DD or MM/DD/YYYY."""
        return self._call("ReportEmergencyTask.aspx", "getAmbulanceTaskReport", {
            "startDate": self._to_ufone_date(start_date),
            "endDate": self._to_ufone_date(end_date),
            "District": district, "Tehsil": tehsil,
            "UnionCouncil": union_council, "TaskId": task_id,
        }, visit_page=visit_page)
    # ══════════════════════════════════════════════════════
    #  TASK ACTIONS (write operations)
    # ══════════════════════════════════════════════════════
    def save_task_comment(self, task_id, comment_type: str, comments: str):
        """Add comment to a task."""
        return self._call("TaskReport.aspx", "saveTaskComments", {
            "taskId": str(task_id), "CommentType": comment_type,
            "Comments": comments,
        }, raw=True)

    def save_task_feedback(self, task_id, feedback: str):
        """Add feedback to a task."""
        return self._call("TaskReport.aspx", "saveTaskFeedback", {
            "taskId": str(task_id), "Feedback": feedback,
        }, raw=True)

    def set_task_complete(self, task_id, amb_id, received_by: str = "",
                          is_received: str = ""):
        """Mark task complete / free ambulance."""
        return self._call("Dashboard.aspx", "setFreeAmbulance", {
            "id": str(amb_id), "aaId": str(task_id),
            "ReceivedBy": received_by, "isReceived": is_received,
        }, raw=True)

    # ══════════════════════════════════════════════════════
    #  REPORTS
    # ══════════════════════════════════════════════════════
    def get_distance_report(self, start_date: str = "", end_date: str = "",
                            district: str = "", ambulance: str = "") -> list:
        """Vehicle distance report."""
        return self._call("VehicleDistance.aspx", "GetAmbDistanceReportNew", {
            "startDate": self._to_ufone_date(start_date),
            "endDate": self._to_ufone_date(end_date),
            "District": district, "Amnbulance": ambulance,
        })

    def _call_anonymous(self, page: str, method: str,
                        params: Optional[dict] = None,
                        timeout: Optional[float] = None,
                        retries: Optional[int] = None) -> Any:
        """POST a WebMethod with a fresh session (no login cookies).

        Some BPOCOPS methods (notably under-maintenance) are district-scoped
        when called with a logged-in district account, but return the full
        statewide list when called without auth cookies.
        """
        req_timeout = timeout or _REQUEST_TIMEOUT
        attempts = retries if retries is not None else _RETRY_ATTEMPTS
        url = f"{BASE_URL}/{page}/{method}"
        body = self._build_body(params)
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": f"{BASE_URL}/{page}",
        }
        last_err = None
        for attempt in range(attempts):
            try:
                with requests.Session() as anon:
                    r = anon.post(url, data=body.encode("utf-8"),
                                  headers=headers, timeout=req_timeout)
                if r.status_code == 200:
                    try:
                        data = r.json()
                        return data.get("d", data)
                    except ValueError:
                        return r.text
                last_err = f"HTTP {r.status_code}: {r.text[:150]}"
            except (requests.ConnectionError, requests.Timeout) as e:
                last_err = str(e)
                if attempt < attempts - 1:
                    time.sleep(_RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)])
        raise RuntimeError(f"{page}/{method} (anonymous) failed: {last_err}")

    def get_maintenance(self) -> list:
        """Ambulances currently under maintenance (all districts).

        Portal WebMethod requires startDate/endDate keys (empty = current open).
        Calling without params returns HTTP 500.

        Important: a Faisalabad (district) login session returns only that
        district. Anonymous call returns the full statewide open list.
        """
        return self._call_anonymous(
            "AmbulanceUnderMaintenance.aspx",
            "getAmbulanceUnderMaintenance",
            {"startDate": "", "endDate": ""},
        )

    def get_maintenance_log(self, maint_id, start_date: str = "") -> list:
        """Update Log rows for one open-maintenance record (portal View popup).

        Portal JS: {'startDate': $('#startDate').val(), 'id': id}
        Empty list = no updates yet ("No record found").
        Works anonymously with the same params.
        """
        return self._call_anonymous(
            "AmbulanceUnderMaintenance.aspx",
            "getAmbulanceUnderMaintenance2",
            {
                "startDate": self._to_ufone_date(start_date) if start_date else "",
                "id": str(maint_id),
            },
        )

    def get_maintenance_history(self, start_date: str = "", end_date: str = "",
                                district: str = "") -> list:
        return self._call("ReportMaintenanceHistory.aspx",
                          "getMaintenanceHistory", {
            "startDate": self._to_ufone_date(start_date),
            "endDate": self._to_ufone_date(end_date),
            "District": district,
        })

    def get_dashboard_count_ras_cow(self) -> list:
        """RAS / COW totals."""
        return self._call("Dashboard.aspx", "getDashboadCountRASandCOW")

    def get_patients(self, start_date: str = "", end_date: str = "",
                     district: str = "") -> list:
        """Patient registration report (regular)."""
        return self._call("ReportPatient.aspx", "getPatientReport", {
            "startDate": self._to_ufone_date(start_date),
            "endDate": self._to_ufone_date(end_date),
            "District": district,
        })

    def get_patients_ussd(self, start_date: str = "", end_date: str = "",
                          district: str = "") -> list:
        return self._call("ReportPatientUSSD.aspx", "getPatientReportUSSD", {
            "startDate": self._to_ufone_date(start_date),
            "endDate": self._to_ufone_date(end_date),
            "District": district,
        })

    def get_daily_task_count(self, start_date: str = "", end_date: str = "") -> list:
        return self._call("ReportDailyTaskCount.aspx", "getDailyTaskCount", {
            "startDate": self._to_ufone_date(start_date),
            "endDate": self._to_ufone_date(end_date),
        })
    def get_monthly_task_count(self, month: str = "") -> list:
        return self._call("ReportMonthlyTaskCount.aspx", "getMonthlyTaskCount", {
            "month": month,
        })

    # ══════════════════════════════════════════════════════
    #  PATIENT LOOKUP (used by tracking page)
    # ══════════════════════════════════════════════════════
    def get_patient_list(self, phone: str = "", name: str = "") -> list:
        return self._call("PatientRegistration.aspx", "getPatientList", {
            "phone": phone, "name": name,
        })

    # ══════════════════════════════════════════════════════
    #  ACCOUNT
    # ══════════════════════════════════════════════════════
    def update_password(self, old_password: str, new_password: str):
        """Change account password."""
        return self._call("Welcome.aspx", "updatePassword", {
            "oldPassword": old_password, "newPassword": new_password,
        }, raw=True)

    def check_session(self) -> bool:
        """Returns True if session is still alive."""
        try:
            r = self._call("Dashboard.aspx", "checkSessionIsLogin",
                           visit_page=True)
            return r == "yes" or r is True
        except Exception:
            return False


# ============================================================
#  CLI self-test
# ============================================================
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if len(sys.argv) < 3:
        print("Usage: python ufone_api_client.py <username> <password>")
        sys.exit(0)
    c = UfoneClient(sys.argv[1], sys.argv[2])
    c.connect()
    print(f"\n✓ Connected. Session: {c.session_file}\n")
    amb = c.get_ambulance_list()
    print(f"Ambulances: {len(amb)}")
    if amb:
        print(f"First: {amb[0].get('Reg_No')} @ {amb[0].get('Latitude')},{amb[0].get('Logitude')}")
