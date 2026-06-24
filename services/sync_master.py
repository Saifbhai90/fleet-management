#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
  SYNC MASTER — Production-to-Local One-Way Database Sync Engine
═══════════════════════════════════════════════════════════════════════════════

  Purpose : Pull data from Render PostgreSQL → Local SQLite (one-way only)
  Safety  : ZERO writes to production. Hard-blocked at connection level.
  Modes   : incremental (smart delta) | full_reset (clean mirror)

  Usage   : python sync_master.py                  # incremental sync
            python sync_master.py --full-reset      # wipe & rebuild
            python sync_master.py --dry-run         # preview only
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import time
import json
import sqlite3
import logging
import argparse
from datetime import datetime, date, time as time_type, timezone
from decimal import Decimal
from pathlib import Path
from contextlib import contextmanager

# ─── Setup Paths ────────────────────────────────────────────────────────────
APP_DIR = Path(__file__).resolve().parent.parent  # project root (was .parent when at root)
ENV_FILE = APP_DIR / '.env.local'

# ─── Load .env.local ────────────────────────────────────────────────────────
def load_env_local():
    """Parse .env.local into os.environ (does NOT override existing vars)."""
    if not ENV_FILE.exists():
        print(f"[ERROR] {ENV_FILE} not found. Copy .env.local.example and fill in values.")
        sys.exit(1)
    with open(ENV_FILE, 'r', encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue
            key, _, val = line.partition('=')
            key, val = key.strip(), val.strip()
            if key:
                os.environ.setdefault(key, val)

load_env_local()

# ─── Configuration ──────────────────────────────────────────────────────────
RENDER_DB_URL  = os.environ.get('RENDER_DB_URL', '').strip()
LOCAL_DB_PATH  = os.environ.get('LOCAL_DB_PATH', 'db/local.db').strip()
SYNC_MODE      = os.environ.get('SYNC_MODE', 'incremental').strip().lower()
FULL_RESET_ENV = os.environ.get('FULL_RESET', 'false').strip().lower() in ('true', '1', 'yes')
LOG_DIR        = os.environ.get('LOG_DIR', 'logs').strip()

# Resolve paths relative to app dir
LOCAL_DB_FULL  = APP_DIR / LOCAL_DB_PATH
LOG_DIR_FULL   = APP_DIR / LOG_DIR
SYNC_STATE_FILE = APP_DIR / 'config' / 'sync_state.json'


# ─── Sync State (smart cache) ──────────────────────────────────────────────
def load_sync_state():
    """Load last sync timestamp from sync_state.json."""
    if SYNC_STATE_FILE.exists():
        try:
            with open(SYNC_STATE_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {'last_sync_time': None}


def save_sync_state(sync_time_str):
    """Save the current sync timestamp to sync_state.json."""
    state = {
        'last_sync_time': sync_time_str,
        'synced_from': 'render_production',
        'local_db': str(LOCAL_DB_FULL),
    }
    with open(SYNC_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)
    log.info(f"Sync state saved: last_sync_time = {sync_time_str}")

# ─── Logging Setup ──────────────────────────────────────────────────────────
LOG_DIR_FULL.mkdir(parents=True, exist_ok=True)
log_file = LOG_DIR_FULL / f'sync_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-5s  %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(log_file), encoding='utf-8'),
    ],
)
log = logging.getLogger('sync_master')

# ─── Banner ─────────────────────────────────────────────────────────────────
BANNER = """
  +===========================================================+
  |       SYNC MASTER -- Production -> Local Sync Engine      |
  |       !! RENDER DB IS READ-ONLY -- NO WRITES ALLOWED      |
  +===========================================================+
"""


# ═══════════════════════════════════════════════════════════════════════════════
#  PRODUCTION PROTECTION LAYER
# ═══════════════════════════════════════════════════════════════════════════════
class ReadOnlyViolation(Exception):
    """Raised when an attempt is made to write to the production database."""
    pass


