# 09 — GPS System

There are **four GPS-related systems**. Do not conflate them.

---

## 1. Device GPS (attendance only)

**Purpose:** Prove a driver is at their parking station for check-in/out.  
**Source:** Phone GPS via Capacitor / browser Geolocation.  
**Storage:** `DriverAttendance.check_in_latitude/longitude` (and checkout fields).  
**Geofence:** Distance to `ParkingStation.latitude/longitude` vs `AttendanceSettings.geofence_radius_meters` (default 150).  

Not used for live fleet maps.

---

## 2. PortalXS fleet tracking (primary fleet hub)

| Layer | Path |
|-------|------|
| Routes | `routes/routes_tracking.py` |
| Service | `services/portalxs_service.py` |
| SOAP client | `services/portalxs_soap_client.py` |
| Crypto | `services/portalxs_crypto.py` |
| Models | `PortalXSAccount`, `PortalXSVehicleMapping`, `PortalXSAlertCache` |
| UI | `templates/tracking/` |
| Hub | `fleet-tracking` |
| Permission section | `tracking` (+ `tracking_view`, `tracking_history`, `tracking_reports`, `tracking_alerts`, `tracking_settings`) |

### Behavior

1. Admin stores PortalXS credentials (Fernet encrypted).  
2. Sync vehicles; map portal `RegNo` → internal `Vehicle`.  
3. Background polling (~30s) caches last lat/lon/speed/status/ignition/landmark.  
4. UI polls `/api/tracking/positions` for live map.  
5. History, trips, fleet report, mileage, trends, alerts available.

Normalized fields commonly include: `RegNo`, `LAT`, `LON`, `Speed`, `VehicleStatus`, `IgnitionStatus`, `LandMark`, `RDT`.

Docs: `PORTALXS_INTEGRATION.md` at repo root.

---

## 3. Ufone BPOCOPS ambulance portal

| Layer | Path |
|-------|------|
| Routes | `routes/routes_ufone.py` |
| Service | `services/ufone_service.py` |
| Client | `services/ufone_api_client.py` |
| Models | `UfoneAccount`, `UfoneVehicleCache`, `UfoneTaskCache`, `UfoneMaintenanceCache` |
| UI | `templates/ufone/*`, `ufone_theme.css`, `ufone_app.js` |
| Capture tooling | `tools/bpocops_capture/` (HAR/session research) |
| Permission | `ufone` (+ view/history/reports/actions/admin/settings) |

### Behavior

Mirror of PortalXS pattern for `bpocops.ufone.com`:

- Encrypted accounts, polling, cache tables  
- Live map, track ambulance, vehicle history  
- Emergency tasks with comment/feedback/complete  
- Distance & ignition reports, patients, ambulance admin  
- Session files may appear as `ufone_session_*.json` (local; treat as sensitive)

---

## 4. TrackingWorld Playwright automation

| Layer | Path |
|-------|------|
| Service | `services/tracker_automation.py` |
| Models | `TrackerAutomationSettings`, `TrackerAutomationJob` |
| Admin UI | `routes_system.py` (users_manage) |

Downloads activity/mileage workbooks for ops/task comparison — **not** the live map source.

---

## Comparison matrix

| Need | Use |
|------|-----|
| Driver present at parking? | Device GPS + attendance |
| Where is our mapped fleet now? | PortalXS hub |
| Ufone ambulance ops / tasks / patients? | Ufone hub |
| Bulk tracker Excel for logbook diffs? | TrackingWorld automation |

---

## Security notes

- PortalXS/Ufone passwords stored encrypted (Fernet); encryption key must be stable across deploys.  
- Polling credentials are high-value secrets.  
- Session JSON capture files must not be committed with live cookies if avoidable.
