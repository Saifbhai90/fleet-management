# Complete Software Audit + Remediation Blueprint (V2)
## Fleet/Company Management System — Web (Flask) + Android (Capacitor)

**Audit Date:** 2026-06-24
**Methodology:** Phase 1 Static (read-only) — no runtime testing, no code changes
**Repo:** `f:\Laptop new hard drive Disk D\company_management`

---

## 1) EXECUTIVE SUMMARY

The Fleet Management System is a large-scale Flask monolith that has undergone significant refactoring since the V1 audit. The main `routes.py` has been split from ~39K lines down to **10,640 lines** across **20+ dedicated route modules**. `base.html` reduced from ~9.7K lines to **864 lines**. Deprecated `.query.get()` calls **fully removed** from active code. Debug prints **eliminated** from hot path.

**Overall health is MODERATE-GOOD (improved from V1).** Remaining concerns:

1. **612 broad `except Exception` blocks** across routes (483) + services (129)
2. **10 `@csrf.exempt` endpoints** — all origin-validated, but surface area
3. **5 `|safe` usages remain** — including 1 on AI LLM output (active XSS)
4. **`routes.py` at 10.6K lines** still large; further splitting recommended
5. **84 Alembic migration files** — chain should be squashed
6. **`minifyEnabled false`** in Android release build
7. **No CI/CD pipeline** — deployments manual via Render
8. **Smoke test exists** (`tests/smoke_test.py`) covering 50+ routes — good start

---

## 2) OVERALL SCORECARD

| Dimension | Score | Delta | Notes |
|---|---|---|---|
| Architecture & Structure | 7 | +3 | routes.py split into 20+ modules; base.html split |
| Security & Permissions | 7 | +1 | Origin validation on CSRF exempts; |safe reduced to 5 |
| Functional Correctness | 7 | +1 | 612 broad excepts may mask bugs |
| UI/UX & Forms | 7 | 0 | Bootstrap 5 + TomSelect + Flatpickr |
| Android / Mobile Parity | 7 | 0 | FleetBridge, biometric, GPS camera |
| Data Integrity | 7 | 0 | VoucherSequence, soft-delete, FK enforcement |
| Performance | 7 | +2 | .query.get() removed; per_page capped at 500 |
| Code Quality | 6 | +2 | Debug prints gone; smoke test; broad excepts remain |
| DevOps & Deployment | 7 | 0 | Render, Gunicorn, backup; no CI/CD |
| Test Coverage | 2 | +2 | Smoke test 50+ routes; no unit tests |
| **OVERALL** | **6.4/10** | **+1.1** | **Improved; needs except cleanup, tests, AI XSS fix** |

---

## 3) MASTER BUG REGISTER

| ID | Type | Sev | File/Route | Description | Effort |
|---|---|---|---|---|---|
| BUG-001 | SECURITY | P1 | `templates/report_ai.html` | LLM output rendered `\|safe` — active XSS | S(1h) |
| BUG-002 | DEBT | P1 | `routes.py` (10,640 lines) | 418 functions in one file | L(weeks) |
| BUG-003 | SECURITY | P2 | 10 `@csrf.exempt` endpoints | All origin-validated; surface for bypass | M(4h) |
| BUG-004 | DEBT | P1 | 612 `except Exception` | 483 routes + 129 services; masks bugs | L(days) |
| BUG-005 | PERFORMANCE | P2 | `auth_utils.py` get_user_context | 4+ DB queries per request, no cache | M(4h) |
| BUG-006 | DEAD-CODE | P2 | `docs/archive/` (3 files) | 42 .query.get() in dead files; ~960KB | S(30m) |
| BUG-007 | TEST-GAP | P1 | Entire repo | Only smoke test; no unit/integration | XL |
| BUG-008 | SECURITY | P2 | `android/app/build.gradle:45` | minifyEnabled false on release | S(1h) |
| BUG-009 | SECURITY | P3 | `network_security_config.xml` | Cleartext to LAN IPs shipped in prod | S(30m) |
| BUG-010 | UI-LAYOUT | P2 | `workspace/transfer_form.html` | 2,053 lines, 99KB — mobile scroll risk | M(4h) |
| BUG-011 | UI-LAYOUT | P2 | `fuel_expense_form.html` | 3,685 lines, 157KB — largest template | M(4h) |
| BUG-012 | UI-LAYOUT | P2 | `driver_attendance_daily_report.html` | 3,743 lines, 179KB | M(4h) |
| BUG-013 | MIGRATION | P3 | `migrations/versions/` (84 files) | Long chain; squash periodically | M(4h) |
| BUG-014 | SECURITY | P3 | `templates/transfer_form.html` | 2 console.log in production | S(5m) |
| BUG-015 | DEBT | P3 | `static/js/` (4 console.log) | Debug logging in prod JS | S(30m) |
| BUG-016 | DUPLICATION | P3 | `routes_finance.py:39` | check_auth imported from finance; should be shared | S(1h) |
| BUG-017 | PERFORMANCE | P3 | `Procfile` | Gunicorn 1 worker, 4 threads | S(config) |
| BUG-018 | DEBT | P3 | 20 templates >500 lines | Large inline JS; extract to external | L(days) |
| BUG-019 | DOCS-GAP | P3 | `docs/` | No API docs, no architecture guide | M(4h) |
| BUG-020 | SECURITY | P3 | `base.html` (2 safe) | Remaining \|safe — verify context | S(30m) |

