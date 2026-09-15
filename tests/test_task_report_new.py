"""Unit checks for New Task Entry helpers (no database)."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
os.chdir(ROOT)
for path in (ROOT, os.path.join(ROOT, 'services')):
    if path not in sys.path:
        sys.path.insert(0, path)

from services.utils import emg_amb_reg_matches_vehicle_no  # noqa: E402
from services.task_entry_filter import (  # noqa: E402
    coerce_task_entry_location_locks as _coerce_task_entry_location_locks,
    coerce_task_entry_vehicle_lock as _coerce_task_entry_vehicle_lock,
    live_task_entry_metrics,
)


def test_emg_reg_match_exact_base_and_tag():
    assert emg_amb_reg_matches_vehicle_no('GBF-25-579', 'GBF-25-579') is True
    assert emg_amb_reg_matches_vehicle_no('GBF-25-579 COW', 'GBF-25-579') is True
    assert emg_amb_reg_matches_vehicle_no('GBF-25-579-COW', 'GBF-25-579') is True
    assert emg_amb_reg_matches_vehicle_no('gbf-25-579 cow', 'GBF-25-579') is True
    assert emg_amb_reg_matches_vehicle_no('GBF-25-580', 'GBF-25-579') is False
    assert emg_amb_reg_matches_vehicle_no('', 'GBF-25-579') is False
    assert emg_amb_reg_matches_vehicle_no('GBF-25-579', '') is False


def test_location_lock_only_when_id_in_scope():
    did, pid, tef = _coerce_task_entry_location_locks(
        0, 0,
        is_master_or_admin=False,
        allowed_districts={7},
        allowed_projects={3},
        valid_district_ids={7},
        scoped_project_ids={3, 9},
        allowed_vehicles={10},
    )
    assert did == 7
    assert pid == 3
    assert tef['lock_district'] is True
    assert tef['lock_project'] is True
    assert tef['lock_vehicle'] is False

    did, pid, tef = _coerce_task_entry_location_locks(
        0, 0,
        is_master_or_admin=False,
        allowed_districts={7},
        allowed_projects={3},
        valid_district_ids={7},
        scoped_project_ids={3, 9},
        allowed_vehicles={10, 11},
    )
    assert did == 7
    assert pid == 0
    assert tef['lock_district'] is True
    assert tef['lock_project'] is False

    did, pid, tef = _coerce_task_entry_location_locks(
        0, 0,
        is_master_or_admin=False,
        allowed_districts={7},
        allowed_projects={3},
        valid_district_ids={8},
        scoped_project_ids={9},
        allowed_vehicles={10},
    )
    assert did == 0
    assert pid == 0
    assert tef['lock_district'] is False
    assert tef['lock_project'] is False


def test_vehicle_lock_clears_when_out_of_scoped_list():
    tef = {'lock_district': True, 'lock_project': True, 'lock_vehicle': False}
    vid, tef = _coerce_task_entry_vehicle_lock(
        55, tef,
        is_master_or_admin=False,
        allowed_vehicles={55},
        scoped_vehicle_ids={10, 11},
    )
    assert vid == 0
    assert tef['lock_vehicle'] is False

    vid, tef = _coerce_task_entry_vehicle_lock(
        0, tef,
        is_master_or_admin=False,
        allowed_vehicles={55},
        scoped_vehicle_ids={55, 11},
    )
    assert vid == 55
    assert tef['lock_vehicle'] is True


def test_admin_is_not_locked():
    did, pid, tef = _coerce_task_entry_location_locks(
        4, 2,
        is_master_or_admin=True,
        allowed_districts={4},
        allowed_projects={2},
        valid_district_ids={4},
        scoped_project_ids={2},
    )
    assert did == 4 and pid == 2
    assert tef['lock_district'] is False
    assert tef['lock_project'] is False


def test_live_metrics_empty_close_shows_negative_driven():
    m = live_task_entry_metrics(start=1200, close=None, tasks=None, emg=4, tracker=50)
    assert m['kms_driven'] == -1200
    assert m['kms_diff'] == -1250
    assert m['task_diff'] == -4
    assert m['pct_diff'] == round((-1250 / -1200) * 100, 1)


def test_live_metrics_typed_values_and_zero_driven():
    m = live_task_entry_metrics(start=100, close=180, tasks=6, emg=6, tracker=70)
    assert m['kms_driven'] == 80
    assert m['kms_diff'] == 10
    assert m['task_diff'] == 0
    assert m['pct_diff'] == 12.5
    z = live_task_entry_metrics(start=0, close='', tasks='', emg=0, tracker=0)
    assert z['kms_driven'] == 0
    assert z['pct_diff'] is None


if __name__ == '__main__':
    test_emg_reg_match_exact_base_and_tag()
    test_location_lock_only_when_id_in_scope()
    test_vehicle_lock_clears_when_out_of_scoped_list()
    test_admin_is_not_locked()
    test_live_metrics_empty_close_shows_negative_driven()
    test_live_metrics_typed_values_and_zero_driven()
    print('test_task_report_new.py: ok')
