# Fleet Manager — APK install (drivers / IT)

## Parse error: "There was a problem while parsing the package"

Usually **not** Android Studio vs file — the APK file on the phone is **corrupt or unsigned**.

### Do NOT use WhatsApp to send APK
WhatsApp often **breaks** `.apk` files. Use one of these:

1. **USB cable** — copy file to `Download` folder, open Files app, tap APK
2. **Google Drive / OneDrive** — upload original file, download on phone (not forwarded in chat)
3. **adb** (PC): `scripts\install-apk.ps1` with USB debugging on

### Which APK to install

| File | Status |
|------|--------|
| `fleet-manager-1.9.8.apk` | Signed (new release key) — **latest**; camera preview + orientation + retake fix |
| `fleet-manager-1.9.7.apk` | Previous release |
| `fleet-manager-1.9.6.apk` | Signed (same key) — OK for in-app update from 1.9.6 |
| `fleet-manager-1.9.5.apk` | Old debug key — do not use for updates |
| `fleet-manager-1.7.0.apk` | Signed (old key) — only if you need old build |
| `fleet-manager-1.9.3.apk` / `1.9.4.apk` | **Removed** — unsigned, install fails |

Build output: `android\app\build\outputs\apk\release\fleet-manager-1.9.8.apk`

Version file (edit before each release): `android\version.properties`

### If install still fails

1. Delete any `fleet-manager-*.apk` from Downloads (failed copies)
2. Uninstall old Fleet Manager app (Settings → Apps)
3. Install again from USB/Drive copy of **1.9.8**
4. If message is **"App not installed"** (not parse error): old app used a different signing key — uninstall first, then install 1.9.8

### Android Studio "Run"

Same as installing a **signed debug** build. It does not fix a corrupt APK sent over WhatsApp.
