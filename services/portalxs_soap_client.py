# -*- coding: utf-8 -*-
"""
PortalXS Direct SOAP Client (FULLY CRACKED - NO BROWSER!)
==========================================================
Mobile app (TW PX) wala asli API. Local Triple DES encryption.

Endpoint : https://tw.portalxs.com/TWTraxX/TrackingServices.asmx
Crypto   :
  Request encrypt:  3DES-ECB, key=MD5("TWSouth"), PKCS7, Base64
  Response decrypt: same key (serverKey) for most fields
  Device reg:        key=MD5("TrackingWorldPVTLtd") (appKey)

FLOW:
  1. Device_Registration -> get numeric uniqueID
  2. ConnectApp_Login(user,pass) -> get loginid token
  3. Use loginid for all data calls (vehicles, positions, history, ...)

USAGE:
  client = PortalXSClient("username", "password")
  client.connect()                  # register device + login (1 entry)
  vehicles = client.get_vehicles()  # all vehicles + their live lat/lon
  nearby = client.get_nearest_vehicles(reg)  # neighbours of ONE vehicle
  history = client.get_history(reg, fdt, tdt)
"""
import base64
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime

import requests
from Crypto.Cipher import DES3
from Crypto.Util.Padding import pad, unpad

# ============================================================
#  CONFIG (from APK .env)
# ============================================================
SOAP_URL    = "https://tw.portalxs.com/TWTraxX/TrackingServices.asmx"
SOAP_NS     = "http://tempuri.org/"
SERVER_KEY  = "TWSouth"
APP_KEY     = "TrackingWorldPVTLtd"
APP_NAME    = "TWPX"

# Session file in a writable temp directory (works on Render + local)
_SESSION_DIR = os.environ.get('PORTALXS_SESSION_DIR', os.path.join(os.path.dirname(__file__), '..'))

# Transport retry: attempts + backoff seconds (only for connection/timeout errors)
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF = (1, 2, 4)
_CONNECT_ATTEMPTS = 3


def _is_crypto_error(exc: Exception) -> bool:
    msg = str(exc or '').lower()
    return 'padding' in msg or 'decrypt' in msg or 'invalid token' in msg


def _session_file_for(session_key) -> str:
    """Account-specific session file so multiple accounts never collide."""
    key = str(session_key) if session_key else 'default'
    safe = re.sub(r'[^A-Za-z0-9_-]', '_', key)
    return os.path.join(_SESSION_DIR, f"portalxs_session_{safe}.json")

_SK = hashlib.md5(SERVER_KEY.encode()).digest()       # 16 bytes
_AK = hashlib.md5(APP_KEY.encode()).digest()           # 16 bytes


# -------------------- crypto --------------------
def enc(text) -> str:
    """Encrypt with serverKey (for requests)."""
    data = str(text).encode("utf-8")
    cipher = DES3.new(_SK, DES3.MODE_ECB)
    return base64.b64encode(cipher.encrypt(pad(data, 8))).decode()


def dec_server(b64: str) -> str:
    """Decrypt with serverKey (most response fields)."""
    cipher = DES3.new(_SK, DES3.MODE_ECB)
    return unpad(cipher.decrypt(base64.b64decode(b64)), 8).decode("utf-8")


def dec_app(b64: str) -> str:
    """Decrypt with appKey (device registration uniqueID)."""
    cipher = DES3.new(_AK, DES3.MODE_ECB)
    return unpad(cipher.decrypt(base64.b64decode(b64)), 8).decode("utf-8")


def smart_dec(val):
    """Try server then app key. Returns original if not encrypted."""
    if not isinstance(val, str) or not val or len(val) < 8:
        return val
    for fn in (dec_server, dec_app):
        try:
            return fn(val)
        except Exception:
            continue
    return val


