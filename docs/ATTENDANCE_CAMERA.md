# GPS Attendance — Front Camera (Android)

## Architecture (do not duplicate logic elsewhere)

1. **Live preview** — `@capacitor-community/camera-preview` in `base.html`:
   - `fleetStartAttendancePreview()` → `toBack: true`, rect from `#cameraPreviewViewport`
   - `fleetSetAttendanceCameraChrome(true)` hides all `body` children except `#cameraModal` (stops driver-name bleed-through)
   - Native: `MainActivity` sets WebView background transparent

2. **Capture** — `fleetCaptureAttendancePreviewPhoto()` returns raw base64 (no rotation).

3. **Orientation** — once in `fleetStampAttendancePhoto()` via `fleetNormalizeSelfieOrientation(dataUrl, { fromCameraPreview: true })`:
   - **Only EXIF-based rotation** (3→180°, 6→90°, 8→270°). **Never** blind 180° when EXIF=1 (live preview is already upright).

4. **GPS stamp** — only on final canvas in `fleetStampAttendancePhoto()` (not on live preview).

5. **Retake** — `fleetRestartAttendancePreview()` → stop, 300ms, start (do not rely on `shown.bs.modal`).

## Version bump before release APK

Edit `android/version.properties` or run `npm run version:bump`, then rebuild signed APK.

## Deploy checklist

| Change | Needs Render deploy | Needs new APK |
|--------|---------------------|---------------|
| `base.html` / attendance templates | Yes | No (if app loads remote URL) |
| `MainActivity` / `version.properties` | No | Yes |
