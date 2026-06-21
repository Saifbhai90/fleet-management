"""Static + HTTP smoke checks for task report mobile/desktop changes."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def check(name: str, ok: bool, detail: str) -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}: {detail}")
    if not ok:
        failures.append(name)


failures: list[str] = []

# New Task Entry mobile support
new_html = read("templates/task_report_new.html")
check(
    "new_mobile_partial",
    "partials/task_report_mobile_task_modal.html" in new_html,
    "includes mobile task modal partial",
)
check(
    "new_mobile_guard",
    "if (_useMobileTaskPanel()) return;" in new_html,
    "desktop EMG/tracker handlers skip on mobile",
)
check(
    "new_float_panel_css",
    ".fleet-task-float-panel" in new_html and "left: 320px" in new_html,
    "desktop popup respects sidebar offset",
)
check(
    "new_emg_print_preview",
    "_openEmgPrintPreview" in new_html and "w.print()" not in new_html.split("_openEmgPrintPreview")[1][:800],
    "EMG print uses custom preview (no auto print)",
)

# Daily task report EMG print
list_html = read("templates/task_report_list.html")
check(
    "list_emg_print_preview",
    "_openEmgPrintPreview" in list_html,
    "daily report EMG custom print preview",
)
check(
    "list_mobile_modal",
    "mobileTaskModal" in list_html,
    "daily report has mobile modal",
)

# Period detail report
period_html = read("templates/task_report_vehicle_period_detail.html")
check(
    "period_emg_print_preview",
    "_openEmgPrintPreview" in period_html,
    "period report EMG custom print preview",
)
check(
    "period_fetch_all",
    "_allPagesUrl" in period_html and "per_page', '99999'" in period_html,
    "print/export fetch all pages",
)
check(
    "period_no_odoo_col",
    ">Odoo<" not in period_html and "odometer_photo_path" not in period_html.split("<tbody>")[1].split("</tbody>")[0],
    "Odoo column removed from table body",
)
check(
    "period_print_all_fetch",
    "Fetching all rows" in period_html,
    "fetch all rows progress message present",
)

partial = read("templates/partials/task_report_mobile_task_modal.html")
check(
    "partial_guard",
    'if (document.getElementById("mobileTaskModal")) return;' in partial,
    "mobile partial avoids duplicate injection",
)
check(
    "partial_handlers",
    "openMobileTaskModal" in partial and "_renderMobileEmgCards" in partial,
    "mobile partial has EMG card renderer",
)

print("\n--- HTTP checks (optional) ---")
try:
    import urllib.request

    for path in (
        "/login",
        "/task-report/new",
        "/task-report/list",
        "/task-report/vehicle-period-detail",
    ):
        url = f"http://127.0.0.1:5050{path}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                code = resp.getcode()
                body = resp.read(500).decode("utf-8", "ignore")
                redirected = "login" in resp.geturl() or "Login" in body or code in (200, 302)
                check(f"http_{path}", redirected, f"status={code} url={resp.geturl()}")
        except Exception as exc:
            check(f"http_{path}", False, str(exc))
except Exception as exc:
    print(f"HTTP checks skipped: {exc}")

print("\nSUMMARY:", "ALL PASS" if not failures else f"{len(failures)} FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
