#!/usr/bin/env bash
# Run ON the VPS as root after files are in /opt/ufone-bridge
set -euo pipefail
cd /opt/ufone-bridge

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip curl ca-certificates

python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

mkdir -p sessions
chmod 700 sessions
if [[ ! -f .env ]]; then
  echo "ERROR: /opt/ufone-bridge/.env missing — copy from .env.example and fill secrets"
  exit 1
fi
chmod 600 .env

# Prove Ufone TLS from this IP
echo "=== TLS probe bpocops.ufone.com ==="
curl -sS -o /dev/null -w "HTTP %{http_code} time=%{time_total}s\n" \
  --connect-timeout 15 --max-time 40 \
  -I "https://bpocops.ufone.com/Login.aspx" || {
  echo "FAIL: Ufone TLS/HTTP probe failed from this VPS — stop and investigate"
  exit 2
}

cp systemd/ufone-bridge.service /etc/systemd/system/ufone-bridge.service
systemctl daemon-reload
systemctl enable ufone-bridge.service
systemctl restart ufone-bridge.service
systemctl --no-pager -l status ufone-bridge.service || true
echo "Bootstrap OK. Logs: journalctl -u ufone-bridge -f"
