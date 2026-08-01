# Demo Environment

Isolated Fleet Manager for client walkthroughs. Edits on Demo do **not** change Production.

## Resources

| Resource | Name / URL |
|----------|------------|
| Demo web | [fleet-demo](https://fleet-demo.onrender.com) (`srv-d9mptl142hec73e8oub0`) |
| Demo Postgres | `fleet-demo-db` (`dpg-d9mporh42hec73e8ee30-a`) |
| Flag | `DEMO_MODE=1` on demo only |
| Ufone bridge ingest | **Blocked** on demo |
| Login (Master) | **`demo` / `Demo#2026`** |

## Clone production data → demo DB

Prod is ~1.5 GB. Demo disk must be large enough (5 GB+).

1. Open [fleet-demo-db → Connect](https://dashboard.render.com/d/dpg-d9mporh42hec73e8ee30-a) and copy **External Database URL**.
2. Install PostgreSQL client tools (`pg_dump` / `pg_restore`) if missing.
3. From repo root:

```powershell
$env:DEMO_DATABASE_URL = "postgresql://...External URL from Connect..."
powershell -File scripts/clone_prod_to_demo.ps1
```

4. On [fleet-demo → Environment](https://dashboard.render.com/web/srv-d9mptl142hec73e8oub0/env): set `DATABASE_URL` to the **Internal** Database URL (same password as External; internal hostname).
5. Ensure `DEMO_MODE=1`, then **Manual Deploy**.
6. Login: **`demo` / `Demo#2026`** (Master).

The clone script dumps prod, restores into demo (`--clean`), then ensures the Master login above. Production is only read (dump), never written.

## Empty demo (sample data only)

If demo DB has no companies, boot with `DEMO_MODE=1` seeds a small sample fleet plus the same Master login.

If companies already exist (including after a prod clone), seed **skips** sample rows and only resets `demo` → Master / `Demo#2026`.

```bash
DEMO_MODE=1 python -c "from services.demo_env import seed_demo_data; print(seed_demo_data())"
```

## What auto-updates

- Same Git `main` push → Prod and Demo rebuild (if both auto-deploy).
- Code/forms → Demo after deploy.
- Production **rows** do not auto-sync; re-run the clone script when you want a fresh copy.

## Safety checklist

- [ ] Demo URL shows orange **DEMO** banner
- [ ] Editing on demo does not change production
- [ ] VPS bridge still posts only to production
- [ ] Demo has **no** production `UFONE_BRIDGE_TOKEN`
