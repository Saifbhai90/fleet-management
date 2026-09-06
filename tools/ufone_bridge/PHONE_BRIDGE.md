# Phone Ufone Bridge — Cloudflare named tunnel

## Production URL

`https://ufone-detail.myfleetmanager.co.uk` → phone Termux `http://127.0.0.1:8787`

Render env:
- `UFONE_BRIDGE_ONLY=1`
- `UFONE_VPS_DETAIL_URL=https://ufone-detail.myfleetmanager.co.uk`

## Architecture

```
Ufone BPOCOPS <- phone WiFi/SIM
Termux worker_pg + detail :8787
     |
cloudflared named tunnel (token in ~/remote/cloudflared_tunnel_token.txt)
     |
Cloudflare edge: ufone-detail.myfleetmanager.co.uk
     |
Render Hub
```

## Remote admin (no USB, no Websouls)

Primary access is Cloudflare HTTPS on the same detail tunnel:

```bash
# From PC (repo root tooling):
python tools/ufone_bridge/phone/phone_ssh.py 'echo PHONE_OK; pgrep -af worker_pg'
```

This calls `POST https://ufone-detail.myfleetmanager.co.uk/remote-exec` with
`X-Ufone-Bridge-Token` (same as bridge). File deploy: `/remote-put`.

USB is only needed once for bootstrap (or if cloudflared/token is broken).
VPS autossh is optional/legacy — soak flag `~/remote/DISABLE_VPS_TUNNEL` skips it.

## Phone files

- `~/remote/cloudflared_tunnel_token.txt` — named tunnel token
- `~/remote/cloudflared_public_url.txt` — `https://ufone-detail.myfleetmanager.co.uk`
- `~/remote/DISABLE_VPS_TUNNEL` — skip Websouls reverse tunnels
- `bash ~/remote/bringup_phone_bridge.sh` — starts worker + named cloudflared (+ optional VPS jump)

## Verify

```bash
curl -s https://ufone-detail.myfleetmanager.co.uk/health
# {"ok": true, "service": "ufone-detail"}

python tools/ufone_bridge/phone/phone_ssh.py 'curl -s http://127.0.0.1:8787/health'
```
