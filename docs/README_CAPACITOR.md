# Fleet Manager — Native Mobile App (Capacitor + WebView)

## Architecture Overview

```
Fleet Manager Web App (Flask on Render)
         │
         │  HTTPS (JWT Auth)
         ▼
   Capacitor WebView
   ┌──────────────────────────────┐
   │  Android / iOS Native Shell  │
   │  ├── GPS (Geolocation API)   │
   │  ├── Camera (Front Selfie)   │
   │  ├── Push Notifications      │
   │  └── Splash Screen / Icon    │
   └──────────────────────────────┘
```

The app is a **WebView wrapper** around your live Render URL. No code duplication — the same Flask app serves both web browsers and the mobile app. The Capacitor bridge gives native GPS, Camera, and Push access.

---

## Prerequisites

Install these on your PC **once**:

| Tool | Download |
|------|----------|
| Node.js ≥ 18 | https://nodejs.org |
| Android Studio | https://developer.android.com/studio |
| Java JDK 17 | Bundled with Android Studio |

---

## Step 1 — Configure Your Server URL

Edit `capacitor.config.json` and replace the server URL:

```json
"server": {
  "url": "https://YOUR-ACTUAL-RENDER-URL.onrender.com"
}
```

---

## Step 2 — Install Capacitor Dependencies

Open PowerShell in `d:\company_management\` and run:

```powershell
npm install
```

This installs Capacitor core, Camera, Geolocation, Push Notifications, Splash Screen, and Status Bar plugins.

---

## Step 3 — Initialize Capacitor (first time only)

```powershell
npx cap init "Fleet Manager" "com.fleetmanager.app" --web-dir "."
```

---

## Step 4 — Add Android Platform

```powershell
npx cap add android
```

This creates the `android/` folder with a full Android Studio project.

---

## Step 5 — Sync Web Assets

After any change to `capacitor.config.json`:

```powershell
npx cap sync android
```

---

## Step 6 — Open in Android Studio

```powershell
npx cap open android
```

Android Studio will open. Wait for Gradle sync to complete (~2-3 minutes first time).

---

## Step 7 — Configure Android Permissions

Android Studio will auto-apply these from `capacitor.config.json`, but verify in `android/app/src/main/AndroidManifest.xml`:

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.CAMERA" />
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />
<uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />
<uses-permission android:name="android.permission.VIBRATE" />
```

---

## Step 8 — Add App Icons & Splash Screen

Place your icon files in `android/app/src/main/res/`:

| File | Size | Folder |
|------|------|--------|
| `ic_launcher.png` | 48×48 | `mipmap-mdpi` |
| `ic_launcher.png` | 72×72 | `mipmap-hdpi` |
| `ic_launcher.png` | 96×96 | `mipmap-xhdpi` |
| `ic_launcher.png` | 144×144 | `mipmap-xxhdpi` |
| `ic_launcher.png` | 192×192 | `mipmap-xxxhdpi` |
| `splash.png` | 2732×2732 | `drawable` |

Use https://www.appicon.co to generate all sizes from one 1024×1024 PNG.

---

## Step 9 — Build Debug APK

In Android Studio:
1. **Build** → **Build Bundle(s) / APK(s)** → **Build APK(s)**
2. APK location: `android/app/build/outputs/apk/debug/app-debug.apk`
3. Transfer to phone via USB or WhatsApp/email and install

---

## Step 10 — Build Release APK (for distribution)

```powershell
# In Android Studio: Build → Generate Signed Bundle / APK
# Or via CLI:
cd android
./gradlew assembleRelease
```

Output: `android/app/build/outputs/apk/release/app-release-unsigned.apk`

Sign with your keystore before distributing.

---

## API Endpoints Reference (JWT)

All endpoints require `Authorization: Bearer <token>` header except login.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/login` | Login → returns JWT token |
| `GET` | `/api/v1/me` | Current user profile |
| `GET` | `/api/v1/driver/profile` | Driver profile + today's attendance |
| `GET` | `/api/v1/dashboard/stats` | KPI summary (drivers, vehicles, attendance) |
| `POST` | `/api/v1/attendance/checkin` | Check-in with GPS + selfie base64 |
| `POST` | `/api/v1/attendance/checkout` | Check-out with GPS + selfie base64 |
| `GET` | `/api/v1/drivers` | Paginated driver list |
| `GET` | `/api/v1/drivers/<id>` | Single driver detail |
| `GET` | `/api/v1/vehicles` | Paginated vehicle list |
| `GET` | `/api/v1/notifications` | User notifications |

### Example: Login

```bash
curl -X POST https://your-app.onrender.com/api/v1/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "yourpassword"}'
```

Response:
```json
{
  "success": true,
  "data": {
    "token": "eyJ...",
    "user_id": 1,
    "name": "Admin",
    "expires_in_hours": 24
  }
}
```

### Example: Attendance Check-in with GPS + Selfie

```javascript
// Using FleetBridge (built into base.html)
async function doCheckin(driverId) {
    const [gps, photo] = await Promise.all([
        window.FleetBridge.getGPS(),
        window.FleetBridge.takeSelfie()
    ]);

    const response = await fetch('/api/v1/attendance/checkin', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + localStorage.getItem('jwt_token')
        },
        body: JSON.stringify({
            driver_id: driverId,
            latitude: gps.latitude,
            longitude: gps.longitude,
            photo_base64: photo
        })
    });

    const result = await response.json();
    if (result.success) alert('Checked in: ' + result.data.time);
}
```

---

## iOS Setup (Future)

```powershell
npx cap add ios
npx cap open ios
# Requires macOS + Xcode
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `CLEARTEXT not permitted` | Set `androidScheme: "https"` in config (already set) |
| GPS not working | Check `ACCESS_FINE_LOCATION` permission in manifest |
| Camera black screen | Add `CAMERA` permission, test on real device not emulator |
| App shows blank screen | Check the `server.url` in `capacitor.config.json` |
| Gradle sync fails | File → Invalidate Caches → Restart in Android Studio |
