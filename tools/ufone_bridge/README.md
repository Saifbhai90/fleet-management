# Ufone Pakistan Bridge
#
# ## Current production (2026-09 cutover)
#
# Bridge **worker + detail API** run on **TECNO SPARK 4 (Termux)**.
# Websouls VPS `185.228.92.23` is only the public IP / SSH jump host.
# VPS systemd unit `ufone-bridge` is **stopped/disabled**.
#
# See [PHONE_BRIDGE.md](PHONE_BRIDGE.md) and helpers in `phone/`.
#
# ## Legacy VPS deploy (pre-cutover)
#
# VPS: 185.228.92.23 (WebSouls PK VPS-1, Ubuntu 22.04)
# Role was: fetch bpocops.ufone.com from PK IP → write Render Postgres
#
# ## One-time: SSH access (jump host)
#
# 1. WebSouls panel → Product 42557 → **SSH Keys** → paste `deploy_key.pub`
#    OR put root password in `.vps_password` (gitignored, one line).
# 2. From repo root (PowerShell):
#
#    .\tools\ufone_bridge\deploy.ps1
#
# ## Login (Fleet UI only)
#
# Bridge loads username/password from `ufone_account` (Ufone → Accounts).
# Never uses UFONE_USERNAME / UFONE_PASSWORD from .env.
# Needs `DATABASE_URL` + `UFONE_BRIDGE_TOKEN` (same as Render).
# Render boot rewraps stored passwords under the bridge token so the bridge can decrypt.
#
# ## Render env (required)
#
# - `UFONE_BRIDGE_TOKEN` — shared secret (same as phone/VPS `.env`)
# - `UFONE_BRIDGE_ONLY=1` — disable Render→Ufone direct polling (TLS fails)
# - `UFONE_VPS_DETAIL_URL=http://185.228.92.23:8787` — optional; this is the code default
#
# ## Ops (phone cutover)
#
# | Action | Command |
# |--------|---------|
# | Public detail health | `curl -s http://185.228.92.23:8787/health` |
# | Phone shell (via VPS tunnel) | `python tools/ufone_bridge/phone/phone_ssh.py` |
# | Restart phone bridge | on phone: `bash ~/remote/bringup_phone_bridge.sh` |
# | VPS prep (stop old worker) | `python tools/ufone_bridge/phone/vps_cutover_prep.py` |
#
# Ingest: `POST /api/ufone/bridge/ingest` header `X-Ufone-Bridge-Token`
# Health: `GET /api/ufone/bridge/health`
