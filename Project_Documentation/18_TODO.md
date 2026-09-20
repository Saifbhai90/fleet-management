# 18 — TODO

Living backlog derived from analysis, audits, and gaps. **Not** an implementation commitment.

---

## Documentation / onboarding

- [x] Create `Project_Documentation/` AI onboarding pack (this folder)  
- [ ] Keep `docs/PROJECT_KNOWLEDGE_BASE.md` in sync or point it here  
- [ ] Add OpenAPI/Swagger for `/api/v1`  
- [ ] Document Fernet key env var name/rotation procedure for PortalXS/Ufone  

---

## Security

- [ ] Verify/fix AI `\|safe` XSS (BUG-001)  
- [ ] Re-audit all `@csrf.exempt` endpoints  
- [ ] Enable Android minify/ProGuard for release  
- [ ] Ensure session JSON capture files are gitignored  
- [ ] Narrow remaining template `\|safe` usages  

---

## Quality & tests

- [ ] Expand beyond `tests/smoke_test.py` — unit tests for attendance geofence, fuel MPG, payroll calc, finance journal balance  
- [ ] Add CI (lint + smoke) on PRs  
- [ ] Reduce broad `except Exception` in hot paths  

---

## Architecture / debt

- [ ] Continue splitting helpers out of `routes.py`  
- [ ] Extract JS from mega templates (fuel, attendance daily report)  
- [ ] Squash Alembic migrations periodically  
- [ ] Move Playwright + heavy schedulers to a dedicated worker service before scaling Gunicorn workers  

---

## Product / domain

- [ ] Decide whether Ufone tasks should sync into internal `EmergencyTaskRecord`  
- [ ] PortalXS ↔ Ufone vehicle identity mapping strategy (if needed)  
- [ ] Password reset / self-service (listed in old SUGGESTIONS; may still be desired)  
- [ ] Stronger offline attendance queue UX metrics  

---

## Performance

- [ ] Cache user permission context per request/session  
- [ ] DB indexes review for new Ufone cache tables  
- [ ] Cap / archive `activity_log` and client diagnostic growth  

---

## Ops

- [ ] Confirm Render env has R2 + Firebase + Gemini + mail as needed  
- [ ] Document APK release checklist (version bump → sync → sign → `AppRelease`)  
- [ ] Backup restore drill on staging  

---

## Lead-developer process (standing)

Before any change:

1. Read relevant docs in this folder + existing module code.  
2. Reuse existing services/helpers.  
3. No duplicate logic.  
4. Match style; keep backward compatibility.  
5. State impact on permissions, migrations, mobile, and jobs.  
6. Ask if requirements are ambiguous.
