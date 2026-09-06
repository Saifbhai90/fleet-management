# -*- coding: utf-8 -*-
"""Cut over Ufone bridge from Websouls systemd worker to phone reverse-forward."""
from __future__ import annotations

import pathlib
import time

import paramiko

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy_key"
HOST = "185.228.92.23"


def connect() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = paramiko.Ed25519Key.from_private_key_file(str(DEPLOY))
    client.connect(
        HOST,
        username="root",
        pkey=pkey,
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    return client


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 60) -> str:
    _i, o, e = client.exec_command(cmd, timeout=timeout)
    out = (o.read() + e.read()).decode(errors="replace")
    print(cmd)
    print(out[:2000])
    print("---")
    return out


def main() -> int:
    c = connect()
    run(
        c,
        "systemctl stop ufone-bridge 2>/dev/null || true; "
        "systemctl disable ufone-bridge 2>/dev/null || true; "
        "pkill -f 'worker_pg.py' 2>/dev/null || true; "
        "fuser -k 8787/tcp 2>/dev/null || true; "
        "sleep 1; "
        "systemctl is-active ufone-bridge || echo ufone-bridge_inactive",
    )
    # clientspecified: phone can bind 0.0.0.0:8787 for Render; keep ssh/adb on 127.0.0.1
    run(
        c,
        "sed -i 's/^GatewayPorts.*/GatewayPorts clientspecified/' /etc/ssh/sshd_config; "
        "grep -q '^GatewayPorts' /etc/ssh/sshd_config || "
        "echo 'GatewayPorts clientspecified' >> /etc/ssh/sshd_config; "
        "sshd -t && systemctl reload ssh || service ssh reload; "
        "grep GatewayPorts /etc/ssh/sshd_config",
    )
    # Firewall: allow 8787 if ufw present
    run(
        c,
        "if command -v ufw >/dev/null; then ufw allow 8787/tcp || true; ufw status | head -20; "
        "else echo no_ufw; fi",
    )
    run(c, "ss -lntp | grep -E ':8787|:18022|:15555' || echo waiting_for_phone_forwards")
    c.close()
    print("VPS_CUTOVER_PREP_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