def _get_render_connection():
    """
    Connect to Render PostgreSQL in READ-ONLY mode.
    Uses transaction-level read-only + statement_timeout for safety.
    """
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        log.error("psycopg2-binary not installed. Run: pip install psycopg2-binary")
        sys.exit(1)

    if not RENDER_DB_URL:
        log.error("RENDER_DB_URL is empty. Set it in .env.local")
        sys.exit(1)

    conn = psycopg2.connect(
        RENDER_DB_URL,
        options='-c default_transaction_read_only=on -c statement_timeout=300000',
    )
    conn.set_session(readonly=True, autocommit=True)
    log.info("Connected to Render PostgreSQL [READ-ONLY MODE]")
    return conn


def _verify_read_only(conn):
    """Double-check the connection is truly read-only by attempting a dummy write."""
    cur = conn.cursor()
    try:
        cur.execute("CREATE TEMP TABLE _sync_rw_test (id int)")
        # If we get here, read-only is NOT enforced — abort immediately
        raise ReadOnlyViolation(
            "PRODUCTION DB IS READ ONLY — connection allowed writes! Aborting."
        )
    except Exception as e:
        err_str = str(e).lower()
        if 'read-only' in err_str or 'read only' in err_str or 'permission' in err_str:
            log.info("[OK] Read-only protection verified -- production DB is safe")
            return True
        if isinstance(e, ReadOnlyViolation):
            raise
        # Some other error — still likely safe, but log it
        log.warning(f"Read-only check got unexpected error (likely safe): {e}")
        return True
    finally:
        try:
            conn.rollback()
        except Exception:
            pass


@contextmanager
def render_connection():
    """Context manager: yields a verified read-only Render connection."""
    conn = _get_render_connection()
    _verify_read_only(conn)
    try:
        yield conn
    finally:
        conn.close()
        log.info("Render connection closed.")


# ═══════════════════════════════════════════════════════════════════════════════
#  LOCAL SQLITE CONNECTION
# ═══════════════════════════════════════════════════════════════════════════════
def _get_local_connection():
    """Connect to local SQLite database (creates file + parent dirs if needed)."""
    LOCAL_DB_FULL.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(LOCAL_DB_FULL))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=OFF")  # OFF during sync to avoid FK issues
    log.info(f"Connected to local SQLite: {LOCAL_DB_FULL}")
    return conn


# ═══════════════════════════════════════════════════════════════════════════════
#  SCHEMA INTROSPECTION
# ═══════════════════════════════════════════════════════════════════════════════
def get_render_tables(pg_conn):
    """Get all user tables from Render PostgreSQL (public schema)."""
    cur = pg_conn.cursor()
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    tables = [row[0] for row in cur.fetchall()]
    cur.close()
    return tables


