#!/usr/bin/env python3
"""
FleetManager — Production Database Cleanup Script
==================================================
Wipes ALL dummy/test data from the PostgreSQL database before go-live.

KEEPS:  user, role, permission, role_permissions,
        district, driver_post, product, attendance_time_control

WIPES:  all transactional, task, transfer, expense, entity, and log data.

Usage (Render Shell or local):
    python cleanup_prod.py           # interactive (asks for confirmation)
    python cleanup_prod.py --yes     # skip confirmation prompt (CI / Render one-shot)

Flask CLI (optional):
    flask cleanup-prod               # interactive
    flask cleanup-prod --yes         # skip confirmation
"""

import sys
import os

# ─── Insertion order: children deleted FIRST so FK constraints are satisfied ──
# When TRUNCATE is used, the full list is sent in one statement (PostgreSQL
# handles inter-table FKs automatically when all referenced tables are listed).
WIPE_TABLES = [
    # ── Attachments & line items (deepest children) ──────────────────────────
    'oil_expense_attachment',
    'oil_expense_item',
    'maintenance_expense_attachment',
    'maintenance_expense_item',
    'employee_document',

    # ── Audit / session logs ─────────────────────────────────────────────────
    'activity_log',       # ActivityLog   (tablename = 'activity_log')
    'activity_logs',      # ClientActivityLog (tablename = 'activity_logs')
    'notification_read',

    # ── Transactional records ─────────────────────────────────────────────────
    'driver_attendance',
    'driver_status_change',
    'driver_transfer',
    'vehicle_transfer',
    'project_transfer',
    'penalty_record',
    'vehicle_daily_task',
    'emergency_task_record',
    'vehicle_mileage_record',
    'red_task',
    'vehicle_move_without_task',

    # ── Expense tables ────────────────────────────────────────────────────────
    'fuel_expense',
    'oil_expense',
    'maintenance_expense',
    'product_balance',       # reset stock to zero (products themselves are kept)

    # ── User-scoped data (users are kept, their data is wiped) ────────────────
    'notification',
    'reminder',
    'login_log',

    # ── Many-to-many association tables ──────────────────────────────────────
    'employee_project',
    'employee_district',
    'vehicle_district',
    'project_district',

    # ── Master entity tables ──────────────────────────────────────────────────
    'employee',
    'driver',
    'vehicle',
    'parking_station',
    'party',
    'project',
    'company',
]

KEEP_TABLES = [
    'user',
    'role',
    'permission',
    'role_permissions',
    'district',
    'driver_post',
    'product',
    'attendance_time_control',
]


def _get_row_counts(conn, tables):
    from sqlalchemy import text
    counts = {}
    for tbl in tables:
        try:
            row = conn.execute(text(f'SELECT COUNT(*) FROM "{tbl}"')).fetchone()
            counts[tbl] = row[0]
        except Exception as e:
            counts[tbl] = f'ERROR: {e}'
    return counts


