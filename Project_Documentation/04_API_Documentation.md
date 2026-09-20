# 04 — API Documentation

This project exposes **three API surfaces**:

1. **Session JSON/HTML APIs** under `/api/...` used by the web/Capacitor UI  
2. **JWT Mobile API** under `/api/v1/...` (`routes/api.py`)  
3. **Feature portals** with dedicated `/api/tracking/*`, `/api/ufone/*`, attendance GPS APIs, etc.

There is no OpenAPI/Swagger file in-repo. This document is the living inventory.

---

## A. JWT Mobile API (`api_bp`, prefix `/api/v1`)

**Auth:** `Authorization: Bearer <JWT>` (HS256, 24h, signed with `SECRET_KEY`)  
**Login rate limit:** 5 failed attempts / IP / 10 minutes (in-memory)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/login` | Body `{username, password}` → JWT |
| GET | `/api/v1/mobile-profile` | User/driver profile |
| GET | `/api/v1/dashboard/stats` | KPI summary |
| POST | `/api/v1/attendance/checkin` | Mobile check-in |
| POST | `/api/v1/attendance/checkout` | Mobile check-out |
| GET | `/api/v1/driver/profile` | Driver profile |
| GET | `/api/v1/notifications` | Notifications list |
| GET | `/api/v1/drivers` | Paginated drivers |
| GET | `/api/v1/drivers/<id>` | Driver detail |
| GET | `/api/v1/vehicles` | Paginated vehicles |
| POST | `/api/v1/fcm-token` | Register FCM token |
| DELETE | `/api/v1/fcm-token` | Remove FCM token |

Permissions checked via JWT payload `is_master` or role permissions in DB (`_mobile_has_permission`).

---

## B. Attendance GPS APIs (session)

Primary module: `routes/routes_attendance.py`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/parking-stations-with-coords` | Stations with lat/lon |
| GET | `/api/attendance/projects` | Cascading filters |
| GET | `/api/attendance/vehicles` | Cascading filters |
| GET | `/api/attendance/drivers` | Cascading filters |
| GET | `/api/attendance-time-window` | Allowed check windows |
| GET | `/api/attendance/gps-submit-status` | Async submit status |
| GET | `/api/attendance-has-gps-checkin` | Has GPS IN? |
| GET | `/api/attendance/latest-gps-media` | Latest selfie URLs |
| POST | `/api/attendance/gps-preflight` | Validate window/geofence before submit |
| POST | `/api/attendance/gps-checkin-submit` | Submit check-in + media |
| POST | `/api/attendance/gps-checkout-submit` | Submit check-out + media |

Page routes: `/driver-attendance/checkin`, `/checkout`, list, reports, leave, manual overrides.

---

## C. PortalXS tracking APIs

Module: `routes/routes_tracking.py`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/tracking/positions` | Cached live positions |
| POST | `/api/tracking/refresh` | Force refresh |
| GET | `/api/tracking/history` | History points |
| GET | `/api/tracking/vehicles/<acct_id>` | Portal vehicles |
| GET | `/api/tracking/internal-vehicles` | Internal vehicle list for linking |

UI: `/tracking`, `/tracking/history`, trips, fleet/mileage reports, alerts, settings.

---

## D. Ufone BPOCOPS APIs

Module: `routes/routes_ufone.py`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/ufone/positions` | Cached ambulance positions |
| POST | `/api/ufone/refresh` | Refresh |
| GET | `/api/ufone/dashboard_count` | Dashboard counters |
| GET | `/api/ufone/vehicles` | Vehicle list JSON |
| GET | `/api/ufone/districts` | Geo cascade |
| GET | `/api/ufone/tehsils/<district_code>` | Tehsils |
| GET | `/api/ufone/ucs/<tehsil_code>` | UCs |
| GET | `/api/ufone/tasks/dashboard` | Task dashboard |
| GET | `/api/ufone/task/<id>/comments` | Comments |
| POST | `/api/ufone/task/<id>/comment` | Add comment |
| POST | `/api/ufone/task/<id>/feedback` | Feedback |
| POST | `/api/ufone/task/<id>/complete` | Complete task |

UI pages under `/ufone/*` (map, track, history, ignition, distance, maintenance, patients, admin, settings).

---

## E. Finance / workspace AJAX (selected)

Registered in `app.py`:

| Path | Purpose |
|------|---------|
| `/api/employee-expense-descriptions` | Suggestions |
| `/api/ft-descriptions`, `/api/ft-categories` | Fund transfer helpers |
| `/api/bank-directory*` | Bank directory CRUD |
| `/api/workspace-party-names`, `/api/workspace-product-names` | Autocomplete |
| `/api/workspace-slip-profiles*` | Slip OCR profiles |
| `/api/workspace-slip-ocr-sample*` | OCR training samples |
| `/api/workspace-slip-server-ocr` | Server Tesseract fallback |
| `/api/workspace-transfer-ref-check` | Duplicate ref check |
| `/api/workspace-account-balance` | Balance lookup |
| `/api/payroll/attendance-preview` | Payroll attendance preview |
| `/api/payroll/driver-bulk-preview` | Bulk salary preview |

---

## F. AI assistant (`ai_bp`)

Gemini-backed “Master Mind” — conversation + read-oriented SQL assistant. Rate limited via env (`AI_RATE_*`). Some endpoints are CSRF-exempt with origin validation.

---

## G. Misc mobile / PWA / biometric

`routes/routes_misc.py` (examples):

- `/mobile-init` — Capacitor entry  
- Biometric enable/disable/login  
- FCM registration helpers  
- Blob upload (`/upload-blob`)  
- App logout  

---

## Auth notes for API consumers

| Client | Mechanism |
|--------|-----------|
| Browser / Capacitor WebView pages | Flask session + CSRF token on forms |
| Capacitor structured calls | Often session cookies in WebView; JWT used for `/api/v1` |
| CSRF-exempt JSON | Must still pass origin checks where implemented |

**Never** assume an endpoint is public — default-deny permission map in `auth_utils.py` plus allowlists for authenticated-but-generic endpoints.
