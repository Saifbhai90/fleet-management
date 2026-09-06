#!/data/data/com.termux/files/usr/bin/bash
# Keep cloudflared alive; rewrite quick-tunnel URL file when it changes.
export HOME=/data/data/com.termux/files/home
export PREFIX=/data/data/com.termux/files/usr
export PATH=$PREFIX/bin:$PATH
LOG=$HOME/remote/watch_tunnel.log
mkdir -p "$HOME/remote"
while true; do
  if ! pgrep -f 'cloudflared tunnel' >/dev/null 2>&1; then
    echo "[$(date)] cloudflared down — restarting" | tee -a "$LOG"
    bash "$HOME/remote/start_tunnel.sh" >>"$LOG" 2>&1 || true
  else
    # Refresh quick-tunnel URL from log if present
    if [ ! -f "$HOME/remote/cloudflared_tunnel_token.txt" ]; then
      url=$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$HOME/remote/cloudflared.log" 2>/dev/null | tail -1 || true)
      if [ -n "$url" ]; then
        echo "$url" > "$HOME/remote/cloudflared_url.txt"
      fi
    fi
  fi
  sleep 30
done