def run_cleanup(yes=False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app import app, db
    from sqlalchemy import text

    with app.app_context():
        print()
        print('═' * 64)
        print('  FleetManager — Production Database Cleanup')
        print('═' * 64)

        # ── Show current counts ───────────────────────────────────────────────
        print('\n  Tables to be WIPED:\n')
        with db.engine.connect() as conn:
            counts = _get_row_counts(conn, WIPE_TABLES)

        has_data = False
        for tbl in WIPE_TABLES:
            val = counts[tbl]
            if isinstance(val, int) and val > 0:
                print(f'    {tbl:<42} {val:>7,} rows')
                has_data = True
            elif isinstance(val, str):
                print(f'    {tbl:<42} [skipped — {val}]')

        total = sum(v for v in counts.values() if isinstance(v, int))
        print(f'\n    {"TOTAL ROWS TO DELETE":<42} {total:>7,}')

        if total == 0:
            print('\n  ✓ All wipe-tables already empty. Nothing to do.\n')
            return

        print('\n  Tables to be KEPT:\n')
        with db.engine.connect() as conn:
            keep_counts = _get_row_counts(conn, KEEP_TABLES)
        for tbl in KEEP_TABLES:
            val = keep_counts.get(tbl, '?')
            print(f'    ✓ {tbl:<42} {val if isinstance(val, int) else "N/A":>7} rows preserved')

        # ── Confirmation ──────────────────────────────────────────────────────
        if not yes:
            print()
            print('─' * 64)
            print('  ⚠  WARNING: This action is IRREVERSIBLE.')
            print('  ⚠  Make sure you have a database backup before proceeding.')
            print('─' * 64)
            try:
                confirm = input('\n  Type  YES  (all caps) to proceed: ').strip()
            except KeyboardInterrupt:
                print('\n\n  Aborted.')
                sys.exit(0)
            if confirm != 'YES':
                print('\n  Aborted. No changes made.')
                sys.exit(0)

        # ── Execute TRUNCATE ──────────────────────────────────────────────────
        print('\n  Truncating tables...')

        # List only tables that exist (no ERROR counts)
        valid_tables = [t for t in WIPE_TABLES if isinstance(counts.get(t), int)]
        tbl_csv = ', '.join(f'"{t}"' for t in valid_tables)

        try:
            with db.engine.begin() as conn:
                conn.execute(text(f'TRUNCATE TABLE {tbl_csv} RESTART IDENTITY CASCADE'))
            print('  ✓ TRUNCATE ... RESTART IDENTITY CASCADE — success')
        except Exception as truncate_err:
            print(f'  ✗ TRUNCATE failed: {truncate_err}')
            print('  → Falling back to table-by-table DELETE...\n')
            _fallback_delete(db, valid_tables)
            _reset_sequences(db)

        # ── Verify ────────────────────────────────────────────────────────────
        print('\n  Verifying...\n')
        errors = []
        with db.engine.connect() as conn:
            post_counts = _get_row_counts(conn, WIPE_TABLES)

        for tbl in WIPE_TABLES:
            val = post_counts[tbl]
            if isinstance(val, int) and val == 0:
                print(f'    ✓ {tbl}')
            elif isinstance(val, int) and val > 0:
                print(f'    ✗ {tbl} — still has {val} rows!')
                errors.append(tbl)
            else:
                print(f'    ? {tbl} — {val}')

        # ── Summary ───────────────────────────────────────────────────────────
        print()
        print('═' * 64)
        if errors:
            print(f'  ✗ Cleanup INCOMPLETE — {len(errors)} table(s) not fully cleared:')
            for t in errors:
                print(f'     • {t}')
        else:
            print('  ✓ Cleanup COMPLETE — database is ready for production.')
        print('═' * 64)
        print()


def _fallback_delete(db, tables):
    """Row-by-row DELETE fallback if TRUNCATE fails (rare permission edge case)."""
    from sqlalchemy import text
    for tbl in tables:
        try:
            with db.engine.begin() as conn:
                result = conn.execute(text(f'DELETE FROM "{tbl}"'))
                print(f'    ✓ DELETE {tbl:<38} {result.rowcount:>7,} rows removed')
        except Exception as e:
            print(f'    ✗ DELETE {tbl:<38} {e}')


def _reset_sequences(db):
    """Reset ALL public sequences to 1 after a fallback DELETE run."""
    from sqlalchemy import text
    print('\n  Resetting sequences...')
    with db.engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT sequence_name FROM information_schema.sequences "
            "WHERE sequence_schema = 'public'"
        )).fetchall()
    for (seq_name,) in rows:
        try:
            with db.engine.begin() as conn:
                conn.execute(text(f'ALTER SEQUENCE "{seq_name}" RESTART WITH 1'))
            print(f'    ✓ RESET {seq_name}')
        except Exception as e:
            print(f'    ✗ {seq_name}: {e}')


# ─── Flask CLI registration (called from app.py or run.py) ───────────────────
def register_cleanup_command(flask_app):
    """
    Call this in app.py AFTER app is created:
        from cleanup_prod import register_cleanup_command
        register_cleanup_command(app)
    Then run: flask cleanup-prod [--yes]
    """
    try:
        import click

        @flask_app.cli.command('cleanup-prod')
        @click.option('--yes', is_flag=True, default=False,
                      help='Skip the YES confirmation prompt.')
        def _cleanup_prod_cmd(yes):
            """Wipe all dummy/test data and reset sequences. Run once before go-live."""
            run_cleanup(yes=yes)
    except ImportError:
        pass  # click not available — standalone mode only


# ─── Standalone entry point ───────────────────────────────────────────────────
if __name__ == '__main__':
    yes_flag = '--yes' in sys.argv or '-y' in sys.argv
    run_cleanup(yes=yes_flag)
