# 06 — Frontend

## Rendering model

Server-rendered **Jinja2** templates with progressive enhancement via JavaScript. Not a React SPA (except embedded daedalOS / personal PC assets).

**Base templates:**
- `templates/base.html` — main shell (sidebar hubs, nav, scripts)
- `templates/ufone/base.html` — Ufone portal chrome
- `templates/tracking/` — PortalXS pages
- Feature folders: `workspace/`, `finance/`, `payroll/`, `books/`, `partials/`

---

## UI building blocks

| Piece | Notes |
|-------|-------|
| Bootstrap 5 | Layout/components |
| Font Awesome / Bootstrap Icons | Icons in hubs |
| Tom Select | Advanced selects (`static/vendor/`) |
| Flatpickr | Dates (used on many forms) |
| Chart.js-style KPIs | Dashboard cards |
| Leaflet-style maps | Tracking / Ufone live maps |
| Report Centre tiles | Gradient tile CSS (`rc_tile_gradients.css`) |

Hub landing pages: `/hub/<slug>` driven by `hub_registry.HUBS`.

---

## CSS structure (`static/css/`)

| File | Role |
|------|------|
| `core/fleet_styles.css` | Core fleet styles |
| `fm_aurora_theme.css` | Theme accents |
| `fm_hub_pages.css` | Hub page layout |
| `fleet_data_grid.css` | Data grids/tables |
| `rc_tile_gradients.css` | Report/hub tile colors |
| `mobile_perfect.css` | Mobile polish |
| `mobile_native_sidebar.css` | Native-feel sidebar |
| `mobile_responsive_audit.css` | Responsive fixes |
| `legacy_android_gpu.css` | Android WebView GPU quirks |
| `ufone_theme.css` | Ufone portal theme |

---

## JavaScript modules (`static/js/`)

| File / folder | Role |
|---------------|------|
| `core/fleet_core.js` | Shared core helpers |
| `core/fleet_ui.js` | UI behaviors |
| `core/fleet_mobile.js` | Capacitor / mobile bridge |
| `fleet_biometric_toggle.js` | Biometric settings |
| `fleet_notifications_ui.js` | In-app notifications UI |
| `fleet_client_diagnostics.js` | Client error reporting |
| `gps_attendance_pending_upload.js` | Offline/retry attendance media |
| `fuel_expense_offline.js` | Fuel form offline resilience |
| `session_sounds.js` | Session UX sounds |
| `legacy_android_gpu.js` | Android rendering workarounds |
| `ufone_app.js` | Ufone portal client logic |
| `ws_slip_ocr/01_…_11_*.js` | Client OCR pipeline (Tesseract / OpenCV / TrOCR bridge) |
| `jszip.min.js` | ZIP downloads (e.g. media gallery) |

Many large templates still embed substantial inline JS (technical debt).

---

## Notable large templates (mobile risk)

From prior audits:

- `fuel_expense_form.html` (~3.6k lines)
- `driver_attendance_daily_report.html` (~3.7k lines)
- `maintenance_expense_form.html` (~2.6k lines)
- `workspace/transfer_form.html` (~2k lines)
- `driver_form.html`, `dashboard.html`, check-in/out pages

Prefer editing carefully; extract JS only when scoped.

---

## Frontend permissions

Visibility is **not** only CSS:

- Sidebar items gated by permission codes from session.  
- Buttons/links often wrapped with permission checks in templates.  
- Form Control tabs gate settings UI (`permissions_config.user_has_form_control_tab`).  

Always enforce on the **server** too.

---

## PWA / mobile web

- Capacitor loads remote URL (not local `www` content as primary).  
- Mobile CSS + `fleet_mobile.js` adapt gestures, sidebar, safe areas.  
- Compression (Brotli/Gzip) reduces payload on slow networks.

---

## Design guidance for changes

- Match existing hub tile / Bootstrap patterns.  
- Reuse `fleet_core` / `fleet_ui` helpers.  
- Do not invent a parallel design system.  
- Keep Ufone theme scoped under `ufone_*` assets.
