#!/data/data/com.termux/files/usr/bin/bash
# Permanent public reachability:
# 1) autossh reverse to Websouls VPS (stable IP for Render) — primary
# 2) optional cloudflared named/quick tunnel — secondary
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
termux-wake-lock 2>/dev/null || true
mkdir -p "$HOME/remote" "$HOME/.ssh"

VPS=185.228.92.23
KEY=$HOME/.ssh/vps_deploy_key
LOG=$HOME/remote/tunnel.log
PIDF=$HOME/remote/tunnel.pid

# Local services
pkill -x sshd 2>/dev/null || true
sshd 2>/dev/null || true

# Enable ADB over TCP for optional scrcpy via VPS (best-effort; needs USB once or root)
# ignore failures
settings put global adb_enabled 1 2>/dev/null || true

# --- Primary: VPS reverse tunnels (stable Render URL) ---
# Soak / mobile-only test: touch ~/remote/DISABLE_VPS_TUNNEL to skip VPS.
pkill -f "autossh.*${VPS}" 2>/dev/null || true
pkill -f "ssh.*${VPS}.*18022" 2>/dev/null || true
sleep 1

if [ -f "$HOME/remote/DISABLE_VPS_TUNNEL" ]; then
  echo "[$(date)] VPS tunnel DISABLED (DISABLE_VPS_TUNNEL present)" | tee -a "$LOG"
elif [ ! -f "$KEY" ]; then
  echo "[$(date)] MISSING $KEY — cannot start VPS tunnel" | tee -a "$LOG"
else
  export AUTOSSH_GATETIME=0
  export AUTOSSH_POLL=30
  # 18022 -> Termux sshd (remote admin, no USB)
  # 15555 -> ADB TCP if enabled
  # 8787  -> bridge detail (Render UFONE_VPS_DETAIL_URL)
  nohup autossh -M 0 -N \
    -o BatchMode=yes \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -o StrictHostKeyChecking=accept-new \
    -i "$KEY" \
    -R 127.0.0.1:18022:127.0.0.1:8022 \
    -R 127.0.0.1:15555:127.0.0.1:5555 \
    -R 0.0.0.0:8787:127.0.0.1:8787 \
    root@$VPS >> "$LOG" 2>&1 &
  echo $! > "$PIDF"
  echo "[$(date)] VPS autossh started pid=$(cat "$PIDF")" | tee -a "$LOG"
fi

# --- Secondary: Cloudflare (optional). Named token preferred. ---
TOKEN_FILE=$HOME/remote/cloudflared_tunnel_token.txt
CFLOG=$HOME/remote/cloudflared.log
CFPID=$HOME/remote/cloudflared.pid
URLF=$HOME/remote/cloudflared_url.txt
pkill -f 'cloudflared tunnel' 2>/dev/null || true
sleep 1
: > "$CFLOG"

if command -v cloudflared >/dev/null 2>&1; then
  if [ -f "$TOKEN_FILE" ] && [ -s "$TOKEN_FILE" ]; then
    TOKEN=$(tr -d '\r\n' < "$TOKEN_FILE")
    nohup cloudflared tunnel --no-autoupdate run --token "$TOKEN" >"$CFLOG" 2>&1 &
    echo $! > "$CFPID"
    if [ -f "$HOME/remote/cloudflared_public_url.txt" ]; then
      cp "$HOME/remote/cloudflared_public_url.txt" "$URLF"
    fi
    echo "[$(date)] named cloudflared started" | tee -a "$LOG"
  else
    # Quick tunnel is backup only; Render should use VPS URL for stability
    nohup cloudflared tunnel --url http://127.0.0.1:8787 --no-autoupdate >"$CFLOG" 2>&1 &
    echo $! > "$CFPID"
    (
      for i in $(seq 1 40); do
        url=$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$CFLOG" | tail -1 || true)
        if [ -n "$url" ]; then echo "$url" > "$URLF"; exit 0; fi
        sleep 1
      done
    ) >/dev/null 2>&1 &
    echo "[$(date)] quick cloudflared started (backup)" | tee -a "$LOG"
  fi
fi

# Prefer Cloudflare named URL; VPS IP is legacy/soak-disabled.
if [ -f "$HOME/remote/cloudflared_public_url.txt" ]; then
  cp "$HOME/remote/cloudflared_public_url.txt" "$HOME/remote/primary_public_url.txt"
else
  echo "https://ufone-detail.myfleetmanager.co.uk" > "$HOME/remote/primary_public_url.txt"
fi