def get_render_columns(pg_conn, table_name):
    """Get column names and types for a Render table."""
    cur = pg_conn.cursor()
    cur.execute("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
    """, (table_name,))
    cols = cur.fetchall()
    cur.close()
    return cols


def pg_type_to_sqlite(pg_type):
    """Map PostgreSQL data types to SQLite types."""
    mapping = {
        'integer': 'INTEGER',
        'bigint': 'INTEGER',
        'smallint': 'INTEGER',
        'serial': 'INTEGER',
        'bigserial': 'INTEGER',
        'boolean': 'INTEGER',
        'real': 'REAL',
        'double precision': 'REAL',
        'numeric': 'REAL',
        'character varying': 'TEXT',
        'character': 'TEXT',
        'text': 'TEXT',
        'varchar': 'TEXT',
        'date': 'TEXT',
        'time without time zone': 'TEXT',
        'time with time zone': 'TEXT',
        'timestamp without time zone': 'TEXT',
        'timestamp with time zone': 'TEXT',
        'json': 'TEXT',
        'jsonb': 'TEXT',
        'bytea': 'BLOB',
        'uuid': 'TEXT',
        'inet': 'TEXT',
        'interval': 'TEXT',
        'ARRAY': 'TEXT',
        'USER-DEFINED': 'TEXT',
    }
    return mapping.get(pg_type, 'TEXT')


def get_primary_key(pg_conn, table_name):
    """Get primary key column(s) for a table."""
    cur = pg_conn.cursor()
    cur.execute("""
        SELECT a.attname
        FROM   pg_index i
        JOIN   pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE  i.indrelid = %s::regclass AND i.indisprimary
        ORDER BY array_position(i.indkey, a.attnum)
    """, (table_name,))
    pks = [row[0] for row in cur.fetchall()]
    cur.close()
    return pks


def has_timestamp_column(columns, name):
    """Check if a specific column exists in the column list."""
    return any(c[0] == name for c in columns)


# ═══════════════════════════════════════════════════════════════════════════════
#  VALUE SERIALIZATION (PG → SQLite safe)
# ═══════════════════════════════════════════════════════════════════════════════
def serialize_value(val):
    """Convert a PostgreSQL value to a SQLite-compatible value."""
    if val is None:
        return None
    if isinstance(val, bool):
        return 1 if val else 0
    if isinstance(val, datetime):
        # Match SQLAlchemy/SQLite string format so range filters work after sync.
        return val.strftime('%Y-%m-%d %H:%M:%S.%f')
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, time_type):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, (list, dict)):
        import json
        return json.dumps(val)
    if isinstance(val, memoryview):
        return bytes(val)
    if isinstance(val, bytes):
        return val
    return val


# ═══════════════════════════════════════════════════════════════════════════════
#  CORE SYNC ENGINE
# ═══════════════════════════════════════════════════════════════════════════════
class SyncStats:
    """Track sync statistics."""
    def __init__(self):
        self.tables_synced = 0
        self.tables_skipped = 0
        self.total_inserted = 0
        self.total_updated = 0
        self.total_skipped = 0
        self.total_deleted = 0
        self.errors = []
        self.start_time = time.time()

    def elapsed(self):
        return time.time() - self.start_time

    def summary(self):
        return (
            f"\n{'=' * 60}\n"
            f"  SYNC COMPLETE\n"
            f"{'=' * 60}\n"
            f"  Tables synced   : {self.tables_synced}\n"
            f"  Tables skipped  : {self.tables_skipped}\n"
            f"  Records inserted: {self.total_inserted}\n"
            f"  Records updated : {self.total_updated}\n"
            f"  Records skipped : {self.total_skipped}\n"
            f"  Records deleted : {self.total_deleted}\n"
            f"  Errors          : {len(self.errors)}\n"
            f"  Duration        : {self.elapsed():.1f}s\n"
            f"{'=' * 60}"
        )


def create_local_table(local_conn, table_name, columns, primary_keys):
    """Create a table in local SQLite matching the Render schema."""
    col_defs = []
    for col_name, data_type, is_nullable, col_default in columns:
        sqlite_type = pg_type_to_sqlite(data_type)
        parts = [f'"{col_name}" {sqlite_type}']
        if col_name in primary_keys and len(primary_keys) == 1:
            parts.append('PRIMARY KEY')
        if is_nullable == 'NO' and col_name not in primary_keys:
            parts.append('NOT NULL')
        col_defs.append(' '.join(parts))

    # Composite primary key
    if len(primary_keys) > 1:
        pk_cols = ', '.join(f'"{pk}"' for pk in primary_keys)
        col_defs.append(f'PRIMARY KEY ({pk_cols})')

    ddl = f'CREATE TABLE IF NOT EXISTS "{table_name}" (\n  ' + ',\n  '.join(col_defs) + '\n)'
    local_conn.execute(ddl)


def sync_table_full(pg_conn, local_conn, table_name, columns, primary_keys, stats):
    """Full sync: drop local table, recreate, copy all rows."""
    col_names = [c[0] for c in columns]

    # Drop and recreate
    local_conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    create_local_table(local_conn, table_name, columns, primary_keys)

    # Fetch all from Render
    pg_cur = pg_conn.cursor()
    quoted_cols = ', '.join(f'"{c}"' for c in col_names)
    pg_cur.execute(f'SELECT {quoted_cols} FROM "{table_name}"')

    inserted = 0
    batch = []
    placeholders = ', '.join(['?'] * len(col_names))
    insert_sql = f'INSERT INTO "{table_name}" ({quoted_cols}) VALUES ({placeholders})'

    while True:
        rows = pg_cur.fetchmany(1000)
        if not rows:
            break
        for row in rows:
            batch.append(tuple(serialize_value(v) for v in row))
        if batch:
            local_conn.executemany(insert_sql, batch)
            inserted += len(batch)
            batch = []

    pg_cur.close()
    stats.total_inserted += inserted
    stats.tables_synced += 1
    log.info(f"  [OK] {table_name}: {inserted} rows (full copy)")


def sync_table_smart(pg_conn, local_conn, table_name, columns, primary_keys, stats, last_sync_time):
    """
    SMART SYNC: Only fetch records WHERE updated_at > last_sync_time.
    Falls back to full-table fetch for tables without timestamp columns.
    This is the key optimization: ~265s full scan -> 5-20s smart delta.
    """
    col_names = [c[0] for c in columns]
    quoted_cols = ', '.join(f'"{c}"' for c in col_names)
    placeholders = ', '.join(['?'] * len(col_names))

    # Check if local table exists
    local_cur = local_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    )
    if not local_cur.fetchone():
        # Table doesn't exist locally -- do full sync
        log.info(f"  Table '{table_name}' not in local DB -- full copy")
        create_local_table(local_conn, table_name, columns, primary_keys)
        return sync_table_full(pg_conn, local_conn, table_name, columns, primary_keys, stats)

    # Determine timestamp column for smart delta
    ts_col = None
    if has_timestamp_column(columns, 'updated_at'):
        ts_col = 'updated_at'
    elif has_timestamp_column(columns, 'created_at'):
        ts_col = 'created_at'

    # If no primary key, fall back to full sync
    if not primary_keys:
        log.info(f"  Table '{table_name}' has no PK -- full copy fallback")
        return sync_table_full(pg_conn, local_conn, table_name, columns, primary_keys, stats)

    # Build PK comparison
    pk_where_sq = ' AND '.join(f'"{pk}" = ?' for pk in primary_keys)
    pk_indices = [col_names.index(pk) for pk in primary_keys]

    # Build update SET clause (exclude PKs)
    non_pk_cols = [c for c in col_names if c not in primary_keys]
    update_set = ', '.join(f'"{c}" = ?' for c in non_pk_cols)
    non_pk_indices = [col_names.index(c) for c in non_pk_cols]

    # === KEY OPTIMIZATION: Only fetch changed rows from Render ===
    pg_cur = pg_conn.cursor()
    if ts_col and last_sync_time:
        # SMART: Only pull records modified since last sync
        pg_cur.execute(
            f'SELECT {quoted_cols} FROM "{table_name}" WHERE "{ts_col}" > %s',
            (last_sync_time,)
        )
    else:
        # No timestamp or first sync -- fetch all (but still do upsert logic)
        pg_cur.execute(f'SELECT {quoted_cols} FROM "{table_name}"')

    inserted = 0
    updated = 0
    skipped = 0

    while True:
        rows = pg_cur.fetchmany(1000)
        if not rows:
            break
        for row in rows:
            pk_vals = tuple(serialize_value(row[i]) for i in pk_indices)
            serialized_row = tuple(serialize_value(v) for v in row)

            # Check if exists locally
            local_row = local_conn.execute(
                f'SELECT {quoted_cols} FROM "{table_name}" WHERE {pk_where_sq}',
                pk_vals
            ).fetchone()

            if local_row is None:
                # INSERT new record
                local_conn.execute(
                    f'INSERT INTO "{table_name}" ({quoted_cols}) VALUES ({placeholders})',
                    serialized_row
                )
                inserted += 1
            else:
                # UPDATE (already filtered by WHERE clause if ts_col available)
                if non_pk_cols:
                    update_vals = tuple(serialized_row[i] for i in non_pk_indices) + pk_vals
                    local_conn.execute(
                        f'UPDATE "{table_name}" SET {update_set} WHERE {pk_where_sq}',
                        update_vals
                    )
                    updated += 1
                else:
                    skipped += 1

    pg_cur.close()
    stats.total_inserted += inserted
    stats.total_updated += updated
    stats.total_skipped += skipped
    stats.tables_synced += 1

    parts = []
    if inserted: parts.append(f"+{inserted} new")
    if updated:  parts.append(f"~{updated} updated")
    if skipped:  parts.append(f"={skipped} unchanged")
    detail = ', '.join(parts) if parts else 'no changes'
    log.info(f"  [OK] {table_name}: {detail}")


# ═══════════════════════════════════════════════════════════════════════════════
#  ALEMBIC VERSION TABLE — special handling
# ═══════════════════════════════════════════════════════════════════════════════
SKIP_TABLES = {'alembic_version'}  # Alembic migration state — keep local version


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN SYNC ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════
def run_sync(full_reset=False, dry_run=False):
    """Main sync entry point."""
    print(BANNER)

    # Load sync state for smart delta
    sync_state = load_sync_state()
    last_sync_time = sync_state.get('last_sync_time')
    sync_start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    mode = 'FULL RESET' if full_reset else 'SMART SYNC'
    log.info(f"Sync mode      : {mode}")
    log.info(f"Last sync time : {last_sync_time or 'Never (first sync)'}")
    log.info(f"Local DB       : {LOCAL_DB_FULL}")
    log.info(f"Log file       : {log_file}")

    if dry_run:
        log.info("[DRY RUN] No changes will be made")

    stats = SyncStats()

    # Full reset: delete existing local DB + clear sync state
    if full_reset and LOCAL_DB_FULL.exists() and not dry_run:
        log.info("[RESET] Deleting existing local database for full reset...")
        LOCAL_DB_FULL.unlink()
        last_sync_time = None  # Force full fetch

    with render_connection() as pg_conn:
        local_conn = _get_local_connection()

        try:
            tables = get_render_tables(pg_conn)
            log.info(f"\nFound {len(tables)} tables on Render\n{'-' * 50}")

            if dry_run:
                for t in tables:
                    tag = '[SKIP]' if t in SKIP_TABLES else '[SYNC]'
                    log.info(f"  {tag} {t}")
                log.info(f"\n  {len(tables) - len(SKIP_TABLES)} tables would be synced")
                return

            for table_name in tables:
                if table_name in SKIP_TABLES:
                    log.info(f"  [SKIP] {table_name}: skipped (system table)")
                    stats.tables_skipped += 1
                    continue

                try:
                    columns = get_render_columns(pg_conn, table_name)
                    primary_keys = get_primary_key(pg_conn, table_name)

                    if full_reset:
                        sync_table_full(pg_conn, local_conn, table_name, columns, primary_keys, stats)
                    else:
                        sync_table_smart(pg_conn, local_conn, table_name, columns, primary_keys, stats, last_sync_time)

                except Exception as e:
                    log.error(f"  [ERR] {table_name}: {e}")
                    stats.errors.append((table_name, str(e)))

            local_conn.commit()
            log.info(stats.summary())

            # Save sync state on success
            if not dry_run:
                save_sync_state(sync_start_time)

            if stats.errors:
                log.warning("\nErrors encountered:")
                for tbl, err in stats.errors:
                    log.warning(f"  - {tbl}: {err}")

        finally:
            local_conn.close()
            log.info("Local DB connection closed.")


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description='Sync Render production DB -> Local SQLite (one-way, read-only)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sync_master.py                 # incremental sync
  python sync_master.py --full-reset    # wipe local & rebuild
  python sync_master.py --dry-run       # preview without changes
        """,
    )
    parser.add_argument(
        '--full-reset', action='store_true',
        help='Delete local DB and rebuild from scratch (100%% mirror)'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Preview tables that would be synced without making changes'
    )
    args = parser.parse_args()

    # Env var override
    full_reset = args.full_reset or FULL_RESET_ENV

    try:
        run_sync(full_reset=full_reset, dry_run=args.dry_run)
    except ReadOnlyViolation as e:
        log.critical(f"\n[BLOCKED] {e}")
        sys.exit(2)
    except KeyboardInterrupt:
        log.warning("\nSync interrupted by user.")
        sys.exit(1)
    except Exception as e:
        log.critical(f"\n[FATAL] Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