def decrypt_tree(obj):
    """Recursively decrypt all string values in JSON response."""
    if isinstance(obj, dict):
        return {k: (decrypt_tree(v) if k != "responseCode" else v)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [decrypt_tree(i) for i in obj]
    return smart_dec(obj)


# ============================================================
#  CLIENT
# ============================================================
class PortalXSClient:
    def __init__(self, username=None, password=None, device_id=None, session_key=None):
        self.username = username
        self.password = password
        self.device_id = device_id or str(uuid.uuid4().int)[:15]
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "TW-PX/5.0.4 Android"})
        self.unique_id = None
        self.login_id = None
        self.profile = None
        # Session persisted per account (session_key) — prevents multi-account collision
        self.session_file = _session_file_for(session_key or username)

    # ---------------- persistence ----------------
    def save_session(self):
        with open(self.session_file, "w") as f:
            json.dump({
                "device_id": self.device_id,
                "unique_id": self.unique_id,
                "login_id": self.login_id,
                "saved_at": datetime.now().isoformat(),
            }, f, indent=2)

    def load_session(self):
        if not os.path.exists(self.session_file):
            return False
        try:
            with open(self.session_file) as f:
                d = json.load(f)
        except (ValueError, OSError):
            return False
        self.device_id = d.get("device_id", self.device_id)
        self.unique_id = d.get("unique_id")
        self.login_id = d.get("login_id")
        return bool(self.unique_id)

    def _clear_session_file(self):
        """Drop a stale/corrupt on-disk session so the next connect starts fresh."""
        try:
            if os.path.exists(self.session_file):
                os.remove(self.session_file)
        except OSError:
            pass
        self.login_id = None
        self.unique_id = None

    # ---------------- transport with retry ----------------
    def _post_with_retry(self, data, headers):
        """POST with retry + exponential backoff on transport errors only
        (connection/timeout). SOAP faults are NOT retried."""
        last_exc = None
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                return self.session.post(SOAP_URL, data=data, headers=headers, timeout=30)
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                if attempt < _RETRY_ATTEMPTS - 1:
                    time.sleep(_RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)])
        raise last_exc

    # ---------------- SOAP core ----------------
    def _soap(self, method, params_plain):
        body = "".join(f"<{k}>{enc(v)}</{k}>" for k, v in params_plain.items())
        env = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body><{method} xmlns="{SOAP_NS}">{body}</{method}></soap:Body>
