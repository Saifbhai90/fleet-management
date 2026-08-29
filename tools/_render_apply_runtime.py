"""Apply the intended runtime config to the live Render web service.

The service predates render.yaml and is not Blueprint-managed, so its start
command drifted to a bare `gunicorn app:app` (one sync worker, one thread, a 30
second timeout). This script pushes the Procfile/render.yaml command and the two
memory-related environment variables, then reports what the API stored.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

KEY = os.environ.get("RENDER_API_KEY") or ""
SERVICE = os.environ.get("RENDER_SERVICE_ID") or "srv-d6k81uk50q8c73eo53v0"

START_COMMAND = (
    "gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --worker-class gthread "
    "--threads 4 --timeout 300 --graceful-timeout 30 --keep-alive 5"
)
EXTRA_ENV = {
    "MALLOC_ARENA_MAX": "2",
    "MEMORY_LIMIT_MB": "512",
    "PYTHONUNBUFFERED": "1",
}


def req(method: str, path: str, body: object | None = None) -> object:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        "https://api.render.com" + path, data=data, method=method,
        headers={
            "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as resp:
            return json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as exc:
        print(f"FAIL {method} {path} -> {exc.code}: {exc.read().decode()[:600]}",
              file=sys.stderr)
        raise


def main() -> int:
    if not KEY:
        print("RENDER_API_KEY is not set", file=sys.stderr)
        return 1

    updated = req("PATCH", f"/v1/services/{SERVICE}", {
        "serviceDetails": {
            "envSpecificDetails": {"startCommand": START_COMMAND},
            "healthCheckPath": "/health",
        },
    })
    details = (updated or {}).get("serviceDetails") or {}
    print("startCommand   :", (details.get("envSpecificDetails") or {}).get("startCommand"))
    print("healthCheckPath:", details.get("healthCheckPath"))

    existing = req("GET", f"/v1/services/{SERVICE}/env-vars", None)
    current = {row["envVar"]["key"]: row["envVar"]["value"] for row in existing}
    for key, value in EXTRA_ENV.items():
        if current.get(key) == value:
            print(f"env {key} already {value}")
            continue
        req("PUT", f"/v1/services/{SERVICE}/env-vars/{key}", {"value": value})
        print(f"env {key} set to {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
