# 08 — Mobile App

## Platform

| Item | Value |
|------|-------|
| Framework | Capacitor 6 |
| App ID | `com.fleetmanager.app` |
| App name | Fleet Manager |
| Version scripts | `package.json` → `scripts/bump-android-version.ps1` |
| Native project | `android/` |
| WebDir | `www/` (shell; live content is remote) |

## Server loading model

`capacitor.config.json`:

- `server.url` → production Render host  
- `startPath` → `/mobile-init`  
- `appendUserAgent` → `FleetCapacitor`  
- HTTPS only (`cleartext: false`)

The APK is essentially a **native shell around the Flask web app**, plus plugins.

---

## Capacitor plugins used

| Plugin | Use |
|--------|-----|
| Camera / CameraPreview | Attendance selfies |
| Geolocation | Attendance GPS |
| Filesystem / File opener / Share | Media & exports |
| PushNotifications | FCM |
| SplashScreen / StatusBar | Native chrome |
| BiometricAuth / Native Biometric | Lock on resume |
| App / Device | Lifecycle & device info |

---

## Mobile-specific backend pieces

| Piece | Location |
|-------|----------|
| `/mobile-init` | `routes_misc.py` |
| Biometric login/enable/disable | `routes_misc.py` |
| JWT API | `routes/api.py` `/api/v1` |
| FCM token models/API | `DeviceFCMToken`, push services |
| App releases / forced update | `AppRelease`, `DeviceAppVersion`, dashboard routes |
| GPS attendance pending upload JS | `gps_attendance_pending_upload.js` |
| Mobile CSS | `mobile_*.css`, `legacy_android_gpu.*` |
| FleetBridge / mobile JS | `static/js/core/fleet_mobile.js` |

---

## Auth UX on mobile

1. Normal web login inside WebView (session cookie).  
2. Biometric overlay re-authenticates on app foreground.  
3. Optional JWT endpoints for structured API clients.  
4. Session inactivity handled partly by JS timer; server permanent session rolls (~30 days config).

---

## Attendance on mobile

Critical path for field drivers:

1. Permissions: location + camera.  
2. Check-in page uses live GPS + camera preview.  
3. Preflight validates geofence/time window.  
4. Media may queue/retry if network weak (`gps_attendance_pending_upload.js`).  
5. Photos stored on R2 as WebP.

See also `docs/ATTENDANCE_CAMERA.md`, `docs/README_CAPACITOR.md`, `docs/APK_INSTALL.md`.

---

## Push notifications

- Firebase Admin SDK (`firebase-admin`) with service account JSON or `FIREBASE_SERVICE_ACCOUNT_JSON`.  
- Tokens stored in `DeviceFCMToken`.  
- Used for attendance reminders, expiry alerts, general notifications.

---

## Build / release notes

- Android signing assets under `config/android-signing/` (sensitive).  
- Prior audit: `minifyEnabled false` on release — security/performance concern.  
- Scripts: `install-apk.ps1`, `point-capacitor-to-lan.ps1`, version bump PowerShell.  
- Companion: `fleet-desktop/` Electron wrapper for desktop shell use.

---

## When changing mobile behavior

1. Prefer fixing shared web templates/JS so Capacitor inherits changes.  
2. Test Android WebView quirks (GPU CSS, safe areas, keyboard).  
3. Keep `allowNavigation` hosts in sync with deploy URL.  
4. Do not commit secrets (`google-services.json` may exist — treat carefully).
