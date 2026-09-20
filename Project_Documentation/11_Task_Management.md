# 11 — Task Management

## Purpose

Capture daily vehicle work (tasks + odometer), ingest tracker emergency/mileage/activity data, justify anomalies (red / without-task / unexecuted), and produce logbooks and comparison reports.

---

## Models

| Model | Role |
|-------|------|
| `VehicleDailyTask` | Manual daily entry: date, start/close reading, tasks_count, odometer photo |
| `EmergencyTaskRecord` | Rows from emergency workbook upload |
| `VehicleMileageRecord` | Tracker mileage (`mileage`/`ptop`/`selected_km`) |
| `VehicleActivityRecord` | Activity trail points |
| `RedTask` | Red-flag justification; reason/action/fine |
| `VehicleMoveWithoutTask` | Movement without task; KM fields + fine |
| `UnexecutedTaskRecord` | Links emergency tasks + fines |
| `PenaltyRecord` | Penalty ledger (`source_type`: red_task \| without_task) |

---

## Route modules

### `routes_tasks.py` — entry & uploads
- `/task-report` list / new / pending  
- Workbook upload endpoints (emergency, mileage, core, activity, missing dates)  
- Detail APIs for uploaded rows  
- Logbook cover  
- Odometer photo upload API  
- PDF/export paths  

### `routes_task_ops.py` — anomalies & penalties
- `/red-task*`  
- `/vehicle-move-without-task*`  
- `/unexecuted-task-report*`  
- `/penalty-record*`  

### Related reports (`routes_tracker_reports.py`)
- Speed monitoring, mileage, unauthorized movement  
- Task start delay, turnaround  
- Tracker difference  

---

## End-to-end flow

```
Tracker Excel / Automation download
        │
        ▼
Upload into Emergency / Mileage / Activity tables
        │
        ▼
Ops creates VehicleDailyTask (or completes pending)
        │
        ▼
Compare readings vs tracker KM / movement
        │
        ├── OK → Logbook / daily report
        └── Anomaly → Red Task / Without Task / Unexecuted
                              │
                              ▼
                         PenaltyRecord (optional)
```

Emergency `status` fields are largely free-text from source systems; do not assume a strict enum unless validated in code.

---

## Permissions

Section `task_report` with granular codes:

- `task_report_upload`, `task_report_upload_list`
- `task_report_list`, `task_report_entry` (+ edit/delete)
- `task_report_pending`, `task_report_vehicle_period_detail`
- `red_task*`, `without_task*`, `task_report_logbook`

Form Control tab `daily_task_entry` can restrict entry behavior.

---

## UI / hub

Hub slug: `task-logbook`  
Tiles cover upload, new entry, daily/pending reports, red/without task, and key tracker reports.

---

## Overlaps with Ufone tasks

Ufone emergency tasks (`UfoneTaskCache` + `/ufone/tasks`) are a **separate portal** for BPOCOPS operations. Internal task logbook is the company’s operational record for contracts/payroll/logbooks. Integrating the two should be explicit — do not silently dual-write without a design decision.
