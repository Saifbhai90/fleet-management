# -*- coding: utf-8 -*-
"""SSH into the Ufone phone via Websouls VPS reverse tunnel (works over SIM/WiFi, no USB)."""
from __future__ import annotations

import pathlib
import sys

import paramiko

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy_key"
PHONE_KEY = pathlib.Path(__file__).resolve().parents[1] / "_phone_remote" / "phone_id_ed25519"
VPS = "185.228.92.23"
REMOTE_PORT = 18022


def phone_exec(command: str, timeout: int = 60) -> tuple[str, str]:
    deploy = paramiko.Ed25519Key.from_private_key_file(str(DEPLOY))
    jump = paramiko.SSHClient()
    jump.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    jump.connect(VPS, username="root", pkey=deploy, timeout=25, allow_agent=False, look_for_keys=False)

    # Ensure key on VPS
    sftp = jump.open_sftp()
    sftp.put(str(PHONE_KEY), "/root/.ssh/phone_access_key")
    sftp.chmod("/root/.ssh/phone_access_key", 0o600)
    sftp.close()

    remote = (
        f"ssh -i /root/.ssh/phone_access_key -p {REMOTE_PORT} "
        f"-o BatchMode=yes -o StrictHostKeyChecking=no "
        f"-o UserKnownHostsFile=/dev/null u0@127.0.0.1 {command!r}"
    )
    _i, o, e = jump.exec_command(remote, timeout=timeout)
    out, err = o.read().decode(errors="replace"), e.read().decode(errors="replace")
    jump.close()
    return out, err


def main(argv: list[str]) -> int:
    cmd = " ".join(argv[1:]) if len(argv) > 1 else "echo PHONE_OK; whoami; pwd; pgrep -af 'worker_pg|autossh|sshd' | head"
    out, err = phone_exec(cmd)
    sys.stdout.write(out)
    if err.strip():
        sys.stderr.write(err)
    return 0 if "Connection refused" not in err and "timed out" not in err.lower() else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
