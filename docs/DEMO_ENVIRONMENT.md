# Demo Environment

Isolated Fleet Manager for client walkthroughs. **Production data is never touched.**

## What was added

| Resource | Name |
|----------|------|
| Demo web | `fleet-manager-demo` |
| Demo Postgres | `fleet-demo-db` |
| Flag | `DEMO_MODE=1` on demo only |
| Ufone bridge ingest | **Blocked** on demo |
| Sample login | `demo` / `Demo@2026` |

Production service `fleet-manager` stays on `company-management-db` with `DEMO_MODE=0`.

## Activate on Render

1. Push this repo (Blueprint already updated in `render.yaml`).
2. Render Dashboard → **Blueprint** → sync / apply so new DB + web service are created.
3. Wait for first demo deploy (migrate + `initialDeployHook` seed).
4. Open the demo service URL (e.g. `https://fleet-manager-demo.onrender.com`).
5. Login: **`demo` / `Demo@2026`** (full Admin permissions on demo only).

Optional: also `master` / `master` and `admin` / `admin` after auth seed (password change forced off on demo).

## What auto-updates

- Same Git `main` push → **both** Prod and Demo rebuild.
- New forms / filters / code → appear on Demo after deploy.
- New tables/columns → created on **Demo DB schema** via migrate/boot (empty tables).

## What does NOT sync

- Production rows (vehicles, drivers, money, Ufone live cache).
- Secrets (R2, Firebase, mail) — set separately on demo if needed; prefer **not** sharing prod R2 write credentials.
- VPS Ufone bridge — leave pointed at **production** only.

## Manual re-seed

On the demo service shell / one-off job:

```bash
DEMO_MODE=1 python -c "from services.demo_env import seed_demo_data; print(seed_demo_data())"
```

Idempotent: if `Demo Fleet Co` already exists, only ensures demo user / Admin full perms.

## Mobile

Current APK points at production URL. For mobile demo later:

- Build a Demo APK with Capacitor `server.url` = demo site, **or**
- Add an in-app Prod/Demo switch.

Web demo is enough for Phase 1.

## Safety checklist

- [ ] Demo URL shows orange **DEMO** banner
- [ ] Editing a vehicle on demo does not change production
- [ ] VPS bridge still posts only to production ingest URL
- [ ] Demo env has **no** `UFONE_BRIDGE_TOKEN` matching production