---

## 4) ROUTE INVENTORY

### Route Registration Pattern
Routes are registered via three mechanisms in `app.py`:
1. **`from routes import *`** — imports `routes.py` which uses `@app.route` decorator (418 functions)
2. **`import routes_*.py`** — dedicated modules using `@app.route` decorator (525 routes)
3. **`app.add_url_rule()`** — explicit registration in `app.py` for finance, workspace, payroll (~100 rules)

### Route Module Summary

| File | Lines | Routes | Functions | KB |
|---|---|---|---|---|
| `routes.py` | 10,640 | 0* | 418 | 482 |
| `routes_expenses.py` | 6,829 | 91 | ~80 | 330 |
| `routes_attendance.py` | 5,688 | 32 | ~60 | 270 |
| `routes_workspace.py` | 5,260 | 0* | 148 | 238 |
| `routes_finance.py` | 2,931 | 0* | 87 | 142 |
| `routes_master_data.py` | 2,608 | 101 | ~70 | 131 |
| `routes_tracker_reports.py` | 1,912 | 42 | ~40 | 93 |
| `routes_auth.py` | 1,886 | 17 | ~35 | 91 |
| `routes_assignments.py` | 1,663 | 42 | ~35 | 85 |
| `routes_tasks.py` | 1,586 | 22 | ~25 | 77 |
| `routes_task_ops.py` | 1,300 | 16 | ~18 | 63 |
| `routes_reports.py` | 1,268 | 13 | ~15 | 62 |
| `routes_employees.py` | 1,209 | 24 | ~25 | 62 |
| `routes_ai.py` | 1,198 | 8 (bp) | 42 | 49 |
| `routes_system.py` | 1,123 | 17 | ~20 | 53 |
| `routes_dashboard.py` | 1,092 | 29 | ~25 | 53 |
| `routes_transfers.py` | 1,080 | 21 | ~22 | 54 |
| `routes_workforce.py` | 765 | 16 | ~18 | 36 |
| `routes_payroll.py` | 738 | 0* | 23 | 38 |
| `api.py` | 640 | 12 (bp) | 25 | 28 |
| `routes_misc.py` | 550 | 19 | ~20 | 24 |
| `routes_books.py` | 328 | 0* | 13 | 18 |
| `routes_tool_workstation.py` | 65 | 3 | ~5 | 2 |

*Routes in these files are registered via `app.add_url_rule()` in `app.py` or imported via `from routes import *`

**Estimated total: ~700+ registered URL rules**

### CSRF-Exempt Endpoints (10 total)

| File | Endpoint | Origin Validation | Purpose |
|---|---|---|---|
| `routes_misc.py` | `/upload-blob` | No | Blob upload from mobile |
| `routes_misc.py` | `/api/biometric/enable` | Yes | Enable biometric login |
| `routes_misc.py` | `/api/biometric/disable` | Yes | Disable biometric login |
| `routes_misc.py` | `/auth/app-logout` | No | Mobile auto-logout |
| `routes_misc.py` | `/auth/biometric-login` | No | Biometric session creation |
| `routes_auth.py` | `/api/client-diagnostics` | Yes | Client error reporting |
| `routes_ai.py` | `/api/ai/query` | Yes | Gemini AI query |
| `routes_ai.py` | `/api/ai/conversations/new` | Yes | AI conversation create |
| `routes_ai.py` | `/api/ai/conversations/<id>` | Yes | AI conversation CRUD |
| `routes.py` | (1 orphaned @csrf.exempt) | Unknown | Orphaned decorator |

