# Ufone PK VPS Bridge — ops

## Architecture

Pakistan VPS `185.228.92.23` (WebSouls PK VPS-1, Ubuntu 22.04) runs
`tools/ufone_bridge/worker_pg.py` as systemd unit `ufone-bridge`.

It logs into `bpocops.ufone.com` from a PK IP and **writes Ufone vehicle/task
caches directly to Render Postgres** (`DATABASE_URL`). Optional small HTTP
batches can push emergency report rows via `/api/ufone/bridge/ingest`.

Fleet UI on Render reads DB-first caches (`UFONE_BRIDGE_ONLY=1` disables
direct bpocops polling from Render).

## Render env

| Variable | Value |
|----------|--------|
| `UFONE_BRIDGE_TOKEN` | shared secret (same as VPS `/opt/ufone-bridge/.env`) |
| `UFONE_BRIDGE_ONLY` | `1` |

If `UFONE_BRIDGE_TOKEN` is empty, the app derives a token from `SECRET_KEY`
(`HMAC-SHA256(SECRET_KEY, "ufone-bridge-v1")`). Prefer an explicit shared token.

Current VPS worker expects the token stored in `tools/ufone_bridge/.bridge_token`
(local) / `/opt/ufone-bridge/.env` (server). Paste that same value into Render.

## VPS deploy

1. WebSouls → product 42557 → **SSH Keys** → paste `tools/ufone_bridge/deploy_key.pub`
   (or put root password in `tools/ufone_bridge/.vps_password`).
2. Fill `tools/ufone_bridge/.env` from `.env.example`.
3. `python tools/ufone_bridge/deploy_paramiko.py`

## Commands

```bash
ssh -i tools/ufone_bridge/deploy_key root@185.228.92.23 'systemctl status ufone-bridge'
ssh -i tools/ufone_bridge/deploy_key root@185.228.92.23 'journalctl -u ufone-bridge -n 50 --no-pager'
ssh -i tools/ufone_bridge/deploy_key root@185.228.92.23 '/opt/ufone-bridge/venv/bin/python /opt/ufone-bridge/worker.py --once'
```

## Rotate token

1. Generate new token.
2. Update Render `UFONE_BRIDGE_TOKEN`.
3. Update `/opt/ufone-bridge/.env` on VPS → `systemctl restart ufone-bridge`.
