# 15 — Security

## Authentication

| Surface | Mechanism |
|---------|-----------|
| Web / Capacitor WebView | Flask session cookies; `SECRET_KEY` required (no fallback) |
| Mobile API | JWT HS256 Bearer, 24h, signed with same `SECRET_KEY` |
| Biometric | Device biometric unlock → session re-establishment endpoints |
| Login identity | CNIC-style username + password hash (Werkzeug) |

Session: permanent lifetime from `SESSION_DAYS` (default 30), refresh each request. Cookie secure flag via `SESSION_COOKIE_SECURE` (true on Render).

---

## Authorization (RBAC)

1. **Roles** contain many **Permission** codes (M2M).  
2. Login expands permissions (`permissions_config.expand_login_permissions`) — section codes unlock children.  
3. **Master** role / `is_master` bypasses checks.  
4. `auth_utils.ENDPOINT_PERMISSION_MAP` maps endpoint → required code.  
5. Default-deny with `ALLOWED_AUTHED_ENDPOINTS` allowlist for generic authenticated pages.  
6. Data scoping: `allowed_projects` / `districts` / `vehicles` / `shifts` in session.  

Section codes include: `dashboard`, `master`, `assignment`, `transfer`, `driver_status`, `attendance`, `task_report`, `expenses`, `accounts`, `workspace`, `reports`, `payroll`, `books`, `backup`, `users_manage`, `tracking`, `ufone`.

Form Control uses tab codes (`form_control_attendance`, `form_control_freeze`, …) plus legacy `form_control`.

---

## CSRF

Flask-WTF CSRFProtect enabled globally.  
Some JSON/mobile endpoints are `@csrf.exempt` — several validate Origin/Referer. Audit list (historical): biometric, AI query, client diagnostics, blob upload, app logout, etc. Treat exemptions as sensitive.

---

## Secrets & encryption

| Secret | Usage |
|--------|-------|
| `SECRET_KEY` | Sessions + JWT |
| R2 keys | Object storage |
| Firebase SA JSON | FCM |
| `GOOGLE_API_KEY` | Gemini |
| Mail credentials | Backup email |
| PortalXS / Ufone passwords | Fernet-encrypted in DB (`portalxs_crypto` / ufone service) |
| Android keystore / google-services | Native push/signing |

`.env`, `.env.local`, session JSON files, and `config/firebase-service-account.json` must not be committed carelessly.

---

## Known security concerns (from audits + analysis)

| Severity | Issue |
|----------|-------|
| P1 | AI report template historically rendered LLM output with `\|safe` (XSS risk) — verify current state before changes |
| P2 | Multiple CSRF-exempt endpoints — keep origin checks tight |
| P2 | Android release `minifyEnabled false` (prior audit) |
| P2 | Broad `except Exception` may hide auth/data failures |
| P3 | Cleartext LAN allowances in Android network security config for debug |
| P3 | Remaining `\|safe` filters in templates — audit context |
| — | JWT and session share `SECRET_KEY` — rotate carefully (logs out everyone) |
| — | In-memory login rate limit not shared across workers (currently 1 worker) |
| — | Ufone/PortalXS session files on disk are sensitive |

---

## Upload security

- `MAX_CONTENT_LENGTH` 50MB (app config); expense attachment max may be separately env-capped.  
- Images processed/resized to WebP via Pillow before R2.  
- Prefer `secure_filename` / UUID keys in R2.  
- `/r2-proxy` style access should remain auth-gated.

---

## Audit logging

Models: `LoginLog`, `LoginAttempt`, `ActivityLog`, `ClientActivityLog`, `ClientDiagnosticLog`.  
Use these rather than inventing parallel audit tables.

---

## Hardening checklist for new features

1. Add permission codes + endpoint map entries.  
2. Keep CSRF on form posts; if JSON exempt, validate origin + auth.  
3. Scope queries to allowed entities.  
4. Never log passwords or Fernet keys.  
5. Sanitize any HTML from AI/user content (no raw `\|safe`).  
6. Validate file types/sizes on upload.
