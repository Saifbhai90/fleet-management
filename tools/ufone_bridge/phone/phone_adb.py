# -*- coding: utf-8 -*-
"""ADB/scrcpy to Ufone phone via Websouls VPS reverse tunnel (no USB)."""
from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy_key"
VPS = "185.228.92.23"
REMOTE_ADB_PORT = 15555
LOCAL_ADB_PORT = 15555
SERIAL = f"127.0.0.1:{LOCAL_ADB_PORT}"


def adb_bin() -> str:
    local = (
        pathlib.Path(os.environ.get("LOCALAPPDATA", ""))
        / "Android"
        / "Sdk"
        / "platform-tools"
        / "adb.exe"
    )
    return str(local) if local.exists() else "adb"


def scrcpy_bin() -> str:
    base = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    found = sorted(base.glob("Genymobile.scrcpy*/**/scrcpy.exe"))
    return str(found[0]) if found else "scrcpy"


def start_tunnel() -> subprocess.Popen:
    cmd = [
        "ssh",
        "-i",
        str(DEPLOY),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ServerAliveInterval=20",
        "-o",
        "ExitOnForwardFailure=yes",
        "-N",
        "-L",
        f"{LOCAL_ADB_PORT}:127.0.0.1:{REMOTE_ADB_PORT}",
        f"root@{VPS}",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    time.sleep(2)
    if proc.poll() is not None:
        err = (proc.stderr.read() or b"").decode(errors="replace")
        raise RuntimeError(f"SSH tunnel failed: {err}")
    return proc


def adb_connect() -> None:
    adb = adb_bin()
    subprocess.run([adb, "disconnect", SERIAL], capture_output=True)
    r = subprocess.run([adb, "connect", SERIAL], capture_output=True, text=True, timeout=25)
    msg = (r.stdout or r.stderr or "").strip()
    print(msg)
    if "connected" not in msg.lower() and "already" not in msg.lower():
        raise RuntimeError(f"adb connect failed: {msg}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        nargs="?",
        default="connect",
        choices=["connect", "devices", "shell", "scrcpy"],
    )
    parser.add_argument("shell_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv[1:])

    tunnel = start_tunnel()
    try:
        adb_connect()
        adb = adb_bin()
        if args.action == "devices":
            return subprocess.call([adb, "devices", "-l"])
        if args.action == "shell":
            extra = [a for a in args.shell_args if a != "--"]
            return subprocess.call([adb, "-s", SERIAL, "shell", *extra])
        if args.action == "scrcpy":
            return subprocess.call(
                [
                    scrcpy_bin(),
                    "-s",
                    SERIAL,
                    "--stay-awake",
                    "--turn-screen-on",
                    "--window-title",
                    "Ufone-Phone-TECNO",
                ],
                env={**os.environ, "ADB": adb},
            )
        return subprocess.call([adb, "devices", "-l"])
    finally:
        tunnel.terminate()
        try:
            tunnel.wait(timeout=5)
        except Exception:
            tunnel.kill()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
