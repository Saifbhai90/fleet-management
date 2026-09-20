# MASTER_CONTEXT — Fleet Manager / Company Management

> **Audience:** Any AI or developer joining this repo.  
> **Rule:** Read this before changing code. Documentation-only analysis date: **2026-07-21**.  
> **Do not** invent parallel modules when an existing `routes_*` / `services/*` path already exists.

---

## 1. One-paragraph brief

**Fleet Manager** is a production Flask monolith for Pakistani ambulance/emergency fleet operations. It manages org master data, vehicles/drivers, GPS+camera attendance, task logbooks, fuel/oil/maintenance, dual accounting (company + per-employee workspace), payroll, PortalXS live tracking, Ufone BPOCOPS ambulance portal, Capacitor Android shell, R2 media, FCM push, APScheduler jobs, and a Gemini AI assistant. Deployed on Render (Starter, 1 Gunicorn worker) with Postgres; local SQLite via `db/local.db`.

---

## 2. Absolute paths & entry

- App: `app.py`  
- Schema: `models.py`  
- Forms: `forms.py`  
- HTTP: `routes/` (flat-imported; `sys.path` includes `routes/` and `services/`)  
- Env template: `.env.example`  
- Deploy: `render.yaml`, `Procfile`  
- Mobile: `capacitor.config.json` → Render URL `/mobile-init`  
- This pack: `Project_Documentation/`

---

## 3. Architecture invariants (never violate casually)

1. **Monolith** — no microservices. Prefer new `routes_*.py` + `services/*.py`.  
2. **Only two blueprints:** `api_bp` (`/api/v1`), `ai_bp`. Everything else is `@app.route` or `app.add_url_rule`.  
3. **Flat imports** — `from auth_utils import check_auth` not `from services.auth_utils...`.  
4. **RBAC default-deny** — add `permissions_config` tree + `auth_utils.ENDPOINT_PERMISSION_MAP` for new endpoints.  
5. **Hubs** — user-facing modules registered in `hub_registry.HUBS`.  
6. **Media** — Cloudflare R2 via `r2_storage.py` (WebP images); Render disk is ephemeral.  
7. **Single web worker** — in-process schedulers + GPS polling; do not raise workers without extracting jobs.  
8. **Timezone** — `Asia/Karachi`.  
9. **Dual GPS** — device GPS ≠ PortalXS ≠ Ufone ≠ TrackingWorld automation.  
10. **Dual books** — `workspace_*` isolated until month-close bridges to company journals.

---

## 4. Org & domain model (mental model)

```
Company → Project → Districts + ParkingStations
                 → Vehicles ↔ Drivers
                 → Employees (M2M projects/districts)

Attendance: DriverAttendance (date + Morning/Night segment) + geofence at ParkingStation
Tasks: uploads (Emergency/Mileage/Activity) + VehicleDailyTask + Red/Without/Penalty
Expenses: FuelExpense / OilExpense / MaintenanceWorkOrder+Expense
Finance: Account + JournalEntry* + vouchers + FundTransfer
Workspace: parallel books per employee_id
Payroll: EmployeeSalaryConfig → MonthlyPayroll (attendance-aware)
Tracking: PortalXSAccount + VehicleMapping cache
Ufone: UfoneAccount + Vehicle/Task/Maintenance caches
Auth: User → Role → Permissions (M2M)
```

~104 SQLAlchemy models; 84 Alembic versions.

---

## 5. Route module cheat sheet

| Need | Open first |
|------|------------|
| Login/roles/form control | `routes_auth.py`, `auth_utils.py`, `permissions_config.py` |
| Companies/vehicles/drivers | `routes_master_data.py` |
| Assign / transfer | `routes_assignments.py`, `routes_transfers.py` |
| Attendance GPS | `routes_attendance.py` |
| Task logbook | `routes_tasks.py`, `routes_task_ops.py` |
| Fuel/oil/maintenance | `routes_expenses.py` |
| Company finance | `routes_finance.py` + `finance_utils.py` |
| Employee books | `routes_workspace.py` |
| Payroll | `routes_payroll.py` |
| PortalXS | `routes_tracking.py`, `portalxs_service.py` |
| Ufone | `routes_ufone.py`, `ufone_service.py` |
| Mobile JWT | `routes/api.py` |
| Dashboard/notifications | `routes_dashboard.py` |
| Reports | `routes_reports.py`, `routes_tracker_reports.py` |
| Mobile init/biometric | `routes_misc.py` |

Shared helpers still live in large `routes/routes.py` — search there before duplicating.

---

## 6. Permission sections

`dashboard`, `master`, `assignment`, `transfer`, `driver_status`, `attendance`, `task_report`, `expenses`, `accounts`, `workspace`, `reports`, `payroll`, `books`, `backup`, `users_manage`, `tracking`, `ufone`

Granular page/action codes live in `PERMISSION_TREE`. Master expands to all. Session may also scope `allowed_projects|districts|vehicles|shifts`.

