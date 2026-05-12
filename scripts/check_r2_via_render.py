"""Fetch R2 env from Render API (cli.yaml key), verify bucket with boto3. No secrets printed."""
import json
import os
import re
import sys
import urllib.request

import boto3
from botocore.config import Config


def _render_api_key():
    p = os.path.join(os.path.expanduser("~"), ".render", "cli.yaml")
    if not os.path.isfile(p):
        print("FAIL: ~/.render/cli.yaml missing (run: render login)", file=sys.stderr)
        sys.exit(2)
    t = open(p, encoding="utf-8").read()
    m = re.search(r"^\s*key:\s*(.+)$", t, re.MULTILINE)
    if not m:
        print("FAIL: could not parse Render API key from cli.yaml", file=sys.stderr)
        sys.exit(2)
    return m.group(1).strip()


def _fetch_env_map(service_id: str) -> dict[str, str]:
    url = f"https://api.render.com/v1/services/{service_id}/env-vars"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_render_api_key()}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    out = {}
    for item in data:
        ev = item.get("envVar") or {}
        k, v = ev.get("key"), ev.get("value")
        if k and v is not None:
            out[k] = v
    return out


def main():
    sid = os.environ.get("RENDER_SERVICE_ID", "srv-d6k81uk50q8c73eo53v0")
    env = _fetch_env_map(sid)
    need = ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT_URL", "R2_BUCKET_NAME", "R2_PUBLIC_URL")
    missing = [k for k in need if not env.get(k)]
    if missing:
        print("FAIL: missing env on Render:", ", ".join(missing))
        sys.exit(1)

    client = boto3.session.Session().client(
        "s3",
        region_name="auto",
        endpoint_url=env["R2_ENDPOINT_URL"].strip(),
        aws_access_key_id=env["R2_ACCESS_KEY_ID"].strip(),
        aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"].strip(),
        config=Config(signature_version="s3v4"),
    )
    bucket = env["R2_BUCKET_NAME"].strip()
    public_base = env["R2_PUBLIC_URL"].strip().rstrip("/")

    try:
        client.head_bucket(Bucket=bucket)
    except Exception as e:
        print("FAIL: head_bucket:", type(e).__name__, str(e)[:200])
        sys.exit(1)

    try:
        r = client.list_objects_v2(Bucket=bucket, MaxKeys=5)
        n = r.get("KeyCount", 0)
        keys = [x.get("Key", "") for x in (r.get("Contents") or [])]
        print("OK: R2 bucket reachable (head_bucket success).")
        print(f"OK: list_objects_v2 sample count={n}")
        for k in keys:
            if k:
                print("  object:", k[:120] + ("..." if len(k) > 120 else ""))
        print("OK: public URL base host parses (not fetching):", public_base.split("//")[-1][:60])
    except Exception as e:
        print("FAIL: list_objects_v2:", type(e).__name__, str(e)[:200])
        sys.exit(1)


if __name__ == "__main__":
    main()
