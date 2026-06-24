# Restructuring Plan — No files deleted, only moved

## Folder Structure:
```
routes/              # All route handler modules
  __init__.py
  routes.py          # Main shared helpers (was root routes.py)
  routes_ai.py
  routes_assignments.py
  routes_attendance.py
  routes_auth.py
  routes_books.py
  routes_dashboard.py
  routes_employees.py
  routes_expenses.py
  routes_finance.py
  routes_master_data.py
  routes_misc.py
  routes_payroll.py
  routes_reports.py
  routes_system.py
  routes_task_ops.py
  routes_tasks.py
  routes_tool_workstation.py
  routes_tracker_reports.py
  routes_transfers.py
  routes_workforce.py
  routes_workspace.py
  api.py             # Mobile API blueprint

services/            # Business logic services & schedulers
  __init__.py
  auth_utils.py
  backup_config.py
  backup_jobs.py
  backup_utils.py
  driver_doc_history_utils.py
  expiry_reminder_scheduler.py
  expiry_reminder_service.py
  finance_utils.py
  freeze_utils.py
  fuel_expense_settings.py
  fuel_market_scan_scheduler.py
  hub_registry.py
  list_visibility.py
  nav_back.py
  notification_service.py
  permissions_config.py
  push_notifications.py
  r2_storage.py
  attendance_reminder_scheduler.py
  attendance_reminder_service.py
  tracker_automation.py
  sync_master.py

database/            # DB scripts, seeds, migrations helpers
  __init__.py
  add_attendance_geofence_columns.py
  add_columns.py
  backfill_district_project.py
  check_permissions.py
  seed_chart_of_accounts.py
  update_db.py

docs/                # All documentation (already exists)
  (existing + moved root .md files)

config/              # Config files
  __init__.py
  backup_config.py -> stays in services (has logic)
  
## Root (stays):
  app.py             # Entry point
  models.py          # SQLAlchemy models
  forms.py           # WTForms
  utils.py           # Core utilities (pk_now, etc.)
  vehicle_sort_utils.py  # Small util, stays at root
  requirements.txt
  runtime.txt
  Procfile
  .env / .env.example / .env.local
  .flaskenv
  .gitignore / .gitattributes
  .python-version
  render.yaml
  package.json / package-lock.json
  capacitor.config.json
  firebase-service-account.json
  run-local.bat
```

## Import Strategy:
- Each folder gets `__init__.py` 
- `sys.path` already includes root (where app.py runs from)
- We add root to sys.path in each `__init__.py` so `import models`, `import app` still work
- Cross-package imports change: `from routes import X` → `from routes.routes import X`
- BUT: this is very risky with 20+ route files all importing `from routes import ...`

## SAFER APPROACH:
Keep routes.py at root (it's the shared helpers hub).
Move only the routes_*.py files into routes/ package.
Use `from routes.routes_auth import ...` pattern.

Actually, the SAFEST approach that won't break anything:
1. Move files into folders
2. Add each folder to sys.path via __init__.py
3. This way `import routes_auth` still works from anywhere

Wait - that won't work because Python doesn't search subdirectories by default.

## REAL APPROACH:
Use conftest.py-style path manipulation OR just add the folders to sys.path in app.py early.

BEST APPROACH: Add folders to PYTHONPATH via sys.path.insert in app.py before any imports.
