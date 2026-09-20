# 14 — Reports

## Report Centre

- Entry: `/reports/` → `templates/reports_index.html`  
- Module: `routes/routes_reports.py`  
- Hub tiles also deep-link from module hubs  

Permission section: `reports` (+ granular codes in `permissions_config.py`).

---

## Report inventory by area

### General / master (`routes_reports.py`)
- Activity log / geo activity logs  
- AI report  
- Project / district / vehicle summaries  
- Driver profile / vehicle profile (incl. shareable `/p/driver-profile/<token>`)  
- Expiry report  
- Parking utilization  
- Uniform sizes  
- Engine/chassis  

### Tracker & operations (`routes_tracker_reports.py`)
- Active drivers  
- Oil change alert  
- Speed monitoring  
- Mileage  
- Unauthorized movement  
- Task start delay / turnaround  
- Tracker difference  
- Driver seat available  
- Missing documents  
- Bank account  
- Driver salary slip  

### Attendance (`routes_attendance.py`)
- Attendance list export/print  
- Monthly attendance report  
- Day-wise daily report  
- TRA attendance sheet  

### Tasks (`routes_tasks.py` / `routes_task_ops.py`)
- Daily task report / vehicle period detail / pending  
- Logbook covers / PDF  
- Unexecuted task report / exports  
- Red / without-task lists  

### Tracking PortalXS (`routes_tracking.py`)
- Trips (+ CSV)  
- Fleet report (+ CSV)  
- Mileage report (+ CSV)  
- Trends  
- Alerts  

### Ufone (`routes_ufone.py`)
- Task counts  
- Distance / ignition  
- Patient reports  
- CSV/export routes for vehicles/tasks/distance  

### Maintenance / expenses
- Maintenance baseline alert report  
- Fuel/oil operational lists (list+export patterns)  

### Workspace
- `/workspace/reports`, MPG report (+ PDF/Excel)  
- Dashboard financial report kinds  

### Finance / payroll
- Ledger, balance sheet, wallet dashboard  
- Payslips  

### Books
- Physical book assignment reports (module-specific)

---

## Export patterns

Common approaches in codebase:

- CSV streaming responses  
- Excel via pandas / openpyxl / XlsxWriter  
- Print-friendly HTML  
- PDF for selected task/workspace reports  

---

## Dashboard (related)

Main dashboard `/` or `/dashboard` is KPI cards + charts gated by `dashboard_card_*` and `view_fleet_map` permissions — not the Report Centre, but overlapping analytics.

Separate dashboards: PortalXS `/tracking`, Ufone `/ufone`, Workspace `/workspace`.

---

## Adding a new report (recommended)

1. Place route in the correct module (tracker vs attendance vs reports).  
2. Add permission code to `permissions_config.PERMISSION_TREE` + `auth_utils` endpoint map.  
3. Add hub tile in `hub_registry.py` if it belongs in a module hub.  
4. Optionally add Report Centre tile.  
5. Reuse list scoping helpers (`list_visibility`) and export utilities (`utils`).
