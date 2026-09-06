# Ufone Pakistan Bridge
#
# ## Permanent production (phone worker + stable VPS public IP)
#
# - Worker + detail API run on TECNO SPARK 4 (Termux)
# - Websouls VPS is ONLY a stable public IP / SSH jump (autossh reverse)
# - Render: UFONE_VPS_DETAIL_URL=http://185.228.92.23:8787
#
# See [PHONE_BRIDGE.md](PHONE_BRIDGE.md) and helpers in `phone/`.
#
# ## Render env
#
# - `UFONE_BRIDGE_TOKEN`
# - `UFONE_BRIDGE_ONLY=1`
# - `UFONE_VPS_DETAIL_URL=http://185.228.92.23:8787`
#
# ## Ops
#
# | Action | Command |
# |--------|---------|
# | Public health | `curl -s http://185.228.92.23:8787/health` |
# | Phone shell (no USB) | `python tools/ufone_bridge/phone/phone_ssh.py` |
# | Phone bring-up | `bash ~/remote/bringup_phone_bridge.sh` |
#
# Ingest: `POST /api/ufone/bridge/ingest` header `X-Ufone-Bridge-Token`
