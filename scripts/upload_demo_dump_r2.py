"""Upload local prod dump to R2 for demo restore. Run from repo root."""
from __future__ import annotations

from pathlib import Path

from botocore.config import Config
import boto3


def _load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    env = _load_env(root / ".env")
    dump = root / "tmp" / "prod_to_demo_latest.dump"
    if not dump.is_file() or dump.stat().st_size < 1_000_000:
        raise SystemExit(f"Missing/small dump: {dump}")

    s3 = boto3.client(
        "s3",
        endpoint_url=env["R2_ENDPOINT_URL"],
        aws_access_key_id=env["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )
    key = "demo-clone/prod_to_demo_latest.dump"
    bucket = env["R2_BUCKET_NAME"]
    print(f"Uploading {dump.stat().st_size} bytes to s3://{bucket}/{key} ...")
    s3.upload_file(
        str(dump),
        bucket,
        key,
        ExtraArgs={"ContentType": "application/octet-stream"},
    )
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=86400,
    )
    print("UPLOAD_OK")
    print(url)


if __name__ == "__main__":
    main()
