"""Restore prod→demo custom dump on Render (internal DB URL).

Requires:
  DEMO_MODE=1
  DATABASE_URL=<fleet-demo-db URL>
  DEMO_RESTORE_URL=<presigned/public URL to .dump>

Downloads PostgreSQL 18 client tools from Maven (zonky) when pg_restore
is not on PATH.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path


ZONKY_PG_RESTORE_JAR = (
    "https://repo1.maven.org/maven2/io/zonky/test/postgres/"
    "embedded-postgres-binaries-linux-amd64/18.4.0/"
    "embedded-postgres-binaries-linux-amd64-18.4.0.jar"
)


def _env_true(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _norm_db(url: str) -> str:
    url = (url or "").strip().replace("postgres://", "postgresql://", 1)
    if url and "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def _download(url: str, dest: Path) -> None:
    print(f"Downloading -> {dest.name} ({url[:80]}...)")
    with urllib.request.urlopen(url, timeout=600) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)


def _find_pg_restore(root: Path) -> Path | None:
    for p in root.rglob("pg_restore"):
        if p.is_file():
            p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            return p
    return None


def _ensure_pg_restore(work: Path) -> Path:
    which = shutil.which("pg_restore")
    if which:
        return Path(which)

    jar = work / "pg.binaries.jar"
    _download(ZONKY_PG_RESTORE_JAR, jar)
    extract = work / "pg_extract"
    extract.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar, "r") as zf:
        zf.extractall(extract)

    # jar often wraps a .txz / .tar.gz of the real binaries
    nested = None
    for pattern in ("*.txz", "*.tar.gz", "*.tgz", "*.tar"):
        hits = list(extract.rglob(pattern))
        if hits:
            nested = hits[0]
            break
    if nested:
        out = work / "pg_bin"
        out.mkdir(parents=True, exist_ok=True)
        if nested.suffix == ".txz" or nested.name.endswith(".tar.xz"):
            # Python 3.12+ may not have xz in tarfile on all builds — use tar command
            subprocess.run(
                ["tar", "-xJf", str(nested), "-C", str(out)],
                check=True,
            )
        else:
            with tarfile.open(nested, "r:*") as tf:
                tf.extractall(out)
        found = _find_pg_restore(out)
        if found:
            return found

    found = _find_pg_restore(extract)
    if found:
        return found
    raise SystemExit("pg_restore not found inside zonky binaries jar")


def _already_populated(database_url: str) -> bool:
    try:
        import psycopg2
    except ImportError:
        return False
    try:
        conn = psycopg2.connect(database_url, connect_timeout=30)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema='public' AND table_name='vehicle'
            """
        )
        if not cur.fetchone():
            conn.close()
            return False
        cur.execute("SELECT COUNT(*) FROM vehicle")
        n = int(cur.fetchone()[0])
        conn.close()
        return n > 10
    except Exception as exc:
        print("populate check:", exc)
        return False


def _wipe_public_schema(database_url: str) -> None:
    """Drop all demo objects so restore cannot collide with sample-seed rows."""
    import psycopg2

    print("Wiping demo public schema (DROP SCHEMA public CASCADE)...")
    conn = psycopg2.connect(database_url, connect_timeout=60)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
    cur.execute("CREATE SCHEMA public")
    cur.execute("GRANT ALL ON SCHEMA public TO CURRENT_USER")
    cur.execute("GRANT ALL ON SCHEMA public TO PUBLIC")
    conn.close()
    print("Schema wipe done")


def _ensure_demo_login(database_url: str) -> None:
    import psycopg2
    from werkzeug.security import generate_password_hash

    pw = generate_password_hash("Demo#2026")
    conn = psycopg2.connect(database_url, connect_timeout=30)
    conn.autocommit = True
    cur = conn.cursor()
    # Prod dump may leave force_password_change NULL; relax + backfill
    try:
        cur.execute(
            'ALTER TABLE "user" ALTER COLUMN force_password_change DROP NOT NULL'
        )
    except Exception:
        pass
    try:
        cur.execute(
            """
            UPDATE "user"
            SET force_password_change = false
            WHERE force_password_change IS NULL
            """
        )
    except Exception as exc:
        print("force_password_change backfill:", exc)

    cur.execute("SELECT id FROM role WHERE name='Master' LIMIT 1")
    row = cur.fetchone()
    if not row:
        print("WARNING: Master role missing")
        conn.close()
        return
    role_id = row[0]
    cur.execute('SELECT id FROM "user" WHERE username=%s LIMIT 1', ("demo",))
    u = cur.fetchone()
    if u:
        cur.execute(
            """
            UPDATE "user"
            SET role_id=%s, password_hash=%s, is_active=true,
                force_password_change=false,
                full_name=COALESCE(NULLIF(full_name, ''), 'Demo Master (Developer)')
            WHERE id=%s
            """,
            (role_id, pw, u[0]),
        )
    else:
        cur.execute(
            """
            INSERT INTO "user"
              (username, password_hash, full_name, role_id, is_active, force_password_change)
            VALUES ('demo', %s, 'Demo Master (Developer)', %s, true, false)
            """,
            (pw, role_id),
        )
    conn.close()
    print("Login ready: demo / Demo#2026 (Master)")


def main() -> int:
    if not _env_true("DEMO_MODE"):
        print("DEMO_MODE off — refuse")
        return 2
    restore_url = (os.environ.get("DEMO_RESTORE_URL") or "").strip()
    database_url = _norm_db(os.environ.get("DATABASE_URL") or "")
    if not restore_url or not database_url:
        print("DEMO_RESTORE_URL and DATABASE_URL required")
        return 2
    if "company_management_w27v" in database_url or "dpg-d6k6omn5r7bs73a8crcg" in database_url:
        print("Refusing production DATABASE_URL")
        return 3

    if not _env_true("DEMO_RESTORE_FORCE") and _already_populated(database_url):
        print("Demo already populated — ensuring login only")
        _ensure_demo_login(database_url)
        return 0

    with tempfile.TemporaryDirectory(prefix="demo_restore_") as td:
        work = Path(td)
        dump = work / "prod.dump"
        _download(restore_url, dump)
        size_mb = dump.stat().st_size / (1024 * 1024)
        print(f"Dump size: {size_mb:.1f} MB")
        if dump.stat().st_size < 1_000_000:
            print("Dump too small")
            return 4

        # Avoid duplicate-key / FK chaos from leftover sample seed or half-restores
        _wipe_public_schema(database_url)

        pg_restore = _ensure_pg_restore(work)
        print("Using", pg_restore)
        cmd = [
            str(pg_restore),
            "--verbose",
            "--no-owner",
            "--no-acl",
            f"--dbname={database_url}",
            str(dump),
        ]
        print("Running pg_restore...")
        proc = subprocess.run(cmd, check=False)
        print("pg_restore exit:", proc.returncode)
        if proc.returncode not in (0, 1):
            return proc.returncode

    _ensure_demo_login(database_url)
    print("RESTORE_DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
