"""Verify Phase 2 Jinja district_id escape and MPG locked-district cascade id."""
from pathlib import Path
from jinja2 import Environment, BaseLoader
import re

ROOT = Path(__file__).resolve().parents[1]
env = Environment(loader=BaseLoader())

ids = [
    "mpgDistrictFilter",
    "ssDistrict",
    "exDistrictSelect",
    "ecDistrictSelect",
    "vsDistrictSelect",
    "puDistrictSelect",
    "reportDistrictSelect",
    "dailyDistrictSelect",
    "traDistrictSelect",
]
for sid in ids:
    tpl = "/api/cascade/vehicles?parent={value}&district_id={{ '{#' }}" + sid + "}"
    out = env.from_string(tpl).render()
    # fleet_core token is {#selectId} — must survive Jinja (not become a comment)
    assert out == f"/api/cascade/vehicles?parent={{value}}&district_id={{#{sid}}}", out
    assert "{#" + sid + "}" in out
print("JINJA ESCAPE OK")

# MPG: when district locked, cascade must still read district id
mpg = (ROOT / "templates/workspace/mpg_report.html").read_text(encoding="utf-8")
# Either live select or hidden with same id
assert 'id="mpgDistrictFilter"' in mpg
# If locked branch uses hidden, it must carry the id
locked = re.search(
    r"{% if disable_district %}(.*?){% else %}",
    mpg,
    re.S,
)
assert locked, "disable_district block missing"
block = locked.group(1)
if "mpg-locked-chip" in block:
    assert 'id="mpgDistrictFilter"' in block, (
        "BUG: locked district chip has no #mpgDistrictFilter for cascade cache-district"
    )
    print("MPG locked district id OK")
else:
    print("MPG locked uses select (ok)")

# daily unused var is harmless; ensure no loadVehicles leftover
daily = (ROOT / "templates/driver_attendance_daily_report.html").read_text(encoding="utf-8")
assert "loadVehicles(" not in daily
assert "loadDistricts(" not in daily
print("DAILY leftover OK")
print("DEEP RECHECK OK")
