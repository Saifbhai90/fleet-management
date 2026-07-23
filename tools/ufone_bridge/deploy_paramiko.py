#!/usr/bin/env python3
"""Deploy ufone-bridge to PK VPS via Paramiko (key or .vps_password)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent
HOST = os.environ.get('UFONE_VPS_HOST', '185.228.92.23')
USER = os.environ.get('UFONE_VPS_USER', 'root')
REMOTE = '/opt/ufone-bridge'
KEY = ROOT / 'deploy_key'
PUB = ROOT / 'deploy_key.pub'
PASS_FILE = ROOT / '.vps_password'


def connect() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = {}
    if KEY.is_file():
        kwargs['key_filename'] = str(KEY)
    if PASS_FILE.is_file():
        kwargs['password'] = PASS_FILE.read_text(encoding='utf-8').strip()
    if 'key_filename' not in kwargs and 'password' not in kwargs:
        raise SystemExit(
            f'No SSH auth.\n'
            f'  A) Put root password in {PASS_FILE}\n'
            f'  B) Or install this pubkey via WebSouls SSH Keys:\n'
            f'     {PUB.read_text(encoding="utf-8").strip()}'
        )
    last_err = None
    for attempt in range(3):
        try:
            client.connect(HOST, username=USER, timeout=20, allow_agent=False,
                           look_for_keys=False, **kwargs)
            return client
        except Exception as e:
            last_err = e
            time.sleep(2)
    raise SystemExit(f'SSH connect failed: {last_err}')


def run(client: paramiko.SSHClient, cmd: str, check: bool = True) -> str:
    print(f'$ {cmd}')
    _stdin, stdout, stderr = client.exec_command(cmd, timeout=300)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print(err.rstrip(), file=sys.stderr)
    if check and code != 0:
        raise SystemExit(f'Command failed ({code}): {cmd}')
    return out


def upload(client: paramiko.SSHClient, local: Path, remote: str) -> None:
    sftp = client.open_sftp()
    try:
        sftp.put(str(local), remote)
        print(f'↑ {local.name} → {remote}')
    finally:
        sftp.close()


def ensure_authorized_key(client: paramiko.SSHClient) -> None:
    if not PUB.is_file():
        return
    pub = PUB.read_text(encoding='utf-8').strip()
    run(client, 'mkdir -p ~/.ssh && chmod 700 ~/.ssh')
    # idempotent append
    run(client,
        f'grep -qxF {repr(pub)} ~/.ssh/authorized_keys 2>/dev/null || '
        f'echo {repr(pub)} >> ~/.ssh/authorized_keys')
    run(client, 'chmod 600 ~/.ssh/authorized_keys')


def main() -> int:
    client = connect()
    try:
        run(client, 'uname -a && echo SSH_OK')
        ensure_authorized_key(client)

        print('=== Ufone TLS probe ===')
        out = run(
            client,
            'curl -sS -o /dev/null -w "HTTP %{http_code} time=%{time_total}\\n" '
            '--connect-timeout 15 --max-time 40 '
            '-I https://bpocops.ufone.com/Login.aspx',
            check=False,
        )
        if 'HTTP 200' not in out and 'HTTP 30' not in out and 'HTTP 40' not in out:
            # Accept any HTTP response code that means TLS worked
            if 'HTTP ' not in out:
                raise SystemExit('Ufone TLS probe FAILED — no HTTP response from VPS')

        run(client, f'mkdir -p {REMOTE}/systemd {REMOTE}/sessions')
        files = [
            'worker.py', 'ufone_api_client.py', 'requirements.txt',
            'bootstrap.sh', '.env.example', 'README.md',
        ]
        for name in files:
            upload(client, ROOT / name, f'{REMOTE}/{name}')
        upload(client, ROOT / 'systemd' / 'ufone-bridge.service',
               f'{REMOTE}/systemd/ufone-bridge.service')
        env_local = ROOT / '.env'
        if env_local.is_file():
            upload(client, env_local, f'{REMOTE}/.env')
        else:
            print(f'WARN: {env_local} missing — bootstrap will fail until created')

        run(client, f'chmod +x {REMOTE}/bootstrap.sh && bash {REMOTE}/bootstrap.sh')
        print('Deploy complete.')
        return 0
    finally:
        client.close()


if __name__ == '__main__':
    raise SystemExit(main())
