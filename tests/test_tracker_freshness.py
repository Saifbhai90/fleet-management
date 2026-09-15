"""Unit checks for Tracker P0/P1 freshness helpers (no live SOAP)."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import patch
import os
import sys
import threading
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
os.chdir(ROOT)
for path in (ROOT, os.path.join(ROOT, 'services')):
    if path not in sys.path:
        sys.path.insert(0, path)

from services import portalxs_service as portalxs_svc  # noqa: E402
from services.portalxs_coordination import (  # noqa: E402
    current_portalxs_operation,
    is_portalxs_bulk_operation,
    portalxs_work,
)
from services.portalxs_service import (  # noqa: E402
    GPS_DELAYED_MAX_SEC,
    GPS_LIVE_MAX_SEC,
    _POSITION_FETCH_WARNINGS,
    _BULK_SYNC_WARNING,
    _parse_rdt,
    _set_cached_positions,
    annotate_vehicle_freshness,
    build_live_positions_payload,
    classify_feed_status,
    classify_gps_status,
    classify_live_status,
    consume_position_warning,
    fetch_live_positions,
    get_cached_positions,
    get_live_feed_meta,
    get_position_warning,
    gps_age_sec,
    serve_live_positions,
)


def test_parse_rdt_real_formats():
    now = datetime(2026, 9, 13, 22, 50, 0)
    samples = {
        '2026-09-13 01:19:04': datetime(2026, 9, 13, 1, 19, 4),
        '2026-09-13T01:19:04': datetime(2026, 9, 13, 1, 19, 4),
        '2026-09-13 01:19:04.000000': datetime(2026, 9, 13, 1, 19, 4),
        '13/09/2026 01:19:04': datetime(2026, 9, 13, 1, 19, 4),
        '9/13/2026 1:19:04 AM': datetime(2026, 9, 13, 1, 19, 4),
        '9/12/2026 2:00:24 PM': datetime(2026, 9, 12, 14, 0, 24),
    }
    for raw, expected in samples.items():
        parsed = _parse_rdt(raw)
        assert parsed == expected, (raw, parsed, expected)
    assert _parse_rdt('') is None
    assert _parse_rdt('not-a-date') is None
    assert gps_age_sec('2026-09-13 22:49:50', now=now) == 10
    assert gps_age_sec('2026-09-13 22:49:30', now=now) == 30
    assert gps_age_sec('2026-09-13 22:49:15', now=now) == 45
    assert gps_age_sec('2026-09-13 22:49:00', now=now) == 60
    assert gps_age_sec('2026-09-13 22:45:00', now=now) == 300
    assert gps_age_sec('garbage', now=now) is None
    # naive PK vs UTC: 22:50 PK must not be treated as UTC (would look ~5h off)
    assert gps_age_sec('2026-09-13 22:50:00', now=now) == 0
    _ = now  # keep now used if samples change


def test_gps_status_thresholds():
    assert classify_gps_status(10, True) == 'live'
    assert classify_gps_status(60, True) == 'live'
    assert classify_gps_status(61, True) == 'delayed'
    assert classify_gps_status(300, True) == 'delayed'
    assert classify_gps_status(301, True) == 'offline'
    assert classify_gps_status(None, True) == 'unknown'
    assert classify_gps_status(10, False) == 'unknown'
    assert GPS_LIVE_MAX_SEC == 60
    assert GPS_DELAYED_MAX_SEC == 300


def test_idle_logic_unchanged():
    assert classify_live_status('Moving', 'On since x', 30, 71) == 'Moving'
    assert classify_live_status('Stopped', 'On since x', 30, 71) == 'Idle'
    assert classify_live_status('Stopped', 'Off since x', 30, 71) == 'Stopped'
    assert classify_live_status('Stopped', 'On since x', None, None) == 'Unknown'


def test_annotate_does_not_mutate_or_change_status():
    now = datetime(2026, 9, 13, 22, 50, 0)
    src = {
        'RegNo': 'LEG-18-2874',
        'LAT': 30.1,
        'LON': 71.2,
        'VehicleStatus': 'Moving',
        'RDT': '2026-09-13 22:49:50',
    }
    out = annotate_vehicle_freshness([src], now=now)
    assert src.get('gps_age_sec') is None
    assert out[0]['VehicleStatus'] == 'Moving'
    assert out[0]['gps_age_sec'] == 10
    assert out[0]['gps_status'] == 'live'


def test_feed_status_never_live_on_failed_soap():
    vehicles = [{'gps_age_sec': 8, 'gps_status': 'live'}]
    assert classify_feed_status({'soap_ok': False, 'source': 'cache', 'cache_age_sec': 20}, vehicles) == 'DELAYED'
    assert classify_feed_status({'soap_ok': False, 'source': 'db', 'cache_age_sec': 10}, vehicles) == 'OFFLINE'
    assert classify_feed_status({'soap_ok': True, 'source': 'portalxs', 'cache_age_sec': 0}, vehicles) == 'LIVE'
    assert classify_feed_status({'soap_ok': True, 'source': 'cache', 'cache_age_sec': 12}, [{'gps_age_sec': 120}]) == 'DELAYED'
    assert classify_feed_status({'soap_ok': True, 'source': 'portalxs', 'cache_age_sec': 0}, [{'gps_age_sec': 400}]) == 'OFFLINE'
    assert classify_feed_status({'soap_ok': True, 'source': 'portalxs', 'cache_age_sec': 0}, []) == 'UNKNOWN'


def test_warning_is_not_consumed():
    _POSITION_FETCH_WARNINGS[999001] = 'GPS server se connection timeout'
    assert consume_position_warning(999001) == 'GPS server se connection timeout'
    assert get_position_warning(999001) == 'GPS server se connection timeout'
    _POSITION_FETCH_WARNINGS.pop(999001, None)


def test_future_rdt_clock_skew():
    now = datetime(2026, 9, 13, 22, 50, 0)
    assert gps_age_sec((now + timedelta(seconds=20)).strftime('%Y-%m-%d %H:%M:%S'), now=now) == 0
    assert gps_age_sec((now + timedelta(hours=6)).strftime('%Y-%m-%d %H:%M:%S'), now=now) is None


def test_request_id_ignores_stale():
    latest = 0
    applied = []

    def start():
        nonlocal latest
        latest += 1
        return latest

    def apply(request_id, payload):
        if request_id != latest:
            return
        applied.append(payload)

    first = start()
    second = start()
    apply(first, 'old')
    apply(second, 'new')
    assert applied == ['new']


def _clear_live_state(account_id: int):
    with portalxs_svc._live_cache_lock:
        portalxs_svc._live_cache.pop(str(account_id), None)
        portalxs_svc._live_cache_ts.pop(str(account_id), None)
        portalxs_svc._live_cache_meta.pop(str(account_id), None)
    _POSITION_FETCH_WARNINGS.pop(account_id, None)


def _sample_vehicle(regno='LEG-18-2874'):
    return {
        'RegNo': regno,
        'LAT': 30.1,
        'LON': 71.2,
        'VehicleStatus': 'Moving',
        'RDT': '2026-09-13 22:49:50',
    }


def test_bulk_operation_names():
    assert is_portalxs_bulk_operation('mileage-auto-sync')
    assert is_portalxs_bulk_operation('activity-auto-sync')
    assert is_portalxs_bulk_operation('fleet-score-snapshot')
    assert not is_portalxs_bulk_operation('live-position')
    assert not is_portalxs_bulk_operation(None)


def test_map_get_uses_cache_without_soap():
    acct = 91011
    _clear_live_state(acct)
    _set_cached_positions(acct, [_sample_vehicle()], source='portalxs', soap_ok=True)
    with patch('services.portalxs_service.fetch_live_positions') as mocked:
        served = serve_live_positions(acct, force=False)
        payload = build_live_positions_payload(acct, force=False)
        mocked.assert_not_called()
    assert served[0]['RegNo'] == 'LEG-18-2874'
    assert payload['vehicles'][0]['RegNo'] == 'LEG-18-2874'
    _clear_live_state(acct)


def test_refresh_still_requests_soap():
    acct = 91012
    _clear_live_state(acct)
    _set_cached_positions(acct, [_sample_vehicle()], source='portalxs', soap_ok=True)
    with patch('services.portalxs_service.fetch_live_positions',
               return_value=[_sample_vehicle('GBF-25-371')]) as mocked:
        out = serve_live_positions(acct, force=True)
        mocked.assert_called_once_with(acct, force=True)
    assert out[0]['RegNo'] == 'GBF-25-371'
    _clear_live_state(acct)


def test_live_lock_collision_is_silent():
    acct = 91013
    _clear_live_state(acct)
    _set_cached_positions(acct, [_sample_vehicle()], source='portalxs', soap_ok=True)
    started = threading.Event()
    release = threading.Event()

    def _hold():
        with portalxs_work(acct, 'live-position', wait=True):
            started.set()
            release.wait(2)

    holder = threading.Thread(target=_hold)
    holder.start()
    assert started.wait(1)
    assert current_portalxs_operation(acct) == 'live-position'
    out = fetch_live_positions(acct, force=True)
    warning = get_position_warning(acct)
    meta = get_live_feed_meta(acct)
    release.set()
    holder.join(2)
    assert out[0]['RegNo'] == 'LEG-18-2874'
    assert warning is None or _BULK_SYNC_WARNING not in warning
    assert meta['soap_ok'] is True
    _clear_live_state(acct)


def test_real_bulk_lock_sets_warning():
    acct = 91014
    _clear_live_state(acct)
    _set_cached_positions(acct, [_sample_vehicle()], source='portalxs', soap_ok=True)
    started = threading.Event()
    release = threading.Event()

    def _hold():
        with portalxs_work(acct, 'mileage-auto-sync', wait=True):
            started.set()
            release.wait(2)

    holder = threading.Thread(target=_hold)
    holder.start()
    assert started.wait(1)
    out = fetch_live_positions(acct, force=True)
    warning = get_position_warning(acct)
    release.set()
    holder.join(2)
    assert out[0]['RegNo'] == 'LEG-18-2874'
    assert warning == _BULK_SYNC_WARNING
    _clear_live_state(acct)


def test_inflight_live_soap_is_shared():
    acct = 91015
    _clear_live_state(acct)
    calls = []
    snapshot = [_sample_vehicle('GBF-25-992')]

    def _fake(_account_id, force=False):
        calls.append(force)
        time.sleep(0.25)
        return snapshot

    with patch('services.portalxs_service._fetch_live_positions', _fake):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(fetch_live_positions, acct, True)
            time.sleep(0.05)
            second = pool.submit(fetch_live_positions, acct, True)
            assert first.result(timeout=3) == snapshot
            assert second.result(timeout=3) == snapshot
    assert calls == [True]
    _clear_live_state(acct)


def test_empty_memory_hydrates_from_db_mappings():
    acct = 91016
    _clear_live_state(acct)
    rows = [_sample_vehicle()]
    with patch('services.portalxs_service._positions_from_db_mappings', return_value=rows):
        out = get_cached_positions(acct)
    assert out[0]['RegNo'] == 'LEG-18-2874'
    with patch('services.portalxs_service._positions_from_db_mappings',
               side_effect=AssertionError('memory cache should already be warm')):
        out2 = get_cached_positions(acct)
    assert out2[0]['RegNo'] == 'LEG-18-2874'
    _clear_live_state(acct)


if __name__ == '__main__':
    test_parse_rdt_real_formats()
    test_gps_status_thresholds()
    test_idle_logic_unchanged()
    test_annotate_does_not_mutate_or_change_status()
    test_feed_status_never_live_on_failed_soap()
    test_warning_is_not_consumed()
    test_future_rdt_clock_skew()
    test_request_id_ignores_stale()
    test_bulk_operation_names()
    test_map_get_uses_cache_without_soap()
    test_refresh_still_requests_soap()
    test_live_lock_collision_is_silent()
    test_real_bulk_lock_sets_warning()
    test_inflight_live_soap_is_shared()
    test_empty_memory_hydrates_from_db_mappings()
    print('tracker freshness tests OK')
