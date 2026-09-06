#!/data/data/com.termux/files/usr/bin/bash
# One-shot bring-up: phone owns Ufone bridge + public Cloudflare tunnel (no Websouls VPS).
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
set -e
termux-wake-lock 2>/dev/null || true
mkdir -p "$HOME/sessions" "$PREFIX/tmp" "$HOME/remote" "$HOME/ufone-bridge"

cd "$HOME/ufone-bridge"
grep -q '^BRIDGE_LOCK_FILE=' .env 2>/dev/null && \
  sed -i "s|^BRIDGE_LOCK_FILE=.*|BRIDGE_LOCK_FILE=$PREFIX/tmp/ufone-bridge.lock|" .env || \
  echo "BRIDGE_LOCK_FILE=$PREFIX/tmp/ufone-bridge.lock" >> .env
sed -i "s|^UFONE_SESSION_DIR=.*|UFONE_SESSION_DIR=$HOME/sessions|" .env 2>/dev/null || true
grep -q '^UFONE_SESSION_DIR=' .env || echo "UFONE_SESSION_DIR=$HOME/sessions" >> .env
grep -q '^BRIDGE_DETAIL_PORT=' .env || echo "BRIDGE_DETAIL_PORT=8787" >> .env
sed -i 's|^BRIDGE_DETAIL_PORT=.*|BRIDGE_DETAIL_PORT=8787|' .env
if grep -q '^UFONE_ACCOUNT_ID=0' .env 2>/dev/null || ! grep -q '^UFONE_ACCOUNT_ID=' .env; then
  sed -i '/^UFONE_ACCOUNT_ID=/d' .env 2>/dev/null || true
  echo "UFONE_ACCOUNT_ID=2" >> .env
fi

bash "$HOME/remote/start_tunnel.sh"

pkill -f 'python worker_pg.py' 2>/dev/null || true
pkill -f run_forever.sh 2>/dev/null || true
sleep 1
nohup bash "$HOME/ufone-bridge/run_forever.sh" >/dev/null 2>&1 &

# Optional: if watch script exists, keep publishing URL / health
pkill -f watch_tunnel.sh 2>/dev/null || true
if [ -x "$HOME/remote/watch_tunnel.sh" ]; then
  nohup bash "$HOME/remote/watch_tunnel.sh" >/dev/null 2>&1 &
fi

sleep 4
echo "=== STATUS ==="
pgrep -af 'cloudflared|worker_pg|sshd|run_forever' | head -20 || true
echo "=== DETAIL LOCAL ==="
curl -m 5 -s http://127.0.0.1:8787/health || echo "detail_not_up_yet"
echo
echo "=== PUBLIC URL ==="
cat "$HOME/remote/cloudflared_url.txt" 2>/dev/null || echo "(set named tunnel URL in remote/cloudflared_public_url.txt)"
echo
echo BRINGUP_DONE
