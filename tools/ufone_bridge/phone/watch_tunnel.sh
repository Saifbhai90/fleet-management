#!/data/data/com.termux/files/usr/bin/bash
# Keep cloudflared + detail port healthy forever (VPS autossh optional/soak).
export HOME=/data/data/com.termux/files/home
export PREFIX=/data/data/com.termux/files/usr
export PATH=$PREFIX/bin:$PATH
LOG=$HOME/remote/watch_tunnel.log
mkdir -p "$HOME/remote"
termux-wake-lock 2>/dev/null || true

CF_FAILS=0

_restart_tunnels() {
  echo "[$(date)] restarting tunnels: $1" | tee -a "$LOG"
  bash "$HOME/remote/start_tunnel.sh" >>"$LOG" 2>&1 || true
}

while true; do
  SLEEP_SEC=20

  # VPS tunnel (optional; skipped during mobile-only soak)
  if [ ! -f "$HOME/remote/DISABLE_VPS_TUNNEL" ]; then
    if ! pgrep -f 'autossh.*185.228.92.23' >/dev/null 2>&1; then
      _restart_tunnels "autossh down"
      SLEEP_SEC=10
    fi
  fi

  # cloudflared process missing → restart immediately
  if command -v cloudflared >/dev/null 2>&1; then
    if ! pgrep -f 'cloudflared tunnel' >/dev/null 2>&1; then
      CF_FAILS=0
      _restart_tunnels "cloudflared process down"
      SLEEP_SEC=10
    else
      # Process up but Cloudflare edge may be disconnected (Error 1033).
      # Require 2 consecutive public failures before restart (avoid flaky false positives).
      PUB=$(tr -d '\r\n' < "$HOME/remote/cloudflared_public_url.txt" 2>/dev/null || true)
      if [ -n "$PUB" ]; then
        if curl -s -m 10 "$PUB/health" | grep -q '"ok"'; then
          CF_FAILS=0
        else
          CF_FAILS=$((CF_FAILS + 1))
          echo "[$(date)] public tunnel check fail #$CF_FAILS ($PUB)" | tee -a "$LOG"
          if [ "$CF_FAILS" -ge 2 ]; then
            CF_FAILS=0
            pkill -f 'cloudflared tunnel' 2>/dev/null || true
            sleep 1
            _restart_tunnels "public tunnel unhealthy (Error 1033 likely)"
            SLEEP_SEC=10
          fi
        fi
      fi
    fi
  fi

  # detail HTTP must be up (worker starts it)
  if ! curl -s -m 3 http://127.0.0.1:8787/health >/dev/null 2>&1; then
    echo "[$(date)] detail :8787 down — restarting worker" | tee -a "$LOG"
    pkill -f 'python worker_pg.py' 2>/dev/null || true
    pkill -f run_forever.sh 2>/dev/null || true
    sleep 1
    nohup bash "$HOME/ufone-bridge/run_forever.sh" >/dev/null 2>&1 &
    SLEEP_SEC=10
  fi

  # sshd for remote admin
  if ! pgrep -x sshd >/dev/null 2>&1; then
    sshd 2>/dev/null || true
  fi

  sleep "$SLEEP_SEC"
done
