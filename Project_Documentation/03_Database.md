# 03 — Database

**ORM file:** `models.py` (~104 model classes)  
**Migrations:** `migrations/` — **84** Alembic versions  
**Engines:** PostgreSQL (production), SQLite (local)

---

## Association tables

| Table | Links |
|-------|-------|
| `project_district` | Project ↔ District |
| `employee_project` | Employee ↔ Project |
| `employee_district` | Employee ↔ District |
| `vehicle_district` | Vehicle ↔ District (if used) |
| `role_permissions` | Role ↔ Permission |

---

## Core organization & fleet

| Model | Table | Key fields / relationships |
|-------|-------|----------------------------|
| `Company` | `company` | → projects |
| `Project` | `project` | → company; M2M districts; vehicles, drivers, parking |
| `District` | `district` | M2M projects; referenced by expenses/tasks |
| `ParkingStation` | `parking_station` | → project; lat/lon for geofence; → vehicles |
| `Vehicle` | `vehicle` | `vehicle_no`, type/family, fuel, MPG target; FKs project/district/parking/driver |
| `Driver` | `driver` | CNIC/license, shift, status Active/Left; FKs project/vehicle/district; doc paths |
| `Employee` / `EmployeePost` | | Workforce + designations |
| `EmployeeDocument` | | Employee files |
| `DriverDocumentHistory` | | Driver doc update audit |

### Transfer / lifecycle history

| Model | Purpose |
|-------|---------|
| `ProjectTransfer` | Project company change history |
| `VehicleTransfer` | Vehicle project/district/parking moves |
| `DriverTransfer` | Driver reassignment history |
| `DriverStatusChange` | left / rejoin |
| `EmployeeAssignment` | Employee lifecycle assign/deassign/left/rejoin |

---

## Attendance

| Model | Notes |
|-------|-------|
| `DriverAttendance` | Unique `(driver_id, attendance_date, attendance_segment)`; status Present/Absent/Leave/Late/Half-Day/Off; GPS + photo paths; parking FK |
| `AttendanceSettings` | Geofence radius (default 150m), reminders |
| `AttendanceTimeControl` / `AttendanceTimeOverride` | Morning/Night windows; scope Vehicle > District > Project > Global |
| `LeaveRequest` | Pending → Approved/Rejected; approve can mark attendance |

---

## Tasks & ops

| Model | Role |
|-------|------|
| `VehicleDailyTask` | Manual daily: readings, task count, odometer photo |
| `EmergencyTaskRecord` | Uploaded emergency tasks |
| `VehicleMileageRecord` | Tracker mileage rows |
| `VehicleActivityRecord` | Activity trail points |
| `RedTask` | Justification + optional fine |
| `VehicleMoveWithoutTask` | Unauthorized movement / KM + fine |
| `UnexecutedTaskRecord` | Links emergency tasks + fines |
| `PenaltyRecord` | Aggregated penalties (`source_type` red_task / without_task) |

---

## Expenses & inventory

| Model | Role |
|-------|------|
| `Party`, `Product`, `ProductBalance` | Vendors / SKUs / stock |
| `FuelExpense` + `FuelExpenseAttachment` | Fueling with readings, MPG, async upload status |
| `OilExpense` + items + attachments | Oil/lube with limits |
| `MaintenanceWorkOrder` | open / in_progress / closed |
| `MaintenanceExpense` + items + attachments | Linked WO expenses |
| `WorkspaceVehicleReadingSetup` | Reading baselines |
| `WorkspaceVehicleMaintenanceBaseline` | Interval alerts (km/days) |

---

## Company finance

| Model | Role |
|-------|------|
| `Account` | Chart of accounts / wallets |
| `JournalEntry` / `JournalEntryLine` | Double-entry |
| `PaymentVoucher`, `ReceiptVoucher`, `BankEntry` | Voucher types |
| `EmployeeExpense` | Staff expenses |
| `VoucherSequence` | Numbering |
| `FundTransfer` + attachments/categories | Inter-account transfers |
| `BankAccountDirectory` | Bank directory |

---

## Workspace (per-employee books)

Isolated by `employee_id`: parties, products, accounts, journals, expenses, openings, fund transfers, slip OCR profiles/samples, month-close, fuel-oil close, MPG inputs, delete-cleanup jobs.

**Critical contract:** workspace stays isolated until month-close bridges into company journals.

---

## Payroll & books

| Model | Role |
|-------|------|
| `EmployeeSalaryConfig` | Pay rules |
| `MonthlyPayroll` | Run lifecycle (generate → finalize → pay) |
| `PhysicalBook` / `BookAssignment` | Physical logbook stock |

---

## Auth, audit, notifications, AI

| Model | Role |
|-------|------|
| `User`, `Role`, `Permission` | RBAC |
| `LoginLog`, `LoginAttempt`, `ActivityLog` | Auth/audit |
| `ClientActivityLog`, `ClientDiagnosticLog` | Client telemetry |
| `Notification`, `NotificationRead`, `Reminder` | In-app |
| `DeviceFCMToken`, `AppRelease`, `DeviceAppVersion` | Push + APK updates |
| `AIAssistantQueryLog`, `AIConversation`, `AIConversationMessage` | Gemini |
| `SystemSetting` | Key/value config |
| `FleetBackupJob`, `FleetBackupJobLock` | Backup jobs |

---

## GPS integrations

### PortalXS

| Model | Role |
|-------|------|
| `PortalXSAccount` | Fernet-encrypted credentials |
| `PortalXSVehicleMapping` | RegNo → Vehicle + last lat/lon/speed/status |
| `PortalXSAlertCache` | Cached alerts |

### TrackingWorld automation

`TrackerAutomationSettings`, `TrackerAutomationJob`

### Ufone BPOCOPS

| Model | Role |
|-------|------|
| `UfoneAccount` | Fernet-encrypted BPOCOPS login |
| `UfoneVehicleCache` | Live ambulance positions |
| `UfoneTaskCache` | Emergency tasks cache |
| `UfoneMaintenanceCache` | Maintenance cache |

---

## Org hierarchy (conceptual)

```
Company
  └── Project
        ├── District(s)  [M:N]
        ├── ParkingStation(s)  [lat/lon]
        ├── Vehicle(s)  ←→ Driver (assignment)
        └── Employee(s) [M:N projects/districts]
```

---

## Migrations practice

- Alembic under `migrations/versions/` (84 files — long chain; squash recommended periodically).  
- Render pre-deploy runs `scripts/render_migrate.sh`.  
- Startup may also run `create_all` + selective `ALTER TABLE` backfills (legacy compatibility).  

**Source of truth for schema:** `models.py` first; migrations must stay in sync for production Postgres.

---

## Soft patterns

- Many entities use status strings rather than enums.  
- Document/media paths often store **R2 public URLs**.  
- Expense attachments track `upload_status`: processing | success | error | partial.  
- Timezone-aware helpers via `pk_now` / `utils` Pakistan time.