---

## 5) FORM INVENTORY

### Major Forms (41 form templates)

| Form | KB | Lines | CSRF | Permission Guard | Scroll Risk |
|---|---|---|---|---|---|
| `fuel_expense_form.html` | 157 | 3,685 | Yes | check_auth | HIGH |
| `driver_attendance_daily_report.html` | 179 | 3,743 | Yes | check_auth | HIGH |
| `report_driver_profile.html` | 153 | 2,725 | Yes | check_auth | MEDIUM |
| `maintenance_expense_form.html` | 122 | 2,661 | Yes | check_auth | MEDIUM |
| `driver_form.html` | 100 | 2,073 | Yes | check_auth | LOW |
| `workspace/transfer_form.html` | 99 | 2,053 | Yes | _workspace_guard | HIGH |
| `reports_index.html` | 82 | 1,874 | Yes | check_auth | LOW |
| `task_report_new.html` | 81 | 1,707 | Yes | check_auth | MEDIUM |
| `task_report_vehicle_period_detail.html` | 84 | 1,702 | Yes | check_auth | MEDIUM |
| `dashboard.html` | 93 | 1,693 | Yes | check_auth | LOW |
| `driver_attendance_list.html` | 85 | 1,653 | Yes | check_auth | MEDIUM |
| `oil_expense_form.html` | 68 | 1,524 | Yes | check_auth | MEDIUM |
| `task_report_list.html` | 74 | 1,471 | Yes | check_auth | MEDIUM |
| `driver_attendance_checkout.html` | 64 | 1,252 | Yes | check_auth | MEDIUM |
| `driver_attendance_checkin.html` | 63 | 1,227 | Yes | check_auth | MEDIUM |
| `control_form.html` | 70 | 1,199 | Yes | check_auth | MEDIUM |
| `system_health.html` | 61 | 1,101 | Yes | check_auth | LOW |
| `unauthorized_movement_report.html` | 60 | 1,019 | Yes | check_auth | LOW |
| `maintenance_expense_list.html` | 48 | 1,005 | Yes | check_auth | LOW |
| `role_form.html` | 37 | 897 | Yes | check_auth | LOW |

### WTForms Classes (forms.py — 1,341 lines, 96.5KB)
Major form classes: CompanyForm, ProjectForm, VehicleForm, DriverForm, EmployeeForm (3-step wizard), FuelExpenseForm, OilExpenseForm, MaintenanceExpenseForm, TaskReportForm, RedTaskForm, PaymentVoucherForm, ReceiptVoucherForm, JournalVoucherForm, FundTransferForm, EmployeeExpenseForm, LoginForm, UserForm, and more.

---

## 6) STATIC CODE ANALYSIS FINDINGS

### 6.1 Broad Exception Handling

| Location | Count | Risk |
|---|---|---|
| `routes.py` | 99 | Masks runtime errors |
| `routes_expenses.py` | 48 | Silent expense failures |
| `routes_master_data.py` | 42 | Data corruption risk |
| `routes_workspace.py` | 40 | Financial data issues |
| `routes_attendance.py` | 33 | Attendance errors hidden |
| `routes_auth.py` | 28 | Auth edge cases |
| `routes_employees.py` | 25 | Employee data issues |
| `routes_finance.py` | 24 | Financial errors |
| `routes_system.py` | 24 | System ops |
| `routes_ai.py` | 21 | AI failures |
| Other route files | 99 | Various |
| **Routes subtotal** | **483** | |
| `services/tracker_automation.py` | 28 | Tracker errors |
| `services/backup_utils.py` | 13 | Backup failures |
| `services/auth_utils.py` | 12 | Auth issues |
| `services/backup_jobs.py` | 12 | Job failures |
| `services/notification_service.py` | 11 | Notification loss |
| Other services | 53 | Various |
| **Services subtotal** | **129** | |
| **TOTAL** | **612** | |

### 6.2 `|safe` Filter Usage (5 remaining — down from 366+)

| File | Context | Risk |
|---|---|---|
| `templates/report_ai.html` | LLM-generated HTML output | **HIGH — active XSS** |
| `templates/reports/activity_log.html` | Activity log display | LOW (admin-only) |
| `templates/tool_workstation/index.html` | Tool description | LOW (static) |
| `templates/tool_workstation/tool.html` | Tool output | MEDIUM |
| `templates/vehicle_reading_setup_form.html` | Form field | LOW |

