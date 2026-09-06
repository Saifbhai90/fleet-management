#!/data/data/com.termux/files/usr/bin/bash
# Keep VPS autossh + cloudflared + detail port healthy forever.
export HOME=/data/data/com.termux/files/home
export PREFIX=/data/data/com.termux/files/usr
export PATH=$PREFIX/bin:$PATH
LOG=$HOME/remote/watch_tunnel.log
mkdir -p "$HOME/remote"
termux-wake-lock 2>/dev/null || true

while true; do
  # VPS tunnel (optional; skipped during mobile-only soak)
  if [ ! -f "$HOME/remote/DISABLE_VPS_TUNNEL" ]; then
    if ! pgrep -f 'autossh.*185.228.92.23' >/dev/null 2>&1; then
      echo "[$(date)] autossh down — restarting tunnels" | tee -a "$LOG"
      bash "$HOME/remote/start_tunnel.sh" >>"$LOG" 2>&1 || true
    fi
  fi

  # cloudflared backup
  if command -v cloudflared >/dev/null 2>&1; then
    if ! pgrep -f 'cloudflared tunnel' >/dev/null 2>&1; then
      echo "[$(date)] cloudflared down — restarting tunnels" | tee -a "$LOG"
      bash "$HOME/remote/start_tunnel.sh" >>"$LOG" 2>&1 || true
    fi
  fi

  # detail HTTP must be up (worker starts it); if missing, nudge worker
  if ! curl -s -m 3 http://127.0.0.1:8787/health >/dev/null 2>&1; then
    echo "[$(date)] detail :8787 down — restarting worker" | tee -a "$LOG"
    pkill -f 'python worker_pg.py' 2>/dev/null || true
    pkill -f run_forever.sh 2>/dev/null || true
    sleep 1
    nohup bash "$HOME/ufone-bridge/run_forever.sh" >/dev/null 2>&1 &
  fi

  # sshd for remote admin
  if ! pgrep -x sshd >/dev/null 2>&1; then
    sshd 2>/dev/null || true
  fi

  sleep 20
done