</soap:Envelope>"""
        r = self._post_with_retry(env.encode(),
            headers={"Content-Type": "text/xml; charset=utf-8",
                     "SOAPAction": f"{SOAP_NS}{method}"})
        m = re.search(rf"<{method}Result>(.*?)</{method}Result>", r.text, re.DOTALL)
        if not m:
            raise RuntimeError(f"No result for {method}: {r.text[:300]}")
        text = m.group(1).strip()
        if text.startswith("{") or text.startswith("["):
            return decrypt_tree(json.loads(text))
        return smart_dec(text)

    # ---------------- bootstrap ----------------
    def register_device(self):
        """Device_Registration -> numeric uniqueID."""
        r = self._soap("Device_Registration", {
            "device_unique_identifier": self.device_id})
        msg = r.get("responseMsg", "") if isinstance(r, dict) else str(r)
        uid_enc = msg.replace("Unique ID for this device is:", "").strip()
        self.unique_id = dec_app(uid_enc)   # decrypt with APP key
        return self.unique_id

    def login(self):
        """ConnectApp_Login -> loginid token."""
        if not self.unique_id:
            self.register_device()
        r = self._soap("ConnectApp_Login", {
            "uniqueID": self.unique_id,
            "device_unique_identifier": self.device_id,
            "userName": self.username,
            "password": self.password,
        })
        if isinstance(r, dict):
            code = str(r.get("responseCode", ""))
            self.login_id = r.get("loginid")
            self.profile = r
            if code == "200":
                return r
            raise RuntimeError(f"Login failed ({code}): {r.get('responseMsg')}")
        raise RuntimeError(f"Unexpected: {r}")

    def connect(self, reuse_session=True):
        """Full connect: reuse session OR register + login (1 history entry)."""
        if reuse_session and self.load_session() and self.login_id:
            try:
                self.get_vehicles()
                return
            except Exception:
                self._clear_session_file()
        last_exc = None
        for attempt in range(_CONNECT_ATTEMPTS):
            try:
                self.register_device()
                self.login()
                self.save_session()
                return
            except Exception as e:
                last_exc = e
                self._clear_session_file()
                if attempt < _CONNECT_ATTEMPTS - 1 and _is_crypto_error(e):
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise
        if last_exc:
            raise last_exc

    def _ok(self):
        if not self.login_id:
            raise RuntimeError("Pehle connect()/login() call karein.")

    # ---------------- data methods ----------------
    def get_vehicles(self):
        """Live positions for ALL vehicles (this method returns positions too)."""
        self._ok()
        r = self._soap("ConnectApp_VehiclesListByLoginid", {
            "uniqueID": self.unique_id,
            "device_unique_identifier": self.device_id,
            "loginid": self.login_id,
        })
        if isinstance(r, dict):
            return r.get("_vehicleData") or r.get("_Vehicles") or []
        return r

    def get_nearest_vehicles(self, regno):
        """Vehicles closest to one vehicle, nearest first, with live position.

        The method name is plural but it anchors on a single vehicle: the server
        feeds regno straight into geography::Point, so a comma-joined list comes
        back as ``'geography::Point' failed because parameter 1 is not allowed
        to be null`` instead of several vehicles' neighbours. Callers that need
        neighbours for more than one vehicle must call this once per vehicle.
        """
        self._ok()
        if isinstance(regno, (list, tuple)):
            if len(regno) != 1:
                raise ValueError(
                    'get_nearest_vehicles accepts one regno; '
                    'the upstream endpoint cannot batch.')
            regno = regno[0]
        r = self._soap("ConnectApp_NearestVehiclesListByRegNo", {
            "uniqueID": self.unique_id,
            "device_unique_identifier": self.device_id,
            "loginid": self.login_id,
            "regno": regno,
        })
        if isinstance(r, dict):
            return r.get("_vehicleData") or r.get("_Vehicles") or []
        return r or []

    def _soap_dates(self, method, enc_params, plain_dates):
        """SOAP call with encrypted params + PLAIN date params (fdt/tdt).
        Server expects dates as XSD dateTime (plain), not encrypted."""
        body_parts = [f"<{k}>{enc(v)}</{k}>" for k, v in enc_params.items()]
        body_parts += [f"<{k}>{v}</{k}>" for k, v in plain_dates.items()]
        body = "".join(body_parts)
        envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body><{method} xmlns="{SOAP_NS}">{body}</{method}></soap:Body>
</soap:Envelope>"""
        r = self._post_with_retry(envelope.encode(),
            headers={"Content-Type": "text/xml; charset=utf-8",
                     "SOAPAction": f"{SOAP_NS}{method}"})
        m = re.search(rf"<{method}Result>(.*?)</{method}Result>", r.text, re.DOTALL)
        if not m:
            fm = re.search(r"<faultstring>(.*?)</faultstring>", r.text, re.DOTALL)
            raise RuntimeError(f"SOAP fault in {method}: {fm.group(1)[:150] if fm else r.text[:150]}")
        text = m.group(1).strip()
        if text.startswith("{") or text.startswith("["):
            return decrypt_tree(json.loads(text))
        return smart_dec(text)

    def get_history(self, regno, from_dt, to_dt):
        """Vehicle history (GPS points). Returns list of {RegNo, RecordDateTime,
        LAT, LON, Speed, Reason, LandMark, Direction}."""
        self._ok()
        r = self._soap_dates("ConnectApp_GetVehicleHistory",
            enc_params={
                "uniqueID": self.unique_id,
                "device_unique_identifier": self.device_id,
                "regNo": regno,
            },
            plain_dates={"fdt": from_dt, "tdt": to_dt})
        if isinstance(r, dict):
            for v in r.values():
                if isinstance(v, list):
                    return v
        return r

    def get_alerts(self):
        self._ok()
        r = self._soap("ConnectApp_GetAlertsByLOGINID", {
            "uniqueID": self.unique_id,
            "device_unique_identifier": self.device_id,
            "loginid": self.login_id,
        })
        if isinstance(r, dict):
            for v in r.values():
                if isinstance(v, list):
                    return v
        return r

    def get_geofences(self):
        self._ok()
        r = self._soap("ConnectApp_GetFencesByLOGINID", {
            "uniqueID": self.unique_id,
            "device_unique_identifier": self.device_id,
            "loginid": self.login_id,
        })
        if isinstance(r, dict):
            for v in r.values():
                if isinstance(v, list):
                    return v
        return r

    def get_trips(self, regno, from_dt, to_dt):
        """Vehicle trips. Returns list of {RegNo, IGON_RDT, IGON_LAT/LON,
        IGOFF_RDT, IGOFF_LAT/LON, Mileage, TravelTimeS, MaxSpeed, AvgSpeed,
        TripStatus}."""
        self._ok()
        r = self._soap_dates("ConnectApp_GetTrips",
            enc_params={
                "uniqueID": self.unique_id,
                "device_unique_identifier": self.device_id,
                "regNo": regno,
            },
            plain_dates={"fdt": from_dt, "tdt": to_dt})
        if isinstance(r, dict):
            for v in r.values():
                if isinstance(v, list):
                    return v
        return r

    def get_mileage(self, regno, from_dt, to_dt):
        """Mileage report. Returns list of {Distance, PToP}."""
        self._ok()
        r = self._soap_dates("ConnectApp_GetMileageReport",
            enc_params={
                "uniqueID": self.unique_id,
                "device_unique_identifier": self.device_id,
                "regNo": regno,
            },
            plain_dates={"fdt": from_dt, "tdt": to_dt})
        if isinstance(r, dict):
            for v in r.values():
                if isinstance(v, list):
                    return v
        return r

    def get_fleet_report(self, regno, from_dt, to_dt):
        """Fleet report (per vehicle). Returns list of {RegNo, VehicleScore,
        FuelConsumption, Trips, Duration, Distance, Alerts}."""
        self._ok()
        r = self._soap_dates("ConnectApp_GetReports",
            enc_params={
                "uniqueID": self.unique_id,
                "device_unique_identifier": self.device_id,
                "regNo": regno,
            },
            plain_dates={"fdt": from_dt, "tdt": to_dt})
        if isinstance(r, dict):
            for v in r.values():
                if isinstance(v, list):
                    return v
        return r

    def get_trends(self, regno, from_dt, to_dt):
        """Daily trends. Returns list of {RDT, Mileage, TravelTimeH, Alerts}."""
        self._ok()
        r = self._soap_dates("ConnectApp_GetTrends",
            enc_params={
                "uniqueID": self.unique_id,
                "device_unique_identifier": self.device_id,
                "regNo": regno,
            },
            plain_dates={"fdt": from_dt, "tdt": to_dt})
        if isinstance(r, dict):
            for v in r.values():
                if isinstance(v, list):
                    return v
        return r

    def get_available_reports(self):
        """List of report types available. Returns list of {ApplicationName}."""
        self._ok()
        r = self._soap("ConnectApp_GetReportName", {
            "uniqueID": self.unique_id,
            "device_unique_identifier": self.device_id,
            "appName": APP_NAME,
        })
        if isinstance(r, dict):
            for v in r.values():
                if isinstance(v, list):
                    return v
        return r


# ============================================================
#  CLI
# ============================================================
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python portalxs_soap_client.py <username> <password>")
        print()
        print("Demo (no login):")
        c = PortalXSClient()
        c.register_device()
        print(f"  Device registered, uniqueID: {c.unique_id}")
        sys.exit(0)

    c = PortalXSClient(sys.argv[1], sys.argv[2])
    c.connect()
    print(f"\nLogin ID: {c.login_id}")
    print(f"Profile: {json.dumps(c.profile, indent=2, ensure_ascii=False)[:600]}")

    vs = c.get_vehicles()
    print(f"\nVehicles: {len(vs) if isinstance(vs,list) else '?'}")
    print(json.dumps(vs[:2] if isinstance(vs,list) else vs, indent=2, ensure_ascii=False)[:600])
