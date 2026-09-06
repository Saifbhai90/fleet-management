#!/data/data/com.termux/files/usr/bin/bash
# Reverse tunnels: phone -> Websouls VPS (public IP for Render + agent access)
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
termux-wake-lock 2>/dev/null || true

pkill -x sshd 2>/dev/null || true
sshd

VPS=185.228.92.23
KEY=$HOME/.ssh/vps_deploy_key
LOG=$HOME/remote/tunnel.log

pkill -f "autossh.*185.228.92.23" 2>/dev/null || true
pkill -f "ssh.*185.228.92.23.*18022" 2>/dev/null || true
sleep 1

export AUTOSSH_GATETIME=0
export AUTOSSH_POLL=30

# 18022 -> Termux sshd (agent shell)
# 15555 -> ADB TCP 5555 (scrcpy)
# 8787  -> bridge detail HTTP (Render UFONE_VPS_DETAIL_URL)
nohup autossh -M 0 -N \
  -o BatchMode=yes \
  -o ServerAliveInterval=20 \
  -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes \
  -o StrictHostKeyChecking=accept-new \
  -i "$KEY" \
  -R 127.0.0.1:18022:127.0.0.1:8022 \
  -R 127.0.0.1:15555:127.0.0.1:5555 \
  -R 0.0.0.0:8787:127.0.0.1:8787 \
  root@$VPS >> "$LOG" 2>&1 &

echo $! > $HOME/remote/tunnel.pid
echo "[$(date)] tunnel started pid=$(cat $HOME/remote/tunnel.pid) (ssh+adb+detail8787)" | tee -a "$LOG"
