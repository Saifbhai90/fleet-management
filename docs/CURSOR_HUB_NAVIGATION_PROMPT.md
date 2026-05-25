# Cursor Prompt — Module Hub Navigation (Fleet Manager)

Copy and paste when extending or fixing hub pages.

---

## Master prompt

Redesign navigation to use a **Hub-Based Model** instead of nested sidebar dropdowns. For each main menu item (Master Data, Assignments, Transfers, Workforce, Attendance, Task & Logbook, Finance, Payroll, Book Management, Notifications, Administration), use a dedicated **Hub Page** like Report Centre.

### Requirements

1. **Sidebar**  
   - Remove sub-menus and dropdowns for hub modules.  
   - Clicking e.g. **Master Data** navigates to `/hub/master-data` (route: `module_hub`).  
   - Keep single-link items: Dashboard, Employee Workspace, Report Centre, Master Mind AI, Backup, What's New.

2. **Design**  
   - **No-Grid Glassmorphic** launcher: pure gradient icons (no icon background boxes).  
   - Animated aurora / mesh background (`fm-aurora-bg`, `hub-glass-panel`).  
   - Labels **bold**, **centered** under icons.

3. **Icon consistency (critical)**  
   - If a report or entity exists in **Report Centre**, use the **same** Font Awesome class and `rc-tile--*` gradient tile as `reports_index.html`.  
   - Examples: Vehicles → `fa-solid fa-bus` + `rc-tile--vehicle-summary`; Daily Task → `rc-tile--daily-task`; Speed Monitoring → `rc-tile--speed`.  
   - **Never** use a different icon for the same feature in a hub vs Report Centre.

4. **Layout**  
   - Each hub has labeled **sections** (e.g. Master Data: Organization, Fleet, People).  
   - Section headers: small uppercase tags with divider line.

5. **Implementation files**  
   - Registry: `hub_registry.py` (sections, permissions, endpoints, icons).  
   - Template: `templates/module_hub.html`.  
   - Styles: `static/css/fm_hub_pages.css`, `static/css/rc_tile_gradients.css`.  
   - Sidebar: `templates/partials/sidebar_hub_links.html`.

### Adding a new hub item

1. Add entry in `hub_registry.py` under the correct hub `sections` → `items`.  
2. Set `perm` to the permission code from `permissions_config.py`.  
3. Set `icon` + `tile` to match Report Centre if the feature appears there.  
4. Add related form/list endpoints to `extra_endpoints` for sidebar active state.

### Adding a new hub module

1. Add slug key to `HUBS` in `hub_registry.py`.  
2. Add sidebar link in `sidebar_hub_links.html` or `base.html`.  
3. No new route needed — `module_hub` handles all slugs.

---

## Icon reference (Report Centre aligned)

| Feature | FA icon | Tile class |
|--------|---------|------------|
| Companies | `fa-solid fa-city` | `rc-tile--company` |
| Projects | `fa-solid fa-diagram-project` | `rc-tile--project` |
| Districts | `fa-solid fa-location-dot` | `rc-tile--district` |
| Vehicles | `fa-solid fa-bus` | `rc-tile--vehicle-summary` |
| Parking | `fa-solid fa-square-parking` | `rc-tile--parking` |
| Drivers | `fa-solid fa-id-card` | `rc-tile--driver-profile` |
| Daily Task Report | `fa-solid fa-calendar-day` | `rc-tile--daily-task` |
| Speed Monitoring | `fa-solid fa-gauge-high` | `rc-tile--speed` |
| Mileage | `fa-solid fa-route` | `rc-tile--mileage` |
| Red Task | `fa-solid fa-flag` | `rc-tile--red-task` |
| Workbook Upload | `fa-solid fa-cloud-arrow-up` | `rc-tile--upload` |

Full gradients live in `static/css/rc_tile_gradients.css`.
