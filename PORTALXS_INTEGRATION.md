# PortalXS Fleet Tracking Integration — Complete Guide

## What's Been Built

The PortalXS Fleet Tracking portal has been **fully integrated** into your existing `company_management` Flask application. No separate app needed — it runs inside your existing software.

### New Files Created

| File | Purpose |
|------|---------|
| `services/portalxs_crypto.py` | Triple DES encryption (cracked, used by SOAP client) |
| `services/portalxs_soap_client.py` | Direct SOAP API client (no browser/captcha) |
| `services/portalxs_service.py` | Service layer: caching, background polling, DB sync |
| `routes/routes_tracking.py` | All tracking portal routes (dashboard, history, trips, etc.) |
| `templates/tracking/dashboard.html` | Live map with 48 vehicles, 30s auto-refresh |
| `templates/tracking/vehicle_detail.html` | Vehicle detail with mini-map + today's trips |
| `templates/tracking/history.html` | Route playback with play/pause/speed controls |
| `templates/tracking/trips.html` | Trips table with CSV export |
| `templates/tracking/fleet_report.html` | Driver ranking + Chart.js bar charts |
| `templates/tracking/trends.html` | Daily mileage/alerts line charts |
| `templates/tracking/alerts.html` | Recent alerts list |
| `templates/tracking/settings.html` | Account management + vehicle linking |

### Modified Files

| File | Change |
|------|--------|
| `models.py` | Added `PortalXSAccount`, `PortalXSVehicleMapping`, `PortalXSAlertCache` models |
| `requirements.txt` | Added `pycryptodome==3.21.0` |
| `app.py` | Registered `routes_tracking` module |
| `services/hub_registry.py` | Added `fleet-tracking` hub with all endpoints |
| `services/auth_utils.py` | Added `tracking_` and `api_tracking_` to allowed prefixes |
| `templates/partials/sidebar_hub_links.html` | Added Fleet Tracking sidebar link |

---

## How to Use

### 1. Install Dependencies
```bash
pip install pycryptodome
```

### 2. Start the App
```bash
python app.py
```

### 3. Configure PortalXS Account
- Go to **Settings → Fleet Tracking** (or `/tracking/settings`)
- Click **Add Account**
- Pre-filled with default credentials:
  - Username: `ccrmuzaffergarh`
  - Password: `Muzaffergarh123`
- Click **Create Account**
- Click **Test** to verify connection
- Click **Sync** to pull all 48 vehicles

### 4. Use the Dashboard
- Go to **Fleet Tracking** in the sidebar (or `/tracking`)
- All 48 vehicles appear on the live map
- Auto-refreshes every 30 seconds
- Click any vehicle for details
- Use sidebar to search/filter by status (Moving/Stopped/Idle)

### 5. History Playback
- Go to **Route History** (or `/tracking/history`)
- Select a vehicle and date range
- Click **Fetch History**
- Use Play/Pause/Speed controls for route playback
- Export to CSV

### 6. Reports
- **Trips**: `/tracking/trips` — trip table with CSV export
- **Fleet Report**: `/tracking/fleet-report` — driver ranking with charts
- **Trends**: `/tracking/trends` — daily mileage/alerts charts
- **Alerts**: `/tracking/alerts` — recent fleet alerts

---

## Additional Ways to Leverage Tracking in Your Software

### 1. **GPS Attendance Verification**
**Current**: Drivers check in/out with GPS coordinates.
**Enhancement**: Cross-reference driver's GPS check-in location with their assigned vehicle's PortalXS position. If the driver checks in but the vehicle is far away, flag as suspicious.

### 2. **Automated Mileage Logging**
**Current**: Manual odometer readings in Task Reports.
**Enhancement**: Auto-populate vehicle mileage from PortalXS `TotalMileage` field daily. Compare with manually entered odometer readings to detect discrepancies (the existing "Tracker Difference Report" can now use real data instead of Playwright-scraped XLSX files).

