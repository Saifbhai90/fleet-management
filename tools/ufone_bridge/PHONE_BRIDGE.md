# Phone Ufone Bridge — full cutover (no Websouls jump required)

## Status

Bridge **worker + detail API + public HTTPS** run on **TECNO SPARK 4 (Termux)**.

Public reachability uses **Cloudflare Tunnel** (`cloudflared`) from the phone.
Websouls VPS reverse tunnels are **no longer required**.

Remote phone admin: **RustDesk** (or USB ADB). VPS SSH jump is optional/legacy.

## Architecture

```
Ufone BPOCOPS
     ^
     | PK IP (phone)
Termux worker_pg.py + detail :8787
     |
     | cloudflared tunnel
Cloudflare edge (HTTPS)
     |
Render Hub + Postgres  (UFONE_VPS_DETAIL_URL)
```

Render:
- `UFONE_BRIDGE_ONLY=1`
- `UFONE_VPS_DETAIL_URL=<https tunnel URL>`

Phone `.env`: `UFONE_ACCOUNT_ID=2` (never `0`).

## Tunnel modes

### A) Named tunnel (recommended, stable URL)

1. Cloudflare Zero Trust → Tunnels → Create → copy install token.
2. On phone: save token to `~/remote/cloudflared_tunnel_token.txt`
3. Save public hostname to `~/remote/cloudflared_public_url.txt` (e.g. `https://ufone-detail.yourdomain.com`)
4. Set Render `UFONE_VPS_DETAIL_URL` to that hostname once.
5. `bash ~/remote/bringup_phone_bridge.sh`

### B) Quick tunnel (works now, URL changes on restart)

`cloudflared tunnel --url http://127.0.0.1:8787` writes
`~/remote/cloudflared_url.txt`. After each reboot, update Render
`UFONE_VPS_DETAIL_URL` to the new `*.trycloudflare.com` URL.

## Bring-up

```bash
bash ~/remote/bringup_phone_bridge.sh
curl -s http://127.0.0.1:8787/health
cat ~/remote/cloudflared_url.txt
```

## Verify

```bash
curl -s "$(cat tools path or phone url)/health"
python tools/ufone_bridge/phone/phone_ssh.py "pgrep -af 'worker_pg|cloudflared'"
```

Legacy VPS helpers remain under `phone/` for emergency rollback only.
