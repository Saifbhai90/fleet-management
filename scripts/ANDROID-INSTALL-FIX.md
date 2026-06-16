# Android Studio install failed (UNKNOWN / 16 KB) — quick fix

## Step 1 — Phone se purani app hatao (sab se common fix)
Play Store ya pehle wali release app **signature alag** hoti hai, is liye debug install fail ho jata hai.

1. Phone: **Settings → Apps → Fleet Manager → Uninstall**
2. Ya long-press app icon → Uninstall

## Step 2 — Android Studio mein Debug build chalao
1. **Build → Select Build Variant** → module **app** → **debug** (release nahi)
2. **Build → Clean Project**
3. **Build → Rebuild Project**
4. Phone USB se connect, USB debugging ON
5. **Run ▶** dubara

## Step 3 — 16 KB warning
`android/app/build.gradle` mein `useLegacyPackaging = true` add ho chuka hai — native libraries compress hongi, 16 KB devices par install ho sakta hai.

Agar phir bhi fail ho:
- OPPO: **Developer options → Install via USB** enable karein
- Phone par **enough storage** check karein
- Android Studio: **File → Invalidate Caches → Restart**

## LAN test (local server)
Laptop par server chalna chahiye:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-lan-for-mobile.ps1
```
App URL: `http://192.168.18.36:5050/mobile-init`