### 3. **Fuel Expense Validation**
**Current**: Fuel expenses entered manually.
**Enhancement**: When a fuel expense is submitted, check the vehicle's PortalXS trip data for the same day. If the vehicle didn't move that day, flag the fuel entry as suspicious (potential fuel theft).

### 4. **Unauthorized Movement Alerts**
**Current**: "Unauthorized Movement Report" exists but relies on manual data.
**Enhancement**: Use PortalXS ignition status + trip data to automatically detect vehicles moving outside working hours or without an assigned driver. Send push notifications via Firebase FCM.

### 5. **Geofence Compliance**
**Current**: Vehicles are assigned to districts/parking stations.
**Enhancement**: Create geofences around assigned parking stations. When a vehicle leaves its assigned district without a transfer record, trigger an alert. This integrates with your existing transfer management system.

### 6. **Driver Performance Scoring**
**Current**: Driver performance is tracked through task reports and attendance.
**Enhancement**: Use PortalXS `VehicleScore`, `MaxSpeed`, and alert data to build a comprehensive driver performance dashboard. Combine with existing attendance, task completion, and fuel efficiency data for a 360-degree driver score.

### 7. **Predictive Maintenance**
**Current**: Oil change alerts based on mileage thresholds.
**Enhancement**: Use PortalXS daily mileage trends to predict when the next oil change/maintenance is due. Send automated reminders via the existing notification system.

### 8. **Real-time Dashboard Widgets**
**Current**: Dashboard shows static stats.
**Enhancement**: Add a live fleet status widget to the main dashboard showing moving/stopped/idle counts from PortalXS data. Users see real-time fleet status without navigating to the tracking portal.

### 9. **Automated Trip-to-Task Matching**
**Current**: Task reports and trips are separate data sources.
**Enhancement**: Match PortalXS trips with daily task reports. If a vehicle made a trip but no task was logged, or vice versa, flag for review. This closes the gap between operational tasks and actual vehicle movement.

### 10. **Speed Violation Integration**
**Current**: Speed monitoring report exists with manual data entry.
**Enhancement**: Automatically import speed violations from PortalXS (trips with `MaxSpeed` > threshold). Generate penalty records automatically and link to the existing penalty system.

### 11. **Vehicle Lifecycle Tracking**
**Current**: Vehicles tracked from assignment to transfer.
**Enhancement**: Add PortalXS data to vehicle profile pages — show last known position, total mileage, trip count, and alert history alongside the existing vehicle information (model, engine no, chassis no, assignments).

### 12. **Multi-Company Fleet Management**
**Current**: System supports multiple companies and projects.
**Enhancement**: The PortalXS integration supports multiple accounts. Map different PortalXS accounts to different companies/projects. Users see only their company's vehicles on the tracking map.

### 13. **Emergency Task Verification**
**Current**: Emergency tasks are logged manually.
**Enhancement**: When an emergency task is recorded, verify the vehicle was actually at the reported location using PortalXS history data. This adds accountability to emergency response.

### 14. **Automated Report Generation**
**Current**: Tracker Automation uses Playwright to download XLSX files.
**Enhancement**: Replace the Playwright-based tracker automation with direct SOAP API calls. Generate the same reports programmatically without browser automation. Faster, more reliable, no captcha issues.

### 15. **Mobile App Integration**
**Current**: Android app exists for field staff.
**Enhancement**: Add a "Live Fleet" section to the mobile app showing real-time vehicle positions. Drivers can see their own vehicle's status. Managers can see all vehicles on mobile.

---

## Architecture Notes

- **No browser dependency**: Uses direct SOAP API with cracked 3DES encryption
- **Session persistence**: `portalxs_session.json` stores login token, auto-relogin on expiry
- **In-memory cache**: 25-second TTL for live positions (30s auto-refresh on frontend)
- **Background polling**: Optional thread polls all active accounts every 30 seconds
- **DB persistence**: Vehicle mappings and alerts stored in SQLite/PostgreSQL
- **Password security**: PortalXS passwords encrypted with Fernet (same as tracker automation)
- **Multi-account**: Supports multiple PortalXS accounts for different companies/regions
