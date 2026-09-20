# 12 — Fuel Management

## Purpose

Record vehicle fueling events with odometer continuity, MPG, payments, attachments, and market rate assistance; feed workspace MPG reporting.

---

## Models

### `FuelExpense`
Key fields include:

- Context: district, project, employee, vehicle, party  
- `fueling_date`, `payment_type`, `fuel_type`  
- `previous_reading`, `current_reading`, `km`, `liters`, `mpg`, `amount`  
- Task reading match helpers  
- Async media: `upload_status` / progress fields  

### `FuelExpenseAttachment`
Linked slips/photos (R2).

### Related
- `WorkspaceVehicleReadingSetup` — reading baselines  
- `WorkspaceMpgReportInput` / workspace MPG reports  
- Oil module is parallel (`OilExpense*`) but separate permission codes  

---

## Routes

Primary: `routes/routes_expenses.py`

| Path pattern | Role |
|--------------|------|
| `/expenses/fuel` | List |
| `/expenses/fuel/add` | Create |
| `/expenses/fuel/<pk>/edit|view|delete` | CRUD |
| APIs for last reading, duplicates, month MPG, price hints, upload status / resume | Supporting AJAX |

Oil & maintenance sibling routes live in the same module.

---

## Client UX

- Large form template `fuel_expense_form.html` (heavy inline JS).  
- Offline helper: `static/js/fuel_expense_offline.js`.  
- Attachments may upload asynchronously with resume.  

---

## Market rates

`fuel_market_scan_scheduler` runs hourly (when started) to refresh fuel market rate data consumed by hint APIs (`/api/fuel-market-rates` family).

---

## Settings / Form Control

Tab key `fuel_expense` → permission `form_control_fuel_expense`  
Logic helpers: `services/fuel_expense_settings.py`

Also subject to date **freeze** (`freeze_utils`) when enabled.

---

## Permissions

Under section `expenses`:

- `fuel_expense`, `fuel_expense_add`, `fuel_expense_edit`, `fuel_expense_delete`  
- Parent `expenses` grants full expenses section when expanded  

---

## Business rules to preserve

1. Reading continuity (previous ≈ prior current).  
2. Duplicate fueling detection APIs.  
3. MPG = km / liters (verify exact formula in form/route before changing).  
4. Attachment upload status machine.  
5. Scoped visibility by allowed projects/districts.  

---

## Relation to finance

Fuel expenses are operational records; posting into company/workspace ledgers depends on configured finance/workspace workflows — do not assume every fuel row auto-journals unless code path does so.
