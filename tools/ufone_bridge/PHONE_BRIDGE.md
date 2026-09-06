# Phone Ufone Bridge — permanent setup

## Goal

Bridge **always runs on phone**. Public URL stays **stable** so Render / agent
access does not break after USB unplug.

## Architecture (permanent)

```
Ufone BPOCOPS  <--- phone WiFi/SIM (PK IP)
        ^
Termux: worker_pg.py + detail :8787
        |
        | autossh reverse (always-on, watchdog)
VPS 185.228.92.23   (stable public IP ONLY)
  :8787  -> phone detail   << Render UFONE_VPS_DETAIL_URL
  :18022 -> phone sshd     << remote admin (no USB)
  :15555 -> phone adb      << optional scrcpy
        |
Render Hub
```

Optional backup: `cloudflared` quick/named tunnel (not used by Render by default).

## Why this is permanent

| Problem before | Fix now |
|----------------|---------|
| USB unplug killed internet (gnirehtet) | Phone uses own WiFi/SIM |
| trycloudflare URL changed every restart | Render uses stable `http://185.228.92.23:8787` |
| Connection refused / dead after reboot | Termux:Boot + `watch_tunnel.sh` + `run_forever.sh` |
| No remote admin without USB | VPS `:18022` SSH jump restored |

## Render env

- `UFONE_BRIDGE_ONLY=1`
- `UFONE_VPS_DETAIL_URL=http://185.228.92.23:8787`

## Phone ops

```bash
bash ~/remote/bringup_phone_bridge.sh
curl -s http://127.0.0.1:8787/health
curl -s http://185.228.92.23:8787/health
```

From PC (no USB):

```bash
python tools/ufone_bridge/phone/phone_ssh.py "pgrep -af worker_pg"
```

## Boot

`~/.termux/boot/ufone-bridge` → `bringup_phone_bridge.sh`  
Keep phone on charger. Disable battery optimization for Termux (already whitelisted via ADB).

## Later: cancel Websouls

Add Cloudflare **named tunnel token** to `~/remote/cloudflared_tunnel_token.txt`
and hostname to `~/remote/cloudflared_public_url.txt`, point Render to that HTTPS
URL, then you can stop paying for the VPS jump IP.
