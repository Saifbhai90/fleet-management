# Archived: In-App Custom Attendance Camera (Front CameraPreview)

**Status:** Parked for future built-in use. Production attendance now uses the **phone system camera** (`fleetTakeSystemCameraPhoto`).

**Last in-app implementation:** Git history around commits `39105a62`–`abbe2e69` (v1.9.7–1.9.9).

---

## What was built

| Piece | Location |
|--------|----------|
| Live preview (CameraPreview plugin) | `templates/base.html` — `fleetStartAttendancePreview`, `fleetCaptureAttendancePreviewPhoto`, `fleetRestartAttendancePreview` |
| WebView transparency | `android/.../MainActivity.java` — `scheduleWebViewTransparent()` |
| Camera chrome (hide app shell) | `fleetSetAttendanceCameraChrome`, CSS `html.fleet-attnd-camera-active` in `base.html` |
| CameraX fallback activity | `AttendanceCameraActivity.java`, `AttendanceFrontCameraPlugin.java` |
| Modal UI | `driver_attendance_checkin.html`, `driver_attendance_checkout.html` — `#cameraModal`, `#cameraPreviewViewport` |
| Orientation (EXIF) | `fleetNormalizeSelfieOrientation`, `fromCameraPreview` flag |
| GPS stamp (capture only) | `fleetStampAttendancePhoto` + `pktDrawReadableGpsStamp` |

---

## Re-enable in-app preview later

1. Set in `base.html`:
   ```javascript
   window.FLEET_ATTENDANCE_USE_INAPP_PREVIEW = true;
   ```
2. Restore `openNativeCheckinCamera()` / `openNativeCheckoutCamera()` to call `startCheckinCameraLive()` / `startCheckoutCameraLive()` (see git history).
3. Rebuild APK (CameraPreview + transparent WebView).

---

## Production path (current)

- `window.FLEET_ATTENDANCE_USE_INAPP_PREVIEW = false`
- `fleetTakeSystemCameraPhoto()` → Capacitor `Camera.getPhoto({ source: 'CAMERA', direction: 'FRONT', saveToGallery: false })`
- Same preview modal, GPS stamp, save/retry flow after capture.

See `docs/ATTENDANCE_CAMERA.md`.