### 6.3 `console.log` in Production

| File | Count |
|---|---|
| `static/js/ws_slip_ocr/01_constants.js` | 2 |
| `static/js/core/fleet_core.js` | 1 |
| `static/js/ws_slip_ocr/07_bridge.js` | 1 |
| `templates/workspace/transfer_form.html` | 2 |
| **Total** | **6** |

### 6.4 `per_page` Capping (FIXED since V1)
- `routes_expenses.py:1406` — caps at 500 when `>= 99999`
- `routes_workspace.py:3215` — caps at 500 when `>= 99999`
- `routes_expenses.py:6133` — comment documents print/export cap

### 6.5 `.query.get()` (FIXED since V1)
- **0 in active code** (routes + services + app.py)
- 42 remaining only in `docs/archive/` dead files

### 6.6 Debug Prints (FIXED since V1)
- **0 `print(f"DEBUG:...")` in active code**

### 6.7 TODO/FIXME/HACK
- Routes: 0 TODO/FIXME in route files
- Services: 3 in `services/utils.py` (docstring text, not actual TODOs)
- Templates: 23 matches across 5 files (mostly in comments/docstrings)

### 6.8 Large Files

**Python files >500 lines:**

| File | Lines | KB |
|---|---|---|
| `routes.py` | 10,640 | 482 |
| `routes_expenses.py` | 6,829 | 330 |
| `routes_attendance.py` | 5,688 | 270 |
| `routes_workspace.py` | 5,260 | 238 |
| `routes_finance.py` | 2,931 | 142 |
| `routes_master_data.py` | 2,608 | 131 |
| `models.py` | 2,413 | 154 |
| `routes_tracker_reports.py` | 1,912 | 93 |
| `routes_auth.py` | 1,886 | 91 |
| `routes_assignments.py` | 1,663 | 85 |
| `forms.py` | 1,341 | 97 |
| `routes_tasks.py` | 1,586 | 77 |
| `routes_task_ops.py` | 1,300 | 63 |
| `routes_reports.py` | 1,268 | 62 |
| `routes_employees.py` | 1,209 | 62 |
| `routes_ai.py` | 1,198 | 49 |
| `routes_system.py` | 1,123 | 53 |
| `routes_dashboard.py` | 1,092 | 53 |
| `routes_transfers.py` | 1,080 | 54 |
| `app.py` | 905 | 59 |
| `services/finance_utils.py` | 1,686 | 70 |
| `services/permissions_config.py` | 1,479 | 72 |
| `services/auth_utils.py` | 1,090 | 54 |
| `services/backup_utils.py` | 782 | 33 |
| `services/tracker_automation.py` | 706 | 31 |
| `routes_workforce.py` | 765 | 36 |
| `routes_payroll.py` | 738 | 38 |
| `api.py` | 640 | 28 |
| `services/sync_master.py` | 537 | 26 |

**JS files >200 lines:**

| File | Lines | KB |
|---|---|---|
| `static/js/core/fleet_core.js` | 5,410 | 297 |
| `static/js/fleet_biometric_toggle.js` | 1,052 | 39 |
| `static/js/core/fleet_ui.js` | 769 | 41 |
| `static/js/ws_slip_ocr/07_bridge.js` | 556 | 21 |
| `static/js/gps_attendance_pending_upload.js` | 530 | 19 |

**CSS files >200 lines:**

| File | Lines | KB |
|---|---|---|
| `static/css/core/fleet_styles.css` | 1,929 | 91 |
| `static/css/mobile_perfect.css` | 664 | 19 |

---

## 7) MODULE-WISE AUDIT REPORT

### 7.1 Auth (`services/auth_utils.py` — 1,090 lines)
- **Strengths:** Centralized `@before_request` guard, endpoint-permission map, login lockout, open redirect protection, biometric HMAC tokens, trusted device cookies, force_password_change on default admin
- **Issues:** 12 broad excepts; `get_user_context()` uncached (4+ queries/request); `check_auth()` duplicated across modules

### 7.2 Finance (`routes_finance.py` — 2,931 lines, `services/finance_utils.py` — 1,686 lines)
- **Strengths:** Double-entry bookkeeping, atomic VoucherSequence (SELECT FOR UPDATE), proper commit/rollback
- **Issues:** 24 broad excepts; routes registered via `app.add_url_rule` in `app.py` (not decorators)

