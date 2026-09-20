# 19 — Project Map

Quick orientation map of the repository.

```
company_management/
├── app.py                          # Flask entry, config, wiring, schedulers
├── models.py                       # ~104 SQLAlchemy models (schema SoT)
├── forms.py                        # WTForms
├── requirements.txt                # Python deps
├── Procfile / runtime.txt          # Gunicorn + Python 3.11.6
├── render.yaml                     # Render Blueprint (web + Postgres)
├── package.json / capacitor.config.json / www/
├── PORTALXS_INTEGRATION.md
├── .env.example                    # Env template (no secrets)
│
├── routes/                         # HTTP layer
│   ├── api.py                      # Blueprint /api/v1 JWT
│   ├── routes.py                   # Shared helpers (+ residual)
│   ├── routes_auth.py
│   ├── routes_dashboard.py
│   ├── routes_master_data.py
│   ├── routes_assignments.py
│   ├── routes_transfers.py
│   ├── routes_workforce.py
│   ├── routes_employees.py
│   ├── routes_attendance.py
│   ├── routes_tasks.py
│   ├── routes_task_ops.py
│   ├── routes_expenses.py          # Fuel / oil / maintenance
│   ├── routes_finance.py
│   ├── routes_workspace.py
│   ├── routes_payroll.py
│   ├── routes_books.py
│   ├── routes_reports.py
│   ├── routes_tracker_reports.py
│   ├── routes_tracking.py          # PortalXS
│   ├── routes_ufone.py             # Ufone BPOCOPS
│   ├── routes_system.py
│   ├── routes_misc.py              # mobile-init, biometric, FCM
│   ├── routes_ai.py                # Gemini blueprint
│   └── routes_tool_workstation.py
│
├── services/                       # Integrations & shared domain logic
│   ├── auth_utils.py
│   ├── permissions_config.py
│   ├── hub_registry.py / nav_back.py
│   ├── r2_storage.py
│   ├── push_notifications.py / notification_service.py
│   ├── portalxs_*.py
│   ├── ufone_*.py
│   ├── tracker_automation.py
│   ├── backup_*.py
│   ├── attendance_reminder_*.py
│   ├── expiry_reminder_*.py
│   ├── fuel_market_scan_scheduler.py
│   ├── finance_utils.py / freeze_utils.py
│   ├── slip_ocr_server.py
│   ├── sync_master.py
│   └── utils.py
│
├── templates/                      # Jinja2 (350+)
│   ├── base.html
│   ├── tracking/
│   ├── ufone/
│   ├── workspace/ finance/ payroll/ books/
│   ├── reports/ partials/ tool_workstation/
│   └── …
│
├── static/
│   ├── css/                        # fleet + mobile + ufone themes
│   ├── js/                         # fleet_core/mobile/ui + OCR + ufone
│   ├── vendor/                     # tesseract, tom-select, …
│   ├── tool_workstation/
│   └── fleet_personal_pc/          # daedalOS assets
│
├── migrations/versions/            # 84 Alembic revisions
├── android/                        # Capacitor native Android
├── config/                         # Firebase SA, android signing, sync state
├── uploads/                        # Local media (dev / fallback)
├── scripts/                        # migrate, APK, Capacitor helpers
├── tools/bpocops_capture/          # Ufone HAR capture toolkit
├── docs/                           # Existing audits & guides
├── tests/                          # Smoke tests
├── database/                       # DB helper scripts
├── fleet-desktop/                  # Desktop shell
├── daedalOS/                       # Personal tools OS source
├── tool_workstation/               # 120-utility registry
└── Project_Documentation/          # THIS onboarding pack
```

---

## Feature → primary files

| Feature | Routes | Services / models |
|---------|--------|-------------------|
| Login / RBAC | `routes_auth.py` | `auth_utils`, `permissions_config`, User/Role |
| Master data | `routes_master_data.py` | Company…Vehicle…Driver |
| Assignments | `routes_assignments.py` | Vehicle/Driver FKs |
| Transfers | `routes_transfers.py` | *Transfer models |
| Attendance | `routes_attendance.py` | DriverAttendance*, R2, reminder schedulers |
| Tasks | `routes_tasks.py`, `routes_task_ops.py` | VehicleDailyTask, RedTask, … |
| Fuel/Oil/Maint | `routes_expenses.py` | FuelExpense*, Maintenance*, R2 |
| Finance | `routes_finance.py` | Account, Journal*, FundTransfer |
| Workspace | `routes_workspace.py` | workspace_*, slip OCR |
| Payroll | `routes_payroll.py` | EmployeeSalaryConfig, MonthlyPayroll |
| PortalXS | `routes_tracking.py` | portalxs_* |
| Ufone | `routes_ufone.py` | ufone_* |
| Mobile API | `api.py` | JWT |
| AI | `routes_ai.py` | Gemini |
| Hubs / nav | dashboard + hub routes | `hub_registry`, `nav_back` |

---

## Env vars (see `.env.example`)

`SECRET_KEY`, `DATABASE_URL`, session/mail/backup, `APP_TIMEZONE`, `APP_BASE_URL` / Render URL, `R2_*`, Firebase, `GOOGLE_API_KEY` / Gemini, `RENDER_API_*`, `EXPENSE_ATTACHMENT_MAX_MB`, `FLEET_PERSONAL_PC_URL`, `FLASK_DEBUG`, `PORT`.

---

## Doc index

| File | Topic |
|------|-------|
| `01_Project_Overview.md` | What / stack / domains |
| `02_System_Architecture.md` | Boot, layers, hubs |
| `03_Database.md` | Models & relationships |
| `04_API_Documentation.md` | HTTP APIs |
| `05_Business_Flow.md` | End-to-end flows |
| `06_Frontend.md` | Templates, CSS, JS |
| `07_Backend.md` | Routes & services |
| `08_Mobile_App.md` | Capacitor |
| `09_GPS_System.md` | Four GPS systems |
| `10_Attendance_System.md` | Check-in/out |
| `11_Task_Management.md` | Tasks / logbook |
| `12_Fuel_Management.md` | Fuel |
| `13_Maintenance.md` | Internal + Ufone |
| `14_Reports.md` | Report inventory |
| `15_Security.md` | AuthZ / threats |
| `16_Performance.md` | Bottlenecks |
| `17_Bugs_and_Risks.md` | Risk register |
| `18_TODO.md` | Backlog |
| `19_Project_Map.md` | This map |
| `MASTER_CONTEXT.md` | Single AI briefing |
