#!/data/data/com.termux/files/usr/bin/bash
# Install Cloudflare named-tunnel token and make it primary public endpoint.
# Usage: bash install_named_tunnel.sh '<TOKEN>' 'https://ufone-detail.myfleetmanager.co.uk'
set -e
export HOME=/data/data/com.termux/files/home
export PATH=/data/data/com.termux/files/usr/bin:$PATH
TOKEN=${1:-}
PUBLIC_URL=${2:-https://ufone-detail.myfleetmanager.co.uk}
if [ -z "$TOKEN" ]; then
  echo "usage: $0 <TUNNEL_TOKEN> [https://hostname]"
  exit 1
fi
mkdir -p "$HOME/remote"
printf '%s' "$TOKEN" > "$HOME/remote/cloudflared_tunnel_token.txt"
printf '%s\n' "$PUBLIC_URL" > "$HOME/remote/cloudflared_public_url.txt"
printf '%s\n' "$PUBLIC_URL" > "$HOME/remote/cloudflared_url.txt"
# Prefer named tunnel over quick tunnel; keep VPS autossh until Render cutover verified
bash "$HOME/remote/start_tunnel.sh"
sleep 4
echo "=== LOCAL ==="
curl -s -m 5 http://127.0.0.1:8787/health || true
echo
echo "=== PUBLIC ==="
curl -s -m 20 "$PUBLIC_URL/health" || true
echo
echo "TOKEN_INSTALLED"
