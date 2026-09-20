# 05 — Business Flow

## Organizational flow

1. Create **Company** → **Project**.  
2. Attach **Districts** to projects.  
3. Create **Parking Stations** (with GPS coords for attendance).  
4. Create **Vehicles** and **Drivers** / **Employees**.  
5. **Assign**: vehicle→district, vehicle→parking, driver→vehicle.  
6. Later **Transfer** entities between projects/districts (history tables).  

---

## Daily operations loop

```
Morning shift window opens
        │
        ▼
Driver GPS Check-IN (camera + geofence at parking)
        │
        ▼
Tasks executed (emergency + routine)
  • Workbook / tracker uploads (ops team)
  • Daily task entry (odometer + task count)
        │
        ▼
Fuel / oil / maintenance recorded as needed
        │
        ▼
Driver GPS Check-OUT
        │
        ▼
Ops review: Red Task / Without Task / Unexecuted → Penalties
        │
        ▼
Reports (TRA attendance, logbook, tracker difference, mileage)
```

---

## Attendance flow (detail)

1. User opens Check In (permission `driver_attendance_checkin`).  
2. Select project / vehicle / driver / parking.  
3. **Preflight** (`/api/attendance/gps-preflight`): time window + geofence.  
4. Capture selfie (camera) + GPS coordinates.  
5. Submit → R2 upload (`attendance/`) → `DriverAttendance` row.  
6. Reminders via FCM/in-app if missing IN/OUT (`attendance_reminder_scheduler`).  
7. Check-out mirrors the path.  
8. Leave requests: create → review → may auto-mark Leave status.  
9. Manual IN/OUT and bulk Off available for supervisors (separate permissions).

Segments: typically **Morning / Night** (`attendance_segment`).

---

## Task / logbook flow

1. Upload tracker workbooks: emergency, mileage, activity, core.  
2. Create or complete **VehicleDailyTask** entries.  
3. Pending list highlights missing daily entries.  
4. Compare against tracker: difference / unauthorized movement / start delay / turnaround reports.  
5. Raise **Red Task** or **Move Without Task**; optionally create **PenaltyRecord**.  
6. Produce logbook covers / PDF exports.

---

## Fuel expense flow

1. Open fuel form (often large client-side UX with offline helpers).  
2. Select district/project/vehicle/employee/party.  
3. Enter readings → KM and MPG computed.  
4. Attach slips; async upload workers push to R2 (`upload_status`).  
5. Optional market rate hints (`fuel_market_scan_scheduler`).  
6. Duplicate/last-reading APIs prevent bad consecutive readings.  
7. Workspace MPG reports consume fuel + reading baselines.

---

## Maintenance flow

1. Open **Maintenance Work Order** (`open`).  
2. Add **Maintenance Expense** lines/items + attachments.  
3. Close WO (`closed`) with dates.  
4. Baseline alert report uses `WorkspaceVehicleMaintenanceBaseline` (km/day intervals).  
5. Separate: Ufone `/ufone/maintenance` shows external BPOCOPS maintenance cache (not the same as internal WO).

---

## Finance / workspace month-close

```
Workspace daily journals/expenses (employee-scoped)
        │
        ▼
Workspace month close / fuel-oil close
        │
        ▼
Bridge entry into company Chart of Accounts
        │
        ▼
Company ledger / balance sheet / wallet dashboard
```

Freeze utilities (`freeze_utils.py` + Form Control freeze tab) can block writes before a cutoff date.

---

## Payroll flow

1. Configure `EmployeeSalaryConfig` (employee or driver).  
2. Generate `MonthlyPayroll` (single or bulk).  
3. Recalc attendance-based components.  
4. Finalize → Pay → Payslip.  
5. Revert/delete with care (permissions).

---

## GPS portal flows

### PortalXS
Settings → add account → test/sync → map RegNo to Vehicle → start polling (~30s) → live map & reports.

### Ufone
Settings → add BPOCOPS account → test → start polling → dashboard/map/tasks/patients/admin actions.

---

## Auth session flow (web)

1. `/login` with CNIC-style username.  
2. Session stores `user_id`, expanded `permissions`, scope lists (`allowed_projects`/`districts`/`vehicles`/`shifts`), flags `is_master`/`is_admin`.  
3. Master role expands to all permission codes.  
4. Every request: `check_auth` / endpoint permission map (default deny with allowlist).  
5. Mobile: biometric re-auth on foreground; optional JWT for `/api/v1`.
