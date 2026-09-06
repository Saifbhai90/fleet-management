# -*- coding: utf-8 -*-
import pathlib
import time

import paramiko

ROOT = pathlib.Path(r"f:/Laptop new hard drive Disk D/company_management/tools/ufone_bridge")
DEPLOY = ROOT / "deploy_key"
PHONE_KEY = ROOT / "_phone_remote" / "phone_id_ed25519"


def connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = paramiko.Ed25519Key.from_private_key_file(str(DEPLOY))
    client.connect(
        "185.228.92.23",
        username="root",
        pkey=pkey,
        timeout=25,
        allow_agent=False,
        look_for_keys=False,
    )
    return client


def run(client, cmd, timeout=40):
    _i, o, e = client.exec_command(cmd, timeout=timeout)
    out = o.read().decode(errors="replace")
    err = e.read().decode(errors="replace")
    print(cmd)
    print(out)
    if err.strip():
        print("ERR", err)
    print("---")
    return out, err


def main():
    client = connect()
    run(
        client,
        "ss -lntp | grep -E ':18022|:15555' || true; "
        "ps -fp 500744 || true",
    )
    # Kill the stale reverse-forward session explicitly
    run(client, "kill 500744 2>/dev/null || true; sleep 1; "
                "ss -lntp | grep -E ':18022|:15555' || echo PORTS_FREE")
    client.close()

    # Wait for phone to re-establish tunnel (started separately), then test
    time.sleep(6)
    client = connect()
    run(client, "ss -lntp | grep -E ':18022|:15555' || echo STILL_FREE")
    # Ensure phone key present
    if PHONE_KEY.exists():
        sftp = client.open_sftp()
        sftp.put(str(PHONE_KEY), "/root/.ssh/phone_access_key")
        sftp.chmod("/root/.ssh/phone_access_key", 0o600)
        sftp.close()
    out, err = run(
        client,
        "timeout 15 ssh -i /root/.ssh/phone_access_key -p 18022 "
        "-o BatchMode=yes -o StrictHostKeyChecking=no "
        "-o UserKnownHostsFile=/dev/null u0@127.0.0.1 "
        "'echo PHONE_OK; whoami; pwd; ls ufone-bridge | head -5'",
        timeout=25,
    )
    client.close()
    if "PHONE_OK" in out:
        print("SUCCESS_REMOTE_PHONE_ACCESS")
    else:
        print("FAIL_REMOTE_PHONE_ACCESS")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
