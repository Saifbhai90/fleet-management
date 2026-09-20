# 20 — Personal (Crescent Tracker) Integration

## Overview

Sidebar section **"Personal"** (Report Centre ke neeche) — **Crescent Tracker** Android app
(`com.cresent.app` v3.0.6) ke asli backend API ko directly integrate karta hai: professional
live map, animated history playback, trips, alarms, notifications aur full telemetry.

## Pro UI (v3 upgrade)

- **Live Map:** **Google map styles (default: Google Street)** + Satellite/Hybrid/Terrain/OSM/Esri,
  **asli Crescent app vehicle icons** (status × type: moving/idle/parked/offline × car/truck/bus/bike/atm,
  APK se extract kiye — `static/img/personal/vehicles/`), moving vehicles DirAngle par rotate hoti hain,
  smooth marker movement, follow mode, fullscreen, freshness countdown, rich telemetry popups
  (batteries/GSM/GPS/fence + Google Maps share link), searchable vehicle list.
- **History Playback:** speed-colored route, stop markers (>=5 min parked/idle), animated replay
  (play/pause, 1×–16×, timeline scrubber), moving-time stat, prev/next day, click-to-map table.
- **Trips:** derived trip cards + CSV.
- **Dashboard:** gradient KPI cards (click-to-filter), vehicle cards with quick actions.
- **Vehicle Detail:** full telemetry (battery bars, GSM, GPS, fence, device status) 30s auto-refresh,
  **Engine Kill/Release control**, collapsible raw JSON.

## Engine Kill / Release (Immobilizer)

- Endpoint: `POST /api/personal/vehicle/<id>/command` `{action: engine_off|engine_on, confirm: "<REGNO>"}`
- **Safety gates:** (1) Settings mein `commands_enabled` toggle (default OFF), (2) speed < 5 km/h
  enforce, (3) typed confirmation (reg no), (4) har command CrescentApiLog mein audited.
- Toggle OFF hone par har request **DRY-RUN** hoti hai — exact URL API Log mein record hota hai,
  kuch bheja nahi jata (wire-format verification ka safe tareeqa).
- Wire format (app binary se): `GET Command/send?uname=&vid=<vehicleId>&id=<Device#>&cmd=ImoblizerOn|ImoblizerOff`
  + Bearer token. Primary base teletixapp, 404 par legacy trackgf cluster automatic fallback.
  **Note:** vendor wire format undocumented hai — pehli asli command ke baad API Log se verify/tune karein.

## Reverse-Engineered API (REAL protocol — live app se MITM capture kiya gaya)

| Item | Value |
|---|---|
| **API Base** | `https://teletixapp.crescenttrack.com:8888/api/` (HTTPS on port 8888) |
| **DNS** | teletixapp → 203.128.254.253 / 202.70.150.187 (dono nodes active) |
| **Login** | `GET user/verify?uname=<u>&pwd=<p>` |
| **Login response** | JSON string of hex bytes = **UTF-16LE** text, e.g. `30003100...` → `01,2,10303,NA` |
| **Token** | decoded string session-scoped hai; **app RAW HEX form hi bhejti hai** (Bearer + `t=` param dono mein) |
| **Auth header** | `Authorization: Bearer <hex-token>` |
| **Fleet live** | `GET live/status?a=1&t=<token>` → saari vehicles, full status |
| **Single vehicle** | `GET live/status?c=<ClusterId>&p=<ProcId>&id=<Device#>` |
| **History points** | `GET tripreplay/getall?cmpId=<cmp_id>&type=v&id=<vehicleId>&dateTime1=<YYYY-MM-DD HH:MM:SS>&dateTime2=<...>` |
| **Change check** | `GET user/isanychange?uname=<u>` |
| **Push register** | `POST https://crescent-api.progatix.com/token/saveFcmToken` `{fcmToken, userName, vendorName: "teletix"}` |
| **Notifications** | `GET https://crescent-api.progatix.com/notification/notificationList` header `fcmToken: <registered>` |

### live/status record fields (important keys)
`Device#`, `VRN`, `AssetType`, `GroupName`, `Point` ("lat,lon"), `Status` (Moving/Idle/Parked),
`Speed`, `GpsDateTime`, `RecDateTime`, `Location`, `Fence`, `ACC` (On/Off), `Online`, `Mileage`,
`DirAngle`, `GsmSignal`, `GpsSatelite`, `ExtBatV`, `IntBatPercent`, `Driver`, `vehicleId`,
`cmp_id`, `ClusterId`, `ProcId`, `DeviceStatus`.

