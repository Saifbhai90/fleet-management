"""Unit checks for login/biometric helpers (no database)."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
os.chdir(ROOT)
for path in (ROOT, os.path.join(ROOT, 'services')):
    if path not in sys.path:
        sys.path.insert(0, path)

from services.auth_utils import (  # noqa: E402
    csrf_exempt_origin_is_allowed,
    login_lockout_key,
    login_username_variants,
    normalize_login_username,
)


def test_normalize_login_username_cnic():
    assert normalize_login_username('32304-0907226-5') == '3230409072265'
    assert normalize_login_username('3230409072265') == '3230409072265'
    assert normalize_login_username('AdminUser') == 'AdminUser'
    assert normalize_login_username('  admin  ') == 'admin'


def test_login_username_variants_include_hyphen_and_digits():
    variants = [v.lower() for v in login_username_variants('32304-0907226-5')]
    assert '32304-0907226-5' in variants
    assert '3230409072265' in variants
    assert 'admin' in [v.lower() for v in login_username_variants('Admin')]


def test_login_lockout_key_canonical():
    assert login_lockout_key('32304-0907226-5') == '3230409072265'
    assert login_lockout_key('Admin') == 'admin'


def test_csrf_exempt_origin_same_host_and_webview():
    host = 'https://fleet.example.com'
    assert csrf_exempt_origin_is_allowed('https://fleet.example.com', '', host) is True
    assert csrf_exempt_origin_is_allowed('https://localhost', '', host) is True
    assert csrf_exempt_origin_is_allowed('http://localhost:8080', '', host) is True
    assert csrf_exempt_origin_is_allowed('capacitor://localhost', '', host) is True
    assert csrf_exempt_origin_is_allowed('', 'https://fleet.example.com/login', host) is True


def test_csrf_exempt_origin_rejects_prefix_spoof_and_missing():
    host = 'https://fleet.example.com'
    assert csrf_exempt_origin_is_allowed('https://localhost.evil.example', '', host) is False
    assert csrf_exempt_origin_is_allowed('https://evil.example', '', host) is False
    assert csrf_exempt_origin_is_allowed('', '', host) is False
    assert csrf_exempt_origin_is_allowed(None, None, host) is False


if __name__ == '__main__':
    test_normalize_login_username_cnic()
    test_login_username_variants_include_hyphen_and_digits()
    test_login_lockout_key_canonical()
    test_csrf_exempt_origin_same_host_and_webview()
    test_csrf_exempt_origin_rejects_prefix_spoof_and_missing()
    print('test_login_auth.py: ok')
