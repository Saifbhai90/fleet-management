# 10 — Attendance System

## Purpose

Record driver presence with **GPS proof** and **camera selfie**, support leave/late/half-day/off, and produce TRA / monthly / daily reports for payroll and ops.

---

## Models

### `DriverAttendance`
- Unique: `(driver_id, attendance_date, attendance_segment)`
- Status: Present | Absent | Leave | Late | Half-Day | Off
- Times: `check_in`, `check_out`, `check_out_date`
- GPS: check-in/out lat/lon
- Media: `check_in_photo_path`, `check_out_photo_path` (R2 URLs)
- Context: `project_id`, `parking_station_id`, etc.

### Settings & windows
- `AttendanceSettings` — geofence enabled/radius, reminder minutes
- `AttendanceTimeControl` / `AttendanceTimeOverride` — Morning/Night windows  
  **Scope priority:** Vehicle → District → Project → Global

### `LeaveRequest`
Pending → Approved / Rejected; approval can mark attendance Leave (`routes_workforce.py`).

---

## Routes (pages)

| Path | Role |
|------|------|
| `/driver-attendance/checkin` | GPS + camera IN |
| `/driver-attendance/checkout` | GPS + camera OUT |
| `/driver-attendance/` | List |
| `/driver-attendance/mark` | Leave/Late/Half-Day/Off |
| `/driver-attendance/bulk-off` | Bulk status |
| `/driver-attendance/pending` | Missing check-IN |
| `/driver-attendance/missing-checkout` | Missing check-OUT |
| `/driver-attendance/manual-checkin` / `manual-checkout` | Supervisor override |
| `/driver-attendance/report` | Monthly |
| `/driver-attendance/daily-report` | Day-wise |
| `/driver-attendance/tra-report` | TRA sheet |
| `/driver-attendance/media-gallery` | Photo gallery + ZIP |
| `/leave-requests*` | Leave workflow |

GPS JSON APIs documented in `04_API_Documentation.md`.

---

## Check-in algorithm (conceptual)

1. Auth + permission `driver_attendance_checkin`.  
2. Resolve driver/vehicle/parking for date + segment.  
3. Preflight: within time window? within geofence? already checked in?  
4. Accept coordinates + photo blob.  
5. Upload image to R2 folder `attendance/`.  
6. Upsert `DriverAttendance` Present with GPS + photo URL.  
7. Client may retry pending uploads if network fails.

Checkout mirrors this and requires prior check-in (enforced by APIs/pages).

---

## Permissions (granular)

Section `attendance`. Important codes include:

- `driver_attendance_checkin` / `checkout`
- `driver_attendance_pending` / `missing_checkout`
- `driver_attendance_mark` / `bulk_off`
- `driver_attendance_list` (+ manual edit/delete/checkout variants)
- Report permissions as defined in `permissions_config.py`

Form Control tab `attendance` gates time-window settings.

---

## Background reminders

`attendance_reminder_scheduler` (~1 min) + `attendance_reminder_service` notify drivers/supervisors about missing IN/OUT via in-app/FCM.

---

## Mobile specifics

- Capacitor camera preview preferred on Android.  
- Offline-ish pending upload helper: `gps_attendance_pending_upload.js`.  
- JWT alternatives: `/api/v1/attendance/checkin|checkout`.  

---

## Integration points

| System | Link |
|--------|------|
| Payroll | Attendance used in salary calc / preview APIs |
| Parking stations | Geofence anchors |
| R2 | Selfie storage |
| Notifications | Reminders |
| Leave | Status synchronization |

---

## Change caution

Attendance is high-risk for payroll disputes. Preserve:

- Unique constraint semantics (date + segment)  
- Geofence & window rules  
- Manual override permission separation  
- Media URL compatibility
