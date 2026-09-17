"""Recheck Phase 2 Batch B report_* MEL cascade migrations."""
from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[1]

PAGES = [
    ("report_expiry.html", "#exDistrictSelect", False),
    ("report_engine_chassis.html", "#ecDistrictSelect", False),
    ("report_vehicle_summary.html", "#vsDistrictSelect", False),
    ("report_parking_utilization.html", "#puDistrictSelect", True),
]

for rel, dist_id, keep_parking in PAGES:
    t = (ROOT / "templates" / rel).read_text(encoding="utf-8")
    assert 'id="locationCascadeData"' in t, f"{rel}: LC"
    assert 'data-cascade-cache-prefix="proj_d"' in t, f"{rel}: proj_d"
    assert 'data-cascade-cache-prefix="veh_p"' in t, f"{rel}: veh_p"
    assert f'data-cascade-cache-district="{dist_id}"' in t, f"{rel}: cache-district"
    assert "/api/filter/districts-by-project" not in t, f"{rel}: old P→D"
    assert "/api/filter/all-vehicles-by-project-district" not in t, f"{rel}: old vehicles fetch"
    assert not re.search(r"district_id=\{#", t), f"{rel}: jinja break"
    # UI order: District label before Project label in filter region
    d_pos = t.find(">District<")
    if d_pos < 0:
        d_pos = t.find(">District</")
    p_pos = t.find(">Project<")
    if p_pos < 0:
        p_pos = t.find(">Project</")
    assert d_pos > 0 and p_pos > d_pos, f"{rel}: District should appear before Project in UI"
    if keep_parking:
        assert "/api/filter/parking-stations" in t, f"{rel}: KEEP parking fetch"
    print(f"OK {rel}")

ast.parse((ROOT / "routes/routes_reports.py").read_text(encoding="utf-8"))
print("Batch B AST OK")
