# 07 — Backend

## Entry point

`app.py` — Flask application, config, DB, CSRF, compression, route wiring, schedulers.

## Package layout (Python)

```
app.py
models.py
forms.py
routes/          # HTTP handlers (flat-imported via sys.path)
services/        # Business + integrations
database/        # One-off DB scripts
migrations/      # Alembic
scripts/         # Deploy / Capacitor / ops scripts
tests/           # Smoke tests primarily
```

Because `routes/` and `services/` are on `sys.path`, imports look like:

```python
from models import Vehicle
from auth_utils import check_auth
from r2_storage import upload_image_bytes
```

…not `from services.auth_utils import ...`.

---

## Route modules

| Module | Domain |
|--------|--------|
| `routes.py` | Shared helpers + residual (still large) |
| `routes_master_data.py` | Companies, projects, vehicles, drivers, parking, districts, parties, products |
| `routes_assignments.py` | Assignments |
| `routes_transfers.py` | Transfers |
| `routes_workforce.py` | Job left/rejoin, leave, posts |
| `routes_employees.py` | Employee lifecycle |
| `routes_attendance.py` | Attendance + GPS APIs |
| `routes_tasks.py` | Task reports / uploads / logbook |
| `routes_task_ops.py` | Red / without / unexecuted / penalties |
| `routes_expenses.py` | Fuel, oil, maintenance |
| `routes_finance.py` | Company accounts (registered via `add_url_rule`) |
| `routes_workspace.py` | Employee workspace |
| `routes_payroll.py` | Payroll |
| `routes_books.py` | Physical books |
| `routes_reports.py` | Report Centre |
| `routes_tracker_reports.py` | Ops/tracker reports |
| `routes_dashboard.py` | Dashboard, notifications, reminders, app updates |
| `routes_auth.py` | Login, users, roles, form control |
| `routes_tracking.py` | PortalXS |
| `routes_ufone.py` | Ufone BPOCOPS |
| `routes_system.py` | Health, tracker automation, driver portal |
| `routes_misc.py` | Mobile init, biometric, FCM, PWA |
| `routes_ai.py` | Gemini AI blueprint |
| `routes_tool_workstation.py` | Utility tools shell |
| `api.py` | JWT `/api/v1` |

---

## Services modules

| Service | Responsibility |
|---------|----------------|
| `auth_utils.py` | Login, permission codes, endpoint map, seed |
| `permissions_config.py` | Hierarchical permission tree + expansions |
| `hub_registry.py` | Sidebar hubs |
| `nav_back.py` | Back navigation |
| `r2_storage.py` | Cloudflare R2 uploads |
| `push_notifications.py` | Firebase FCM |
| `notification_service.py` | In-app + push orchestration |
| `portalxs_soap_client.py` / `portalxs_service.py` / `portalxs_crypto.py` | PortalXS |
| `ufone_api_client.py` / `ufone_service.py` | Ufone |
| `tracker_automation.py` | Playwright TrackingWorld |
| `backup_*` | Backup zip/email/schedule |
| `attendance_reminder_*` | Check-in/out reminders |
| `expiry_reminder_*` | License/CNIC/oil alerts |
| `fuel_market_scan_scheduler.py` | Fuel price scan |
| `slip_ocr_server.py` | Server OCR fallback |
| `finance_utils.py` | Double-entry helpers |
| `freeze_utils.py` | Write freeze windows |
| `fuel_expense_settings.py` | Fuel form control settings |
| `list_visibility.py` | List scoping helpers |
| `vehicle_sort_utils.py` | Vehicle ordering |
| `driver_doc_history_utils.py` | Doc history |
| `sync_master.py` | Local↔remote DB sync tooling |
| `utils.py` | Formatting, CSV, timezone helpers |

---

## Background jobs

Started from `app.py` when `_run_startup_tasks`:

| Job | Interval | Module |
|-----|----------|--------|
| DB backup email | configured time | `backup_config` / `backup_jobs` |
| Attendance reminders | ~1 min | `attendance_reminder_scheduler` |
| Expiry / oil reminders | ~1 hour | `expiry_reminder_scheduler` |
| Fuel market scan | ~1 hour | `fuel_market_scan_scheduler` |

**In-process threads** (not APScheduler): PortalXS polling, Ufone polling, expense R2 upload workers, tracker automation jobs.

---

## Forms

`forms.py` — large WTForms inventory for master data, expenses, auth, etc. Prefer extending existing forms over inventing parallel validation.

---

## Key backend conventions

1. Use `db.session.get(Model, id)` (SQLAlchemy 2 style).  
2. Guard routes with `check_auth('permission_code')`.  
3. Scope queries by session allowed projects/districts/vehicles when applicable.  
4. Store media via `r2_storage` when R2 is configured.  
5. Prefer Pakistan timezone helpers from `utils`.  
6. Avoid inline imports unless circular dependency (workspace rule).  
7. Do not add Celery — extend APScheduler/services pattern.

---

## Health & ops endpoints

- `GET /health` — Render health check  
- System health / Render API status under administration (`RENDER_API_KEY`, `RENDER_SERVICE_ID`)  
- Tracker automation admin UI for Playwright jobs
