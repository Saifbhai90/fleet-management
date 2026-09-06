# -*- coding: utf-8 -*-
"""Run a shell command on the Ufone phone — USB/VPS not required.

Primary path: Cloudflare HTTPS → phone detail server `/remote-exec`
(same UFONE_BRIDGE_TOKEN). Works while phone has WiFi/SIM + cloudflared.

Legacy fallbacks (optional):
  - VPS jump 185.228.92.23:18022 (only if Websouls is up)
  - USB ADB (only if cable connected)
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
PHONE_DIR = pathlib.Path(__file__).resolve().parent
BRIDGE_TOKEN_FILE = ROOT / ".bridge_token"
ENV_FILE = ROOT / ".env"
CF_DETAIL_URL = "https://ufone-detail.myfleetmanager.co.uk"
CF_RESOLVE_IP = "104.21.33.125"  # optional; urllib uses system DNS


def _load_token() -> str:
    if BRIDGE_TOKEN_FILE.is_file():
        tok = BRIDGE_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("UFONE_BRIDGE_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("UFONE_BRIDGE_TOKEN missing (.bridge_token or .env)")


def phone_exec_cf(command: str, timeout: float = 60.0) -> tuple[str, str, int]:
    """Execute via Cloudflare named tunnel. Returns stdout, stderr, exit_code."""
    token = _load_token()
    url = f"{CF_DETAIL_URL.rstrip('/')}/remote-exec"
    body = json.dumps({"cmd": command, "timeout": timeout}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Ufone-Bridge-Token": token,
            "User-Agent": "fleet-phone-ssh/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=max(timeout + 15.0, 30.0)) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            raise RuntimeError(f"CF remote-exec HTTP {e.code}: {raw[:300]}") from e
        if e.code == 401:
            raise RuntimeError("unauthorized — check UFONE_BRIDGE_TOKEN") from e
        if not payload.get("ok") and "stdout" not in payload:
            raise RuntimeError(payload.get("error") or raw[:300]) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"CF unreachable: {e}") from e

    if not payload.get("ok") and payload.get("error") == "timeout":
        return payload.get("stdout") or "", payload.get("stderr") or "timeout", 124
    if not payload.get("ok") and "exit_code" not in payload:
        raise RuntimeError(payload.get("error") or "remote-exec failed")
    return (
        payload.get("stdout") or "",
        payload.get("stderr") or "",
        int(payload.get("exit_code") or 0),
    )


def phone_put_cf(path: str, content: bytes, mode: str | None = None) -> None:
    """Write a file on the phone over Cloudflare (USB-free deploy)."""
    import base64

    token = _load_token()
    url = f"{CF_DETAIL_URL.rstrip('/')}/remote-put"
    body_obj: dict = {
        "path": path,
        "content_b64": base64.b64encode(content).decode("ascii"),
    }
    if mode is not None:
        body_obj["mode"] = mode
    body = json.dumps(body_obj).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Ufone-Bridge-Token": token,
            "User-Agent": "fleet-phone-ssh/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "remote-put failed")


def phone_exec(command: str, timeout: int = 60) -> tuple[str, str]:
    """Compat wrapper used by older scripts: returns (stdout, stderr)."""
    out, err, code = phone_exec_cf(command, timeout=float(timeout))
    if code != 0 and not err:
        err = f"exit_code={code}"
    return out, err


def main(argv: list[str]) -> int:
    cmd = (
        " ".join(argv[1:])
        if len(argv) > 1
        else "echo PHONE_OK; whoami; pwd; pgrep -af 'worker_pg|cloudflared|sshd|autossh|watch_tunnel' | head -20"
    )
    try:
        out, err, code = phone_exec_cf(cmd, timeout=90.0)
    except Exception as e:
        sys.stderr.write(f"CF_PATH_FAILED: {e}\n")
        # Optional VPS fallback if still alive
        try:
            out2, err2 = _phone_exec_vps(cmd)
            sys.stdout.write(out2)
            if err2.strip():
                sys.stderr.write(err2)
            return 0
        except Exception as e2:
            sys.stderr.write(f"VPS_FALLBACK_FAILED: {e2}\n")
            return 1
    sys.stdout.write(out)
    if err.strip():
        sys.stderr.write(err)
    return 0 if code == 0 else code


def _phone_exec_vps(command: str, timeout: int = 60) -> tuple[str, str]:
    import paramiko

    deploy = ROOT / "deploy_key"
    phone_key = ROOT / "_phone_remote" / "phone_id_ed25519"
    if not deploy.is_file() or not phone_key.is_file():
        raise RuntimeError("VPS keys missing")
    deploy_key = paramiko.Ed25519Key.from_private_key_file(str(deploy))
    jump = paramiko.SSHClient()
    jump.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    jump.connect(
        "185.228.92.23",
        username="root",
        pkey=deploy_key,
        timeout=15,
        allow_agent=False,
        look_for_keys=False,
    )
    sftp = jump.open_sftp()
    sftp.put(str(phone_key), "/root/.ssh/phone_access_key")
    sftp.chmod("/root/.ssh/phone_access_key", 0o600)
    sftp.close()
    remote = (
        "ssh -i /root/.ssh/phone_access_key -p 18022 "
        "-o BatchMode=yes -o StrictHostKeyChecking=no "
        f"-o UserKnownHostsFile=/dev/null u0@127.0.0.1 {command!r}"
    )
    _i, o, e = jump.exec_command(remote, timeout=timeout)
    out, err = o.read().decode(errors="replace"), e.read().decode(errors="replace")
    jump.close()
    return out, err


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
