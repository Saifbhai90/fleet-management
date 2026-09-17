"""Recheck Phase 2 Batch A pages for MEL cascade markers."""
from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[1]


def check_html(rel, *, district_id, need_veh=True, salary_keep_driver=False, no_filter_fetch=True):
    t = (ROOT / "templates" / rel).read_text(encoding="utf-8")
    assert 'id="locationCascadeData"' in t, f"{rel}: missing locationCascadeData"
    assert 'data-cascade-cache-prefix="proj_d"' in t, f"{rel}: missing proj_d"
    assert f'data-cascade-cache-district="{district_id}"' in t or not need_veh, f"{rel}: missing cache-district"
    if need_veh:
        assert 'data-cascade-cache-prefix="veh_p"' in t, f"{rel}: missing veh_p"
    assert "fetch('/api/cascade" not in t, f"{rel}: leftover cascade fetch"
    if no_filter_fetch:
        assert "/api/filter/projects-by-district" not in t, f"{rel}: leftover filter projects fetch"
        assert "/api/filter/all-vehicles" not in t, f"{rel}: leftover filter vehicles fetch"
        assert "api_attendance_projects" not in t, f"{rel}: leftover attendance projects api"
    assert not re.search(r"district_id=\{#", t), f"{rel}: broken Jinja district_id"
    if salary_keep_driver:
        assert "/api/salary-slip/drivers-for-vehicle" in t, f"{rel}: missing vehicle→driver KEEP"
    print(f"OK {rel}")


check_html(
    "driver_salary_slip.html",
    district_id="#ssDistrict",
    need_veh=True,
    salary_keep_driver=True,
)
check_html(
    "driver_attendance_bulk_off.html",
    district_id="#districtSelect",
    need_veh=False,
    no_filter_fetch=True,
)
# bulk_off has no cache-district — override assert path
t = (ROOT / "templates/driver_attendance_bulk_off.html").read_text(encoding="utf-8")
assert 'data-cascade-cache-prefix="proj_d"' in t
assert 'data-cascade-cache-prefix="veh_p"' not in t
assert "loadProjectsForDistrict" not in t

ast.parse((ROOT / "routes/routes_tracker_reports.py").read_text(encoding="utf-8"))
ast.parse((ROOT / "routes/routes_attendance.py").read_text(encoding="utf-8"))
print("Batch A salary+bulk AST OK")
