# 02 — System Architecture

## High-level architecture

```
┌─────────────────────┐     ┌─────────────────────┐
│  Browser / PWA      │     │ Capacitor Android   │
│  (session cookie)   │     │ WebView + plugins   │
└──────────┬──────────┘     └──────────┬──────────┘
           │                           │
           └────────────┬──────────────┘
                        ▼
              ┌─────────────────────┐
              │  Flask app.py       │
              │  ProxyFix + CSRF    │
              │  Compress (br/gzip) │
              └──────────┬──────────┘
         ┌───────────────┼────────────────┐
         ▼               ▼                ▼
   routes/*         api_bp /api/v1     ai_bp Gemini
   (session)        (JWT)              (assistant)
         │               │                │
         └───────────────┼────────────────┘
                         ▼
              ┌─────────────────────┐
              │ SQLAlchemy models   │
              │ Postgres / SQLite   │
              └──────────┬──────────┘
                         │
     ┌───────────────────┼────────────────────┐
     ▼                   ▼                    ▼
 Cloudflare R2      PortalXS SOAP        Ufone BPOCOPS
 (media)            + TrackingWorld      HTTP API
                    Playwright
     ▼
 Firebase FCM / SMTP backups / Gemini
```

This is a **single monolithic Flask application**, not microservices.

---

## Boot sequence (`app.py`)

1. Insert `routes/`, `services/`, `database/`, `config/` onto `sys.path` (flat imports).  
2. Load `.env`; require `SECRET_KEY`.  
3. Configure SQLAlchemy URI (normalize `postgres://` → `postgresql://`; absolute SQLite paths).  
4. Pool settings: Postgres `pool_size=10`, `max_overflow=20`, `pool_recycle=120`, keepalives; SQLite simpler.  
5. CSRFProtect, Flask-Migrate, Flask-Compress.  
6. Optional `LOCAL_DB_GUARANTEED` hard-check for `db/local.db`.  
7. Startup tasks (when not reloader child): `create_all`, migrations, R2 CORS sync, permission seed, CoA seed, employee assignment backfill.  
8. Import route modules (side-effect `@app.route`).  
9. `register_book_routes(app)` + many `app.add_url_rule` for finance/workspace/payroll.  
10. Register `api_bp`, `ai_bp`.  
11. Start APSchedulers: backup, attendance reminders, expiry reminders, fuel market scan.

---

## Route registration patterns

| Pattern | Used for |
|---------|----------|
| `@app.route` in `routes/routes_*.py` | Most fleet features |
| `from routes import *` | Shared helpers + residual in `routes.py` |
| `app.add_url_rule(...)` in `app.py` | Finance, workspace, payroll |
| Flask Blueprint | Mobile API (`/api/v1`), AI assistant |

**Only two formal blueprints.** Almost everything hangs off the global `app` object.

---

## Layering

| Layer | Location | Responsibility |
|-------|----------|----------------|
| HTTP / forms / templates | `routes/` | Request handling, flash, redirects |
| Shared route helpers | `routes/routes.py` | Large shared utility surface |
| Domain services | `services/` | External APIs, schedulers, RBAC, R2, nav |
| ORM | `models.py` | Schema source of truth |
| Forms | `forms.py` | WTForms definitions |
| Templates | `templates/` | Jinja2 UI |
| Static | `static/` | CSS/JS/vendor assets |

**Pattern:** Historically fat routes; newer integrations (PortalXS, Ufone, R2, FCM, schedulers) live in `services/`. Core CRUD (vehicles, fuel, attendance) still largely in route modules.

---

## Module hubs (navigation)

Sidebar hubs are defined in `services/hub_registry.py` and rendered via `/hub/<slug>`:

| Slug | Section permission |
|------|--------------------|
| `master-data` | `master` |
| `assignments` | `assignment` |
| `transfers` | `transfer` |
| `workforce` | `driver_status` |
| `attendance` | `attendance` |
| `task-logbook` | `task_report` |
| `finance` | `accounts` / expenses / workspace |
| `payroll` | `payroll` |
| `books` | `books` |
| `notifications` | notifications |
| `fleet-tracking` | `tracking` |
| `ufone` | `ufone` |
| `administration` | `users_manage` / backup |

Back-nav alignment: `services/nav_back.py`.

---

## Process model (production)

- **1 Gunicorn worker** (Starter RAM constraint) with **4 threads**.  
- APScheduler and PortalXS/Ufone polling run **in-process** → only one worker is intentional to avoid duplicate jobs.  
- Ephemeral filesystem on Render → media on R2; backups exclude heavy log tables by default.

---

## Dual GPS / tracking subsystems

| System | Purpose | Protocol |
|--------|---------|----------|
| PortalXS | Primary fleet live tracking hub | SOAP + DB cache/mapping |
| Ufone BPOCOPS | Ambulance ops portal (tasks, patients, map) | HTTP API + cache tables |
| TrackingWorld | Activity XLSX downloads | Playwright automation |
| Device GPS | Attendance geofence only | Capacitor Geolocation |

These are **not** interchangeable; attendance GPS ≠ fleet tracker GPS.

---

## Dual accounting

```
Employee daily books  →  workspace_* tables (isolated by employee_id)
Month close           →  bridge journal into company Account/JournalEntry
```

Company finance (`routes_finance.py`) and workspace (`routes_workspace.py`) share journal concepts via `finance_utils.py` but keep separate tables.

---

## Configuration sources

| Source | Role |
|--------|------|
| Environment / `.env` | Secrets, R2, mail, Gemini, session |
| `app.py` | Flask config object |
| `SystemSetting` model | Runtime toggles |
| Form Control tabs | Attendance windows, freeze dates, fuel/oil limits |
| `render.yaml` | Infra blueprint |

There is **no** standalone `config.py`.

---

## Failure & resilience notes

- DB: `pool_pre_ping` against Render idle disconnects.  
- ProxyFix depth 2 for HTTPS behind Render.  
- R2 optional at boot (local can run without full R2 for non-upload paths).  
- Schedulers wrap start failures in warnings (app still boots).
