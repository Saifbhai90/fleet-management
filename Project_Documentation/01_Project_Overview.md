# 01 — Project Overview

**Product name:** Fleet Manager (also: Company Management)  
**Package / App ID:** `com.fleetmanager.app` (Capacitor Android)  
**Version (npm):** 2.1.1  
**Analyzed:** 2026-07-21  
**Repo root:** `company_management/`

---

## What it is

A production **fleet & company management ERP** focused on ambulance / emergency fleet operations in Pakistan. It combines:

- Organizational master data (companies, projects, districts, parking stations)
- Vehicles, drivers, and employees with assignments and transfers
- GPS + camera attendance for drivers
- Daily tasks, emergency task uploads, logbooks, and ops penalties
- Fuel, oil, and maintenance expenses with cloud media
- Dual accounting: company ledger + per-employee financial workspace
- Payroll driven by attendance
- Two live GPS portals: **PortalXS** and **Ufone BPOCOPS**
- Capacitor Android shell, push notifications, backups, and Gemini AI assistant

**Timezone:** `Asia/Karachi` (`APP_TIMEZONE`). Dates typically display as `dd-mm-yyyy`.

---

## Tech stack (summary)

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11, Flask 3.1, SQLAlchemy 2, Flask-Migrate/Alembic |
| DB | PostgreSQL (Render production), SQLite (local `db/local.db`) |
| Frontend | Jinja2 templates, Bootstrap 5, custom CSS/JS |
| Mobile | Capacitor 6 Android WebView → Render URL `/mobile-init` |
| Storage | Cloudflare R2 (S3 API) via boto3; local `uploads/` fallback |
| Jobs | APScheduler (in-process); no Celery |
| Deploy | Render Blueprint (`render.yaml`), Gunicorn gthread |
| Auth | Session cookies (web) + JWT Bearer (`/api/v1`) |

---

## Business domains

1. **Master Data** — companies, projects, districts, vehicles, parking, drivers, employees, designations, products  
2. **Assignments & Transfers** — link and move fleet entities with audit history  
3. **Workforce** — driver exit/rejoin, penalties, employee lifecycle  
4. **Attendance** — geofenced GPS check-in/out with camera, leave, TRA sheets  
5. **Task & Logbook** — workbook uploads, daily entries, red/without-task, tracker comparison  
6. **Expenses** — fuel, oil, maintenance work orders  
7. **Finance & Workspace** — company vouchers + isolated employee books  
8. **Payroll** — salary config, monthly runs, payslips  
9. **Books** — physical logbook inventory  
10. **Fleet Tracking (PortalXS)** — live map, history, trips, alerts  
11. **Ufone BPOCOPS** — ambulance portal mirror (map, tasks, patients, maintenance)  
12. **Administration** — users/roles, form control, backups, tracker automation, tool workstation  

---

## Clients

| Client | How it connects |
|--------|-----------------|
| Browser (desktop/mobile web) | Same Flask app, session auth |
| Capacitor Android APK | Loads production URL; biometric lock; camera/geo/FCM plugins |
| JWT mobile API | `/api/v1/*` for structured mobile calls |
| Electron-ish `fleet-desktop/` | Desktop wrapper (companion) |
| Admin Personal Tools / daedalOS | Embedded tools UI under administration |

---

## Production deployment snapshot

- **Host:** Render web service `fleet-manager` (Starter plan, ~512MB RAM)  
- **Workers:** Gunicorn `workers=1`, `threads=4`, `--timeout 600`  
- **DB:** Managed Postgres starter  
- **Health:** `GET /health`  
- **Pre-deploy:** `scripts/render_migrate.sh` (Alembic upgrade)  
- **Public URL (Capacitor):** `https://fleet-management-xdvj.onrender.com`

---

## Scale indicators (approx.)

| Metric | Value |
|--------|-------|
| SQLAlchemy models | ~104 classes |
| Alembic migrations | 84 versions |
| HTTP endpoints | ~700–750 |
| Route modules | 25+ under `routes/` |
| Jinja templates | 350+ |
| Formal Flask blueprints | 2 (`api_bp`, `ai_bp`) |

---

## Related existing docs (do not replace)

The repo already has operational docs under `docs/` (knowledge base, audits, Capacitor, finance schema). This `Project_Documentation/` folder is the **canonical AI/developer onboarding pack** generated 2026-07-21.

---

## Lead-developer rules (from this analysis)

Before any code change:

1. Understand existing architecture (see `MASTER_CONTEXT.md`).  
2. Reuse existing helpers in `services/` and `routes/routes.py`.  
3. Never duplicate permission, storage, or GPS client logic.  
4. Match current coding style (flat imports via `sys.path` for `routes/`/`services/`).  
5. Keep backward compatibility (sessions, permission codes, URL names).  
6. Explain impact before changing a shared module.  
7. Ask when requirements are unclear.
