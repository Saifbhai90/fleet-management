# Ufone Pakistan VPS Bridge
#
# VPS: 185.228.92.23 (WebSouls PK VPS-1, Ubuntu 22.04)
# Role: fetch bpocops.ufone.com from PK IP → POST cache to Render ingest API
#
# ## One-time: SSH access
#
# 1. WebSouls panel → Product 42557 → **SSH Keys** → paste `deploy_key.pub`
#    OR put root password in `.vps_password` (gitignored, one line).
# 2. From repo root (PowerShell):
#
#    .\tools\ufone_bridge\deploy.ps1
#
# ## Render env (required)
#
# - `UFONE_BRIDGE_TOKEN` — shared secret (same as VPS `.env`)
# - `UFONE_BRIDGE_ONLY=1` — disable Render→Ufone direct polling (TLS fails)
#
# ## Ops
#
# | Action | Command |
# |--------|---------|
# | Status | `ssh root@185.228.92.23 'systemctl status ufone-bridge'` |
# | Logs | `ssh root@185.228.92.23 'journalctl -u ufone-bridge -f'` |
# | One-shot sync | `ssh root@185.228.92.23 '/opt/ufone-bridge/venv/bin/python /opt/ufone-bridge/worker.py --once'` |
# | Restart | `ssh root@185.228.92.23 'systemctl restart ufone-bridge'` |
# | Rotate token | change both Render env + `/opt/ufone-bridge/.env`, restart worker |
#
# Ingest: `POST /api/ufone/bridge/ingest` header `X-Ufone-Bridge-Token`
# Health: `GET /api/ufone/bridge/health`
