# 17 — Bugs and Risks

> Synthesized from static analysis (2026-07-21) and prior audits in `docs/AUDIT_REPORT_V2.md`.  
> **No fixes applied** in this documentation pass.

---

## High priority

| ID | Type | Description |
|----|------|-------------|
| R-01 | Security | LLM/AI HTML rendered with Jinja `\|safe` historically — XSS if still present |
| R-02 | Reliability | Hundreds of broad `except Exception` blocks can swallow real failures |
| R-03 | Ops | Schedulers + Playwright share the web dyno — resource contention / silent job failure |
| R-04 | Data | Dual GPS portals + internal vehicles can diverge if mappings incomplete |
| R-05 | Test gap | Primarily smoke tests; weak regression safety for payroll/attendance/finance |

---

## Medium priority

| ID | Type | Description |
|----|------|-------------|
| R-06 | Security | CSRF-exempt endpoints — bypass risk if origin checks weaken |
| R-07 | UX/Perf | Extremely large templates (fuel, attendance daily report, maintenance) |
| R-08 | Debt | `routes.py` still huge shared helper monolith |
| R-09 | Mobile | Release minify disabled (prior audit); larger reverse-engineering surface |
| R-10 | Auth perf | Permission/context loading may hit DB repeatedly per request |
| R-11 | Migrations | 84-version Alembic chain — painful to reason about; squash needed |
| R-12 | Secrets | Local `ufone_session_*.json` / portalxs session files may contain live sessions |
| R-13 | Consistency | Ufone tasks vs internal `EmergencyTaskRecord` not automatically reconciled |
| R-14 | Accounting | Workspace/company dual books — month-close mistakes hard to unwind |

---

## Lower priority / tech debt

| ID | Description |
|----|-------------|
| R-15 | Debug `console.log` remnants in some templates/JS |
| R-16 | Duplicate helper import patterns across finance modules |
| R-17 | SUGGESTIONS.md outdated vs current feature set (many items already built) |
| R-18 | PROJECT_KNOWLEDGE_BASE partially stale (line counts, model counts) |
| R-19 | No OpenAPI spec for `/api/v1` |
| R-20 | In-memory rate limits not multi-process safe (OK while workers=1) |

---

## Domain-specific risk notes

### Attendance
Wrong geofence/window logic → payroll disputes. Manual overrides must remain tightly permissioned.

### Fuel
Reading continuity bugs → incorrect MPG and cost reports.

### Task logbook
Upload partial failures can leave inconsistent emergency/mileage sets.

### Finance
Voucher sequence / freeze bypass would corrupt books.

### Ufone (new hub)
Still evolving (untracked files at analysis time). Treat credentials, polling, and CSRF on action POSTs carefully.

---

## Suspected bug patterns to watch when coding

1. Forgetting to register new endpoints in `ENDPOINT_PERMISSION_MAP` → 403 or open hole depending on allowlist.  
2. Forgetting hub + permission tree entries → feature invisible or over-visible.  
3. Using local `uploads/` paths on Render without R2 → lost media.  
4. Starting extra background threads without locks under multiple workers.  
5. Breaking Capacitor `User-Agent` / `/mobile-init` assumptions.