---

## 7. Background jobs

| Job | Cadence | Module |
|-----|---------|--------|
| Backup email | scheduled HH:MM | `backup_config` / `backup_jobs` |
| Attendance reminders | ~1 min | `attendance_reminder_*` |
| Expiry/oil reminders | ~1 hour | `expiry_reminder_*` |
| Fuel market scan | ~1 hour | `fuel_market_scan_scheduler` |
| PortalXS / Ufone poll | ~30s threads | respective `*_service` |
| Tracker automation | on demand | `tracker_automation` + Playwright |

---

## 8. Third-party integrations

| System | Role |
|--------|------|
| PostgreSQL / SQLite | Primary data |
| Cloudflare R2 | Uploads |
| Firebase FCM | Push |
| PortalXS SOAP | Fleet live GPS |
| Ufone BPOCOPS HTTP | Ambulance ops portal |
| TrackingWorld | Playwright XLSX pull |
| Google Gemini | AI assistant |
| SMTP | Backup mail |
| Render | Hosting |

No Twilio/Stripe/Celery.

---

## 9. Frontend / mobile facts

- Jinja2 + Bootstrap; hubs at `/hub/<slug>`.  
- Core JS: `static/js/core/fleet_{core,ui,mobile}.js`.  
- Ufone: `ufone_theme.css` + `ufone_app.js`.  
- Capacitor 6 Android `com.fleetmanager.app` loads remote Flask; plugins for camera/geo/push/biometric.  
- Mega templates exist — edit surgically.

---

## 10. Environment essentials

Required: `SECRET_KEY`.  
Typical prod: `DATABASE_URL`, `SESSION_COOKIE_SECURE=true`, `R2_*`, Firebase, mail/backup, optional `GOOGLE_API_KEY`, `RENDER_API_KEY`.  
Local: often `DATABASE_URL=sqlite:///db/local.db` + `LOCAL_DB_GUARANTEED`.

---

## 11. Security & risk hotspots

- CSRF exemptions on some mobile/AI JSON routes — keep origin checks.  
- AI `\|safe` XSS risk historically.  
- Encrypted GPS portal passwords — Fernet key stability matters.  
- Broad `except Exception` masks bugs.  
- Attendance/payroll/finance changes are high business risk.  
- Session files `ufone_session_*.json` / portalxs sessions are sensitive.

Full register: `17_Bugs_and_Risks.md`, `15_Security.md`.

---

## 12. Coding rules for this project (standing orders)

1. **Understand** existing architecture before edits.  
2. **Reuse** `services/*` and existing route helpers — **no duplicate logic**.  
3. Match **current style** (flat imports, `check_auth`, flash/redirect patterns).  
4. Preserve **backward compatibility** (URL endpoint names, permission codes, session keys, DB columns).  
5. **Explain impact** (permissions, migrations, mobile, schedulers) before modifying shared modules.  
6. If requirements are unclear — **ask first**.  
7. Prefer extending models via Alembic migrations for production schema changes.  
8. Do not commit secrets (`.env`, keystores, live session JSON).  
9. Do not “fix” unrelated debt while implementing a feature.  
10. After feature work, update the relevant `Project_Documentation/*.md` if behavior meaningfully changes.

---

## 13. Where to read next (by task)

| Task type | Read |
|-----------|------|
| Any change | This file + `19_Project_Map.md` |
| Architecture | `02_System_Architecture.md` |
| Schema | `03_Database.md` |
| New API | `04_API_Documentation.md` + `15_Security.md` |
| Attendance | `10_Attendance_System.md` + `09_GPS_System.md` |
| Tasks | `11_Task_Management.md` |
| Fuel | `12_Fuel_Management.md` |
| Maintenance | `13_Maintenance.md` |
| Reports | `14_Reports.md` |
| Mobile | `08_Mobile_App.md` |
| Perf | `16_Performance.md` |
| Backlog | `18_TODO.md` |

Also useful legacy docs: `docs/PROJECT_KNOWLEDGE_BASE.md`, `docs/AUDIT_REPORT_V2.md`, `docs/FINANCE_SCHEMA.md`, `docs/README_CAPACITOR.md`, `PORTALXS_INTEGRATION.md` — prefer this pack when they conflict on counts/dates.

---

## 14. Verification snapshot (analysis time)

| Signal | Value |
|--------|-------|
| Flask | 3.1.3 |
| Models | ~104 |
| Migrations | 84 |
| Endpoints | ~700–750 |
| Hubs | 14 (incl. fleet-tracking, ufone) |
| Formal blueprints | 2 |
| npm app version | 2.1.1 |
| Prod plan | Render Starter, workers=1 threads=4 |

---

## 15. Lead developer declaration

This documentation establishes shared project memory. Future sessions should treat the AI assistant as **lead developer of Fleet Manager**: architecture-aware, reuse-first, compatibility-preserving, and explicit about impact before module changes.