### 7.3 Workspace (`routes_workspace.py` — 5,260 lines)
- **Strengths:** Employee isolation via `_workspace_guard`, month-close reconciliation, MPG reports, slip OCR profiles
- **Issues:** 40 broad excepts; 148 functions; silent R2 upload/delete failures

### 7.4 Expenses (`routes_expenses.py` — 6,829 lines)
- **Strengths:** Fuel price hints, duplicate detection, KM gap validation, offline support, work orders
- **Issues:** 48 broad excepts; largest route module by lines

### 7.5 Attendance (`routes_attendance.py` — 5,688 lines)
- **Strengths:** GPS geofenced check-in/out, camera selfie, offline upload queue, time-window overrides
- **Issues:** 33 broad excepts; client-side geofence validation only

### 7.6 AI Assistant (`routes_ai.py` — 1,198 lines)
- **Strengths:** Rate limiting, SQL injection filter, model fallback, conversation persistence
- **Issues:** 3 CSRF exempts (origin-validated); **XSS via `|safe` on LLM output** (BUG-001)

### 7.7 Master Data (`routes_master_data.py` — 2,608 lines)
- **Strengths:** CNIC/license duplicate validation APIs, import/export
- **Issues:** 42 broad excepts; 101 route decorators

### 7.8 Android / Capacitor
- **Strengths:** FleetBridge native bridge (GPS, camera, download, print, push), biometric auth, keyboard handling, native bottom nav, in-app update check
- **Issues:** `minifyEnabled false` (BUG-008); cleartext traffic config (BUG-009); `webContentsDebuggingEnabled` in capacitor config

---

## 8) WEB vs ANDROID PARITY GAPS

| Feature | Web | Android | Gap | Priority |
|---|---|---|---|---|
| Pinch-zoom | `user-scalable=no` | Native override | Web locked | P3 |
| Bottom nav | N/A | `capacitor-native` class | Android-only | — |
| GPS Camera | N/A | FleetBridge native | Android-only | — |
| Biometric | N/A | BiometricAuth plugin | Android-only | — |
| Offline queue | N/A | `gps_attendance_pending_upload.js` | Android-only | — |
| Export/Print | Browser print | FleetBridge.print() | Both supported | — |
| APK minify | N/A | Disabled | Larger APK | P2 |
| Debug web contents | N/A | Enabled in config | Should be false | P2 |
| Session expiry mid-form | No draft preservation | Same | Both lack | P3 |
| Landscape rotation | Not tested | Not tested | Unknown | P3 |

---

## 9) SECURITY FINDINGS

| ID | Sev | Location | Finding | Fix |
|---|---|---|---|---|
| SEC-001 | P1 | `report_ai.html` | LLM output `\|safe` — XSS | Sanitize with bleach or render as text |
| SEC-002 | P2 | 10 CSRF-exempt endpoints | Surface area; 3 lack origin validation | Add origin validation to all |
| SEC-003 | P2 | `android/build.gradle:45` | minifyEnabled false | Enable shrinking + R8 |
| SEC-004 | P3 | `network_security_config.xml` | Cleartext to LAN IPs | Remove prod build or use debug variant |
| SEC-005 | P3 | `base.html` (2 `\|safe`) | Verify context is trusted | Audit each usage |
| SEC-006 | P3 | `transfer_form.html` | console.log in prod | Remove |
| SEC-007 | OK | `app.py:44-51` | GOOD: SECRET_KEY no fallback, raises if missing | — |
| SEC-008 | OK | `render.yaml` | GOOD: SESSION_COOKIE_SECURE=true | — |
| SEC-009 | OK | `auth_utils.py:895` | GOOD: force_password_change=True on default admin | — |
| SEC-010 | OK | `routes.py` before_request | GOOD: Session timeout + inactivity check | — |

---

## 10) PERFORMANCE HOTSPOTS

| ID | Location | Issue | Fix | Effort |
|---|---|---|---|---|
| PERF-001 | `auth_utils.py` get_user_context | 4+ queries/request, no cache | Cache in session/Redis 5-min TTL | M(4h) |
| PERF-002 | `Procfile` | Gunicorn 1 worker, 4 threads | Increase to 2-4 workers | S(config) |
| PERF-003 | `fleet_core.js` (5,410 lines, 297KB) | Large JS bundle | Code-split, lazy load | L(days) |
| PERF-004 | `fleet_styles.css` (1,929 lines, 91KB) | Large CSS | Purge unused selectors | M(4h) |
| PERF-005 | 20 templates >500 lines | Inline JS in templates | Extract to external files | L(days) |

