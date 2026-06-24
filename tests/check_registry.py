"""
SE-03: Registry completeness check.
Verifies every non-static endpoint has either:
  - A permission mapping in ENDPOINT_PERMISSION_MAP, OR
  - An entry in ALLOWED_AUTHED_ENDPOINTS / ALLOWED_AUTHED_PREFIXES, OR
  - Is a known public endpoint (login, health, etc.)

Run: python tests/check_registry.py
Exit code 0 = pass, 1 = fail
"""
import sys, os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import app as app_module
from services.auth_utils import (
    get_required_permission,
    is_endpoint_allowed_for_any_authed,
)

# Public endpoints that skip auth entirely (handled in require_login)
PUBLIC_ENDPOINTS = {
    'login', 'pwa_manifest', 'service_worker', 'biometric_login',
    'app_logout', 'mobile_init', 'session_ping', 'app_check_update',
    'health_check', 'report_driver_profile_public',
    'set_new_password',
}


def run_check():
    app = app_module.app
    rules = sorted(app.url_map.iter_rules(), key=lambda r: r.endpoint)

    missing = []
    for rule in rules:
        ep = rule.endpoint
        if ep.startswith('static'):
            continue
        if ep in PUBLIC_ENDPOINTS:
            continue
        perm = get_required_permission(ep)
        if perm is not None:
            continue
        if is_endpoint_allowed_for_any_authed(ep):
            continue
        missing.append((ep, str(rule)))

    if missing:
        print(f"FAIL: {len(missing)} endpoints have no permission mapping and are not allowlisted:")
        for ep, rule in missing:
            print(f"  {ep}  ->  {rule}")
        return 1
    else:
        total = len([r for r in rules if not r.endpoint.startswith('static')])
        print(f"PASS: All {total} non-static endpoints have permission mapping or are allowlisted.")
        return 0


if __name__ == '__main__':
    sys.exit(run_check())
