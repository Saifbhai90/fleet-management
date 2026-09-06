# Ufone Pakistan Bridge
#
# ## Current production (2026-09 full phone cutover)
#
# Bridge **worker + detail API + public HTTPS** run on **TECNO SPARK 4 (Termux)**
# via **Cloudflare Tunnel**. Websouls VPS is **not required**.
#
# See [PHONE_BRIDGE.md](PHONE_BRIDGE.md) and helpers in `phone/`.
#
# ## Render env (required)
#
# - `UFONE_BRIDGE_TOKEN` — shared secret (same as phone `.env`)
# - `UFONE_BRIDGE_ONLY=1` — disable Render→Ufone direct polling
# - `UFONE_VPS_DETAIL_URL` — public Cloudflare Tunnel HTTPS URL to phone `:8787`
#
# ## Ops (phone)
#
# | Action | Command |
# |--------|---------|
# | Bring-up | on phone: `bash ~/remote/bringup_phone_bridge.sh` |
# | Local health | `curl -s http://127.0.0.1:8787/health` |
# | Public URL file | `cat ~/remote/cloudflared_url.txt` |
#
# Ingest: `POST /api/ufone/bridge/ingest` header `X-Ufone-Bridge-Token`
# Health: `GET /api/ufone/bridge/health`
#
# ## Legacy note
#
# Older docs referring to Websouls `185.228.92.23` systemd worker are obsolete.
# Keep the VPS only if you still want an emergency SSH jump; it is unused for bridge traffic.
