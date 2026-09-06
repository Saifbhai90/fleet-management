# -*- coding: utf-8 -*-
"""One-shot USB deploy of remote-admin pieces; after this, use phone_ssh.py over CF."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
PHONE = pathlib.Path(__file__).resolve().parent
ADB = (
    pathlib.Path(os.environ.get("LOCALAPPDATA", ""))
    / "Android"
    / "Sdk"
    / "platform-tools"
    / "adb.exe"
)
BASH = "/data/data/com.termux/files/usr/bin/bash"
HOME = "/data/data/com.termux/files/home"


def adb(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(
        [str(ADB), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and r.returncode != 0:
        raise SystemExit(
            f"adb {' '.join(args)} failed rc={r.returncode}\n{r.stdout}\n{r.stderr}"
        )
    return r


def push_to_termux(local: pathlib.Path, remote: str) -> None:
    sd = f"/sdcard/_ufone_push_{local.name}"
    adb("push", str(local), sd)
    # Avoid nested-quote hell: run-as sh -c with simple cp
    adb(
        "shell",
        "run-as",
        "com.termux",
        "cp",
        sd,
        remote,
    )


def run_termux_script(script: str) -> str:
    with tempfile.NamedTemporaryFile(
        "w", suffix=".sh", delete=False, encoding="utf-8", newline="\n"
    ) as f:
        f.write("#!/data/data/com.termux/files/usr/bin/bash\n")
        f.write(script)
        if not script.endswith("\n"):
            f.write("\n")
        local = f.name
    try:
        sd = "/sdcard/_ufone_bootstrap.sh"
        remote = f"{HOME}/remote/_ufone_bootstrap.sh"
        adb("push", local, sd)
        adb("shell", "run-as", "com.termux", "cp", sd, remote)
        r = adb("shell", "run-as", "com.termux", BASH, remote, check=False)
        sys.stdout.write(r.stdout or "")
        if r.stderr:
            sys.stderr.write(r.stderr)
        if r.returncode != 0:
            raise SystemExit(f"bootstrap script rc={r.returncode}")
        return r.stdout or ""
    finally:
        pathlib.Path(local).unlink(missing_ok=True)


def main() -> int:
    if not ADB.is_file():
        raise SystemExit(f"adb missing: {ADB}")
    devices = adb("devices").stdout
    if "\tdevice" not in devices:
        raise SystemExit("No USB device in 'device' state. Plug phone once for this bootstrap.")

    files = [
        (ROOT / "detail_ops.py", f"{HOME}/ufone-bridge/detail_ops.py"),
        (PHONE / "start_tunnel.sh", f"{HOME}/remote/start_tunnel.sh"),
        (PHONE / "watch_tunnel.sh", f"{HOME}/remote/watch_tunnel.sh"),
        (PHONE / "bringup_phone_bridge.sh", f"{HOME}/remote/bringup_phone_bridge.sh"),
    ]
    for local, remote in files:
        if not local.is_file():
            raise SystemExit(f"missing {local}")
        print("PUSH", local.name, "->", remote)
        push_to_termux(local, remote)

    run_termux_script(
        f"""
export HOME={HOME}
export PREFIX=/data/data/com.termux/files/usr
export PATH=$PREFIX/bin:$PATH
mkdir -p "$HOME/remote" "$HOME/ufone-bridge"
touch "$HOME/remote/DISABLE_VPS_TUNNEL"
chmod 755 "$HOME/remote/start_tunnel.sh" "$HOME/remote/watch_tunnel.sh" "$HOME/remote/bringup_phone_bridge.sh" || true
pkill -f autossh || true
pkill -f 'ssh.*185.228.92.23' || true
pkill -f watch_tunnel.sh || true
pkill -f 'python worker_pg.py' || true
pkill -f run_forever.sh || true
sleep 2
nohup bash "$HOME/ufone-bridge/run_forever.sh" >/dev/null 2>&1 &
nohup bash "$HOME/remote/watch_tunnel.sh" >/dev/null 2>&1 &
sshd 2>/dev/null || true
sleep 8
echo ===PROCS===
pgrep -af worker_pg || echo no_worker
pgrep -af cloudflared || echo no_cf
pgrep -af watch_tunnel || echo no_watch
pgrep -af autossh || echo no_autossh_ok
pgrep -af sshd || echo no_sshd
echo ===HEALTH===
curl -s -m 5 http://127.0.0.1:8787/health || echo DOWN
echo
echo BOOTSTRAP_DONE
"""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
