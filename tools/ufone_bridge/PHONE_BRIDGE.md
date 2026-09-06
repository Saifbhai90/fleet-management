# Phone Ufone Bridge — Websouls worker cutover

## Status (cut over)

Bridge **worker + detail API** now run on **TECNO SPARK 4 (Termux)**.

Websouls VPS `185.228.92.23` is only:
- public IP / SSH jump
- TCP reverse-forward target for phone ports

`ufone-bridge` **systemd unit is stopped/disabled** on VPS.

Full Websouls cancel still needs Cloudflare Tunnel (or another public endpoint).
Until then the VPS bill is for the jump IP only — not for running the Python bridge.

## Architecture

```
Ufone BPOCOPS
     ^
     | PK IP (phone)
Termux worker_pg.py + detail :8787
     |
     | autossh reverse
VPS 185.228.92.23
  :8787  -> phone detail (Render UFONE_VPS_DETAIL_URL)
  :18022 -> phone sshd (agent shell; localhost on VPS)
  :15555 -> phone adb (scrcpy)
     |
Render Hub + Postgres
```

Render should keep:
- `UFONE_BRIDGE_ONLY=1`
- `UFONE_VPS_DETAIL_URL=http://185.228.92.23:8787` (code default)

Phone `.env` must have a real `UFONE_ACCOUNT_ID` (Muzaffergarh = `2`). Never `0`.

## Verify

```bash
curl -s http://185.228.92.23:8787/health
# {"ok": true, "service": "ufone-detail"}

python tools/ufone_bridge/phone/phone_ssh.py "pgrep -af worker_pg"
```

On phone (Termux / USB adb):

```bash
bash ~/remote/bringup_phone_bridge.sh
```

## Local secrets (gitignored)

Keep under `tools/ufone_bridge/_phone_remote/`:
- `phone_id_ed25519` (phone SSH key)
- `rustdesk_creds.txt` (if used)
- copies of deploy key / staging APKs

Tracked helpers live in `tools/ufone_bridge/phone/` and expect:
- `tools/ufone_bridge/deploy_key` (gitignored)
- `tools/ufone_bridge/_phone_remote/phone_id_ed25519` (or set path)

## Boot

`~/.termux/boot/ufone-bridge` starts wake-lock, sshd, tunnel, worker.

## Notes

- Phone must stay on charger + WiFi/SIM 24/7.
- `detail_ops` coerces `account_id<=0` via `resolve_ufone_login()` so detail cache FK cannot write `account_id=0`.
