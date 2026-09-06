#!/data/data/com.termux/files/usr/bin/bash
# Public reachability without Websouls VPS: Cloudflare Tunnel -> local :8787
export HOME=/data/data/com.termux/files/home
export PREFIX=/data/data/com.termux/files/usr
export PATH=$PREFIX/bin:$PATH
termux-wake-lock 2>/dev/null || true
mkdir -p "$HOME/remote"

# Prefer named tunnel token (stable hostname). Fallback: quick tunnel.
TOKEN_FILE=$HOME/remote/cloudflared_tunnel_token.txt
LOG=$HOME/remote/cloudflared.log
PIDF=$HOME/remote/cloudflared.pid
URLF=$HOME/remote/cloudflared_url.txt

pkill -f 'cloudflared tunnel' 2>/dev/null || true
# Stop legacy VPS reverse tunnels (no longer required for detail)
pkill -f "autossh.*185.228.92.23" 2>/dev/null || true
pkill -f "ssh.*185.228.92.23.*18022" 2>/dev/null || true
sleep 1
rm -f "$LOG"
: > "$LOG"

if [ -f "$TOKEN_FILE" ] && [ -s "$TOKEN_FILE" ]; then
  TOKEN=$(tr -d '\r\n' < "$TOKEN_FILE")
  nohup cloudflared tunnel --no-autoupdate run --token "$TOKEN" >"$LOG" 2>&1 &
  echo $! > "$PIDF"
  # Named tunnel hostname is configured in Cloudflare dashboard; optional override file:
  if [ -f "$HOME/remote/cloudflared_public_url.txt" ]; then
    cp "$HOME/remote/cloudflared_public_url.txt" "$URLF"
  fi
  echo "[$(date)] named cloudflared started pid=$(cat "$PIDF")"
else
  nohup cloudflared tunnel --url http://127.0.0.1:8787 --no-autoupdate >"$LOG" 2>&1 &
  echo $! > "$PIDF"
  url=""
  for i in $(seq 1 45); do
    url=$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$LOG" | tail -1 || true)
    if [ -n "$url" ]; then
      echo "$url" > "$URLF"
      break
    fi
    sleep 1
  done
  echo "[$(date)] quick cloudflared started pid=$(cat "$PIDF") url=${url:-TIMEOUT}"
fi

# Keep local sshd for USB debugging only (not exposed via VPS anymore)
sshd 2>/dev/null || true
