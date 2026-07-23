# Ufone PK VPS Bridge — ops

## Architecture

Pakistan VPS `185.228.92.23` (WebSouls PK VPS-1, Ubuntu 22.04) runs
`tools/ufone_bridge/worker.py` as systemd unit `ufone-bridge`.

It logs into `bpocops.ufone.com` from a PK IP and POSTs raw payloads to:

`POST https://fleet-management-xdvj.onrender.com/api/ufone/bridge/ingest`

Header: `X-Ufone-Bridge-Token: <UFONE_BRIDGE_TOKEN>`

Render sets `UFONE_BRIDGE_ONLY=1` so the in-app poller does not call Ufone
(TLS is cut from Render outbound IPs).

## Render env

| Variable | Value |
|----------|--------|
| `UFONE_BRIDGE_TOKEN` | shared secret (same as VPS `/opt/ufone-bridge/.env`) |
| `UFONE_BRIDGE_ONLY` | `1` |

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
