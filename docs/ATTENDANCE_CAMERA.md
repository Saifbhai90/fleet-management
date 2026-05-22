# GPS Attendance — Camera (Production)

## Current behaviour (Mark Attendance / Check-out)

1. User taps **Mark Attendance** (or check-out equivalent).
2. **Phone system camera** opens (Capacitor Camera plugin).
   - `source: 'CAMERA'` — gallery picker **not** offered.
   - `direction: 'FRONT'` — front / selfie camera.
   - `saveToGallery: false` — photo **not** saved to gallery.
3. After capture → `fleetStampAttendancePhoto()` adds GPS stamp on canvas.
4. In-app **Preview** modal → Save or **Dobara lein** (re-opens system camera).

Implementation: `window.fleetTakeSystemCameraPhoto()` in `templates/base.html` (uses `FleetBridge.takeSelfie` when available).

## GPS stamp size

- Odometer photos: `ODOM_STAMP_SCALE = 2.5` in `task_report_odometer_upload.html`.
- Attendance: `FLEET_ATTENDANCE_STAMP_SCALE = 5.5`, full-width compact bottom stamp (max 4 rows: title, date/time, vehicle·driver, lat·accuracy).
- While preview modal is open: Tom Select dropdowns are closed/hidden (`fleetSetAttendanceModalOpen`).

## Archived custom in-app camera

Future built-in live preview work is documented in:

`docs/archive/CUSTOM_ATTENDANCE_CAMERA_ARCHIVE.md`

Toggle: `window.FLEET_ATTENDANCE_USE_INAPP_PREVIEW = true` (default **false**).

## Deploy vs APK

| Change | Render deploy | New APK |
|--------|---------------|---------|
| `base.html`, check-in/out templates | Yes | No (remote URL) |
| `MainActivity` / CameraPreview native | Only if re-enabling in-app preview | Yes |
