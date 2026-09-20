# 13 — Maintenance

There are **two maintenance concepts** in this project.

---

## A. Internal maintenance (fleet expenses)

### Models

| Model | Role |
|-------|------|
| `MaintenanceWorkOrder` | Header: `work_order_no`, `status` open \| in_progress \| closed, `work_type`, opened/closed dates |
| `MaintenanceExpense` | Expense header linked to WO / vehicle / project / district / party |
| `MaintenanceExpenseItem` | Line items |
| `MaintenanceWorkOrderAttachment` / `MaintenanceExpenseAttachment` | Media |
| `WorkspaceVehicleMaintenanceBaseline` | Per vehicle job_category interval (km and/or days) for alerts |

### Routes (`routes_expenses.py`)

- `/maintenance-work-orders` + add/edit/delete/close  
- `/maintenance-expenses` + add/edit/delete/view  
- Media download routes  
- `/maintenance-baseline-alert-report`  

### Permissions

- `maintenance_expense*` under `expenses`  
- Related accounting maintenance Form Control tab: `form_control_accounting_maintenance`  

### Flow

```
Open Work Order → Add expense lines + attachments → Close WO
        │
        ▼
Baseline alert report (due service by km/days)
```

---

## B. Ufone BPOCOPS maintenance (external)

| Piece | Detail |
|-------|--------|
| Model | `UfoneMaintenanceCache` |
| UI | `/ufone/maintenance` |
| Source | Live/remote BPOCOPS API via `ufone_service` / client |
| Permission | `ufone_reports` / `ufone_view` family |

This displays ambulance maintenance from Ufone — **not** the same records as internal work orders.

---

## Oil change adjacency

Oil expenses (`OilExpense*`) and expiry/oil reminder scheduler (`expiry_reminder_*`) complement maintenance for lubricant intervals. Oil-change alert report lives under tracker/ops reports.

---

## Change guidance

- Keep WO status machine intact.  
- Do not merge Ufone cache rows into `MaintenanceWorkOrder` without an explicit sync design.  
- Large template `maintenance_expense_form.html` — edit carefully.  
- Reuse R2 upload patterns from fuel/oil.