### tripreplay point fields
`SrNo`, `GpsDateTime`, `ACC`, `Speed`, `Status`, `Alarm` (e.g. "Out:Event" = geofence out),
`Location`, `Dir`, `Latitude`, `Longitude`.

### Legacy / dead endpoints (old APK strings — current app in-use nahi karta)
`trackgf.crescenttrack.com:8888` (plain HTTP) par `POST /api/Token` OWIN endpoint **broken hai**
(har request par NullReferenceException 500). `DashBoard/List`, `Reports/AssetTrip`,
`HistoryReplay/View` waghera isi par the — ab relevant nahi.

## Files

| File | Purpose |
|---|---|
| `services/crescent_service.py` | Real-protocol client: login/hex-token, live fleet, history, trips derivation, notifications (FCM identity), API log, lazy schema self-heal |
| `routes/routes_crescent.py` | Pages (`/personal/*`) + JSON APIs (`/api/personal/*`) |
| `models.py` | `CrescentSettings` (+fcm_token), `CrescentVehicleCache` (+cmp_id/cluster_id/proc_id/vendor_vehicle_id), `CrescentApiLog` |
| `templates/personal/*.html` | dashboard, live, vehicles, vehicle_detail, history, trips, alarms, notifications, settings |
| `static/js/personal_*.js`, `static/css/personal.css` | Frontend (vendored Leaflet + Chart.js reuse) |
| `services/auth_utils.py` | `PERMISSION_PERSONAL` + endpoint permission map |
| `services/permissions_config.py` | Permission tree / PAGE_VISIBLE / expansions |
| `templates/base.html` | Sidebar item (Report Centre ke neeche) + mobile drawer link |

## Permissions

`personal` (full), granular: `personal_view`, `personal_history`, `personal_reports`,
`personal_settings`. Master role ko sab automatically; doosri roles ko Administration → Roles
se assign karna hoga.

## Schema self-heal

`LOCAL_FAST_BOOT=1` (run-local.bat) startup ka `db.create_all()` skip karta hai, is liye
`routes_crescent.py` ka `_crescent_ensure_tables` hook pehli `/personal` request par sirf apni
tables + extra columns (`ALTER TABLE ... ADD COLUMN`) create karta hai (idempotent).

## Setup (one time)

1. **Personal → Settings** kholein.
2. Username **wahi likhein jo Crescent app login par use hota hai** (prefix ke saath, e.g.
   `ct_saif617`) aur password enter karein → **Save**.
3. **Test Connection** — Login, live/status, isanychange, notifications ke checks green aane
   chahiye.
4. **Refresh** — saari vehicles cache mein aa jayengi (live/status se).

## Features → endpoints mapping

| Personal page | Vendor endpoint |
|---|---|
| Dashboard + Live Map + Vehicles | `live/status?a=1&t=` |
| Vehicle Detail | cache + raw record |
| History (playback) | `tripreplay/getall` |
| Trips | `tripreplay/getall` → movement-burst segmentation (haversine distance) |
| Alarms | `tripreplay/getall` → points jahan `Alarm` non-empty |
| Notifications | Progatix `notification/notificationList` (fcmToken header) — **best-effort** |
| Settings | credentials + Test Connection + API Log |

## Known Limitations

1. **Notifications best-effort:** vendor sirf registered (real FCM) device token accept karta hai;
   hamara synthetic token 401 deta hai. Same alert data **Alarms page** se milta hai (history
   points ka `Alarm` field).
2. **Unofficial API** — vendor kabhi change/block kar sakta hai. Official API access ki request
   bhi consider ki jaye (Crescent / info@crescenttrack.com).
3. **TLS:** vendor ka certificate chain non-standard hai — client `verify=False` use karta hai
   (warning suppressed). In-app data plain readable hai unke server side par.
4. **Token expiry:** session token har login par naya banta hai (counter badhta hai); service
   12 ghante baad / 401 par auto re-login karta hai.
5. **Immobilizer (Engine Kill/Release)** vendor API par mojoom hai (app use karta hai) lekin
   safety wajah se hamari UI mein intentionally expose nahi kiya gaya.
