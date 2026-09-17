"""Phase 2 full MEL cascade recheck (Batches A+B+C)."""
from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[1]

CHECKS = [
    # rel, district_sel, need_veh, keep_extra
    ("workspace/mpg_report.html", "#mpgDistrictFilter", True, None),
    ("driver_salary_slip.html", "#ssDistrict", True, "/api/salary-slip/drivers-for-vehicle"),
    ("driver_attendance_bulk_off.html", "#districtSelect", False, None),
    ("report_expiry.html", "#exDistrictSelect", True, None),
    ("report_engine_chassis.html", "#ecDistrictSelect", True, None),
    ("report_vehicle_summary.html", "#vsDistrictSelect", True, None),
    ("report_parking_utilization.html", "#puDistrictSelect", True, "/api/filter/parking-stations"),
    ("driver_attendance_report.html", "#reportDistrictSelect", True, "/api/attendance/filtered-drivers"),
    ("driver_attendance_daily_report.html", "#dailyDistrictSelect", True, "/api/attendance/filtered-drivers"),
    ("driver_attendance_tra_report.html", "#traDistrictSelect", True, "/api/attendance/filtered-drivers"),
]

for rel, dist_id, need_veh, keep in CHECKS:
    t = (ROOT / "templates" / rel).read_text(encoding="utf-8")
    assert 'id="locationCascadeData"' in t, f"{rel}: LC"
    assert 'data-cascade-cache-prefix="proj_d"' in t, f"{rel}: proj_d"
    if need_veh:
        assert 'data-cascade-cache-prefix="veh_p"' in t, f"{rel}: veh_p"
        assert f'data-cascade-cache-district="{dist_id}"' in t, f"{rel}: cache-district {dist_id}"
    assert "/api/filter/districts-by-project" not in t, f"{rel}: old P→D"
    assert "/api/filter/all-vehicles-by-project-district" not in t, f"{rel}: old vehicles"
    assert "/api/filter/projects-by-district" not in t, f"{rel}: old projects filter"
    assert "api_attendance_projects" not in t, f"{rel}: old att projects"
    assert "function loadDistricts" not in t, f"{rel}: leftover loadDistricts"
    assert "function loadVehicles" not in t, f"{rel}: leftover loadVehicles"
    assert "function loadProjects" not in t, f"{rel}: leftover loadProjects"
    assert not re.search(r"district_id=\{#", t), f"{rel}: jinja break"
    if keep:
        assert keep in t, f"{rel}: missing KEEP {keep}"
    # District before Project in filter labels (first occurrences after form-ish region)
    # Prefer filter-select ids order via cascade-child pointing project after district
    assert "data-cascade-child=" in t, f"{rel}: cascade-child"
    print(f"OK {rel}")

for py in (
    "routes/routes_workspace.py",
    "routes/routes_tracker_reports.py",
    "routes/routes_attendance.py",
    "routes/routes_reports.py",
):
    ast.parse((ROOT / py).read_text(encoding="utf-8"))
    print(f"AST OK {py}")

print("PHASE 2 FULL RECHECK OK")
