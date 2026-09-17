"""Recheck workspace/mpg_report MEL cascade markers (custom district id)."""
from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[1]
t = (ROOT / "templates/workspace/mpg_report.html").read_text(encoding="utf-8")
assert 'id="locationCascadeData"' in t
assert 'data-cascade-cache-prefix="proj_d"' in t
assert 'data-cascade-cache-prefix="veh_p"' in t
assert 'data-cascade-cache-district="#mpgDistrictFilter"' in t
assert "fetch('/api/cascade" not in t
assert not re.search(r"district_id=\{#", t)
ast.parse((ROOT / "routes/routes_workspace.py").read_text(encoding="utf-8"))
print("MPG RECHECK OK")
