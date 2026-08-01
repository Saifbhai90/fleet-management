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

### If `fleet-manager-demo` already exists (created via API/dashboard)

1. Open [fleet-manager-demo Settings](https://dashboard.render.com/web/srv-d9mpqdp42hec73e8hui0/settings).
2. Set **Build Command** to exactly:
   ```text
   pip install -r requirements.txt
   ```
   (Do **not** use `playwright install --with-deps` — it fails on Render without root/`su`.)
3. Environment → add `DATABASE_URL` = **Internal Database URL** from [fleet-demo-db](https://dashboard.render.com/d/dpg-d9mporh42hec73e8ee30-a) → Connect.
4. Ensure `DEMO_MODE=1` and a unique `SECRET_KEY` (not production’s).
5. Manual Deploy → Clear build cache & deploy.
6. Open https://fleet-manager-demo.onrender.com — orange **DEMO** banner.
7. Login: **`demo` / `Demo@2026`**.

### Blueprint sync (optional / future)

Push this repo, then Blueprint Sync if you manage infra via `render.yaml`. Demo build command in yaml is already `pip install -r requirements.txt` only.

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