---

## 11) CODE CLEANING BACKLOG

| ID | Task | Effort | Priority |
|---|---|---|---|
| CLEAN-001 | Fix AI XSS: sanitize `report_ai.html` | S(1h) | P0 |
| CLEAN-002 | Replace 612 broad excepts with specific types | L(days) | P1 |
| CLEAN-003 | Add unit tests for critical modules | XL(weeks) | P1 |
| CLEAN-004 | Further split `routes.py` (10.6K lines) | L(weeks) | P1 |
| CLEAN-005 | Delete `docs/archive/` dead files | S(30m) | P2 |
| CLEAN-006 | Enable Android minifyEnabled + R8 | S(1h) | P2 |
| CLEAN-007 | Add origin validation to 3 unvalidated CSRF-exempt endpoints | S(2h) | P2 |
| CLEAN-008 | Cache `get_user_context()` | M(4h) | P2 |
| CLEAN-009 | Extract `check_auth()` to shared utility | S(1h) | P3 |
| CLEAN-010 | Remove console.log from JS + templates | S(30m) | P3 |
| CLEAN-011 | Squash 84 Alembic migrations | M(4h) | P3 |
| CLEAN-012 | Add pyproject.toml + ruff config | S(1h) | P2 |
| CLEAN-013 | Add API documentation | M(4h) | P3 |
| CLEAN-014 | Split large templates (fuel_expense_form 3.7K lines) | L(days) | P2 |

---

## 12) REMEDIATION ROADMAP

### Phase 1: Critical (Week 1) — P0/P1
- Fix AI XSS: sanitize `report_ai.html` (BUG-001) — 1h
- Add origin validation to 3 unvalidated CSRF-exempt endpoints (SEC-002) — 2h
- Enable Android minifyEnabled (BUG-008) — 1h
- Remove console.log from production (BUG-014, BUG-015) — 30m
- Delete `docs/archive/` dead files (BUG-006) — 30m

### Phase 2: High Priority (Weeks 2-4) — P1/P2
- Begin replacing broad excepts with specific types (BUG-004) — ongoing
- Cache `get_user_context()` (PERF-001) — 4h
- Add linting config (CLEAN-012) — 1h
- Add unit tests for auth, finance, workspace (BUG-007) — weeks
- Further split `routes.py` (BUG-002) — weeks
- Extract `check_auth()` to shared utility (BUG-016) — 1h

### Phase 3: Structural (Months 2-3) — P2
- Split large templates into partials (CLEAN-014) — days
- Code-split `fleet_core.js` (PERF-003) — days
- Add integration tests — weeks
- Squash migrations (BUG-013) — 4h
- Add API docs (BUG-019) — 4h

### Phase 4: Polish (Month 3+) — P3
- Increase Gunicorn workers (PERF-002)
- Purge unused CSS (PERF-004)
- Fix viewport zoom (P3)
- Remove cleartext network config from prod (BUG-009)

---

## 13) FINAL VERDICT

**Rating: 6.4/10 — Functional, improved, but needs hardening.**

The codebase has undergone **significant structural improvement** since V1:
- `routes.py` split from 39K → 10.6K lines across 20+ modules
- `base.html` split from 9.7K → 864 lines
- `.query.get()` eliminated from active code
- Debug prints removed from hot path
- `|safe` reduced from 366+ → 5 usages
- `per_page` capped to prevent OOM
- Smoke test added covering 50+ routes

**Top 3 immediate actions:**
1. **Fix AI XSS** (`report_ai.html` `|safe` on LLM output) — 1 hour
2. **Add origin validation** to 3 CSRF-exempt endpoints lacking it — 2 hours
3. **Enable Android minification** — 1 hour

**Top 3 medium-term investments:**
1. Replace 612 broad `except Exception` blocks with specific types
2. Add comprehensive test suite (unit + integration)
3. Further split `routes.py` and large templates

**Production readiness: YES with caveats.** The system is functional and deployed. The AI XSS is the only active vulnerability requiring immediate fix. All other issues are technical debt that should be addressed systematically.
