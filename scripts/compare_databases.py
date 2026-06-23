"""Compare local SQLite vs online PostgreSQL Fleet Management databases.

Usage:
    LOCAL_DATABASE_URL=sqlite:///db/local.db
    ONLINE_DATABASE_URL=postgresql://...  (from Render dashboard)
    python scripts/compare_databases.py

Or:
    python scripts/compare_databases.py "sqlite:///db/local.db" "postgresql://user:pass@host/db"
"""
import os
import sys
from decimal import Decimal
from collections import defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Load .env.local the same way sync_master.py does
ENV_FILE = os.path.join(ROOT, '.env.local')
if os.path.exists(ENV_FILE):
    with open(ENV_FILE, 'r', encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, val = line.partition('=')
            key, val = key.strip(), val.strip()
            if key:
                os.environ.setdefault(key, val)

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def get_engine(uri):
    uri = uri.strip()
    if uri.startswith("postgres://"):
        uri = "postgresql://" + uri[9:]
    return create_engine(uri)


def table_counts(sess, tables):
    out = {}
    for t in tables:
        try:
            out[t] = sess.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
        except Exception as e:
            out[t] = f"ERROR: {e}"
    return out


def driver_status_summary(sess):
    rows = sess.execute(
        text("SELECT status, COUNT(*) FROM driver GROUP BY status")
    ).all()
    return {r[0]: r[1] for r in rows}


def workspace_summary(sess, employee_id):
    """Return workspace totals for a specific employee."""
    # Expense sources
    fuel = sess.execute(
        text("SELECT COALESCE(SUM(amount), 0) FROM fuel_expense WHERE employee_id = :eid"),
        {"eid": employee_id},
    ).scalar()
    oil = sess.execute(
        text("SELECT COALESCE(SUM(total_bill_amount), 0) FROM oil_expense WHERE employee_id = :eid"),
        {"eid": employee_id},
    ).scalar()
    maintenance = sess.execute(
        text("SELECT COALESCE(SUM(total_bill_amount), 0) FROM maintenance_expense WHERE employee_id = :eid"),
        {"eid": employee_id},
    ).scalar()
    employee = sess.execute(
        text("SELECT COALESCE(SUM(amount), 0) FROM employee_expense WHERE employee_id = :eid"),
        {"eid": employee_id},
    ).scalar()
    opening = sess.execute(
        text("SELECT COALESCE(SUM(total_expense), 0) FROM workspace_opening_expense WHERE employee_id = :eid"),
        {"eid": employee_id},
    ).scalar()
    fuel_oil_opening = sess.execute(
        text("SELECT COALESCE(SUM(total_amount), 0) FROM workspace_fuel_oil_opening_expense WHERE employee_id = :eid"),
        {"eid": employee_id},
    ).scalar()
    transfers = sess.execute(
        text("SELECT COALESCE(SUM(amount), 0) FROM workspace_fund_transfer WHERE employee_id = :eid"),
        {"eid": employee_id},
    ).scalar()
    month_close = sess.execute(
        text("SELECT COUNT(*) FROM workspace_month_close WHERE employee_id = :eid"),
        {"eid": employee_id},
    ).scalar()
    return {
        "fuel": Decimal(str(fuel)),
        "oil": Decimal(str(oil)),
        "maintenance": Decimal(str(maintenance)),
        "employee": Decimal(str(employee)),
        "opening": Decimal(str(opening)),
        "fuel_oil_opening": Decimal(str(fuel_oil_opening)),
        "transfers": Decimal(str(transfers)),
        "month_close": month_close,
    }


def find_divergent_drivers(local_sess, online_sess):
    """Find drivers whose status differs between local and online."""
    local = {
        r[0]: r[1]
        for r in local_sess.execute(text("SELECT id, status FROM driver")).all()
    }
    online = {
        r[0]: r[1]
        for r in online_sess.execute(text("SELECT id, status FROM driver")).all()
    }
    divergent = []
    for did in set(local.keys()) | set(online.keys()):
        local_status = local.get(did, "MISSING")
        online_status = online.get(did, "MISSING")
        if local_status != online_status:
            divergent.append((did, local_status, online_status))
    return divergent


def find_missing_drivers(local_sess, online_sess):
    """Find drivers present in one DB but not the other."""
    local_ids = {r[0] for r in local_sess.execute(text("SELECT id FROM driver")).all()}
    online_ids = {r[0] for r in online_sess.execute(text("SELECT id FROM driver")).all()}
    only_local = sorted(local_ids - online_ids)
    only_online = sorted(online_ids - local_ids)
    return only_local, only_online


def main():
    local_url = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LOCAL_DATABASE_URL", "sqlite:///db/local.db")).strip()
    if local_url.startswith("sqlite:///") and not os.path.isabs(local_url[10:]):
        local_url = "sqlite:///" + os.path.join(ROOT, local_url[10:]).replace("\\", "/")
    online_url = (sys.argv[2] if len(sys.argv) > 2 else os.environ.get("ONLINE_DATABASE_URL", os.environ.get("RENDER_DB_URL", ""))).strip()

    if not online_url:
        print("ERROR: ONLINE_DATABASE_URL env var or second CLI arg required (Render PostgreSQL URL).")
        sys.exit(1)

    local_engine = get_engine(local_url)
    online_engine = get_engine(online_url)
    LocalSess = sessionmaker(bind=local_engine)
    OnlineSess = sessionmaker(bind=online_engine)
    local_sess = LocalSess()
    online_sess = OnlineSess()

    print("=" * 70)
    print("DATABASE COMPARISON REPORT")
    print("=" * 70)
    print(f"Local:  {local_url}")
    print(f"Online: {online_url}")
    print(f"Generated: {datetime.now().isoformat()}")
    print()

    # 1. Driver status summary
    print("--- DRIVER STATUS SUMMARY ---")
    local_status = driver_status_summary(local_sess)
    online_status = driver_status_summary(online_sess)
    print(f"Local:  {local_status}")
    print(f"Online: {online_status}")
    print()

    # 2. Divergent driver statuses
    print("--- DIVERGENT DRIVER STATUSES ---")
    divergent = find_divergent_drivers(local_sess, online_sess)
    if divergent:
        for did, ls, online_status in divergent:
            print(f"  driver_id={did}: local={ls} online={online_status}")
    else:
        print("  None")
    print()

    # 3. Missing drivers
    print("--- DRIVERS PRESENT IN ONLY ONE DATABASE ---")
    only_local, only_online = find_missing_drivers(local_sess, online_sess)
    if only_local:
        print(f"  Only in local ({len(only_local)}): {only_local}")
    if only_online:
        print(f"  Only in online ({len(only_online)}): {only_online}")
    if not only_local and not only_online:
        print("  None")
    print()

    # 4. Workspace summary for the logged-in employee (Muhammad Saifur Rehman Sajid)
    print("--- WORKSPACE EXPENSE/TRANSFER TOTALS ---")
    # Find employee by name from both databases
    for label, sess in [("Local", local_sess), ("Online", online_sess)]:
        rows = sess.execute(
            text("SELECT id, name FROM employee WHERE name LIKE '%Saifur%' OR name LIKE '%Sajid%' ORDER BY id LIMIT 5")
        ).all()
        print(f"{label} employees matching Saifur/Sajid: {rows}")
    print()

    # Let user pick employee_id via env or use first match
    employee_id = os.environ.get("EMPLOYEE_ID")
    if not employee_id:
        # Try to auto-detect the employee from the workspace session on local
        rows = local_sess.execute(
            text("SELECT id, name FROM employee WHERE name LIKE '%Saifur%' OR name LIKE '%Sajid%' ORDER BY id LIMIT 1")
        ).all()
        if rows:
            employee_id = rows[0][0]
            print(f"Auto-detected employee_id={employee_id} ({rows[0][1]})")
        else:
            print("WARNING: Could not auto-detect employee_id. Set EMPLOYEE_ID env var.")
            employee_id = None

    if employee_id:
        local_ws = workspace_summary(local_sess, employee_id)
        online_ws = workspace_summary(online_sess, employee_id)
        print(f"Employee ID: {employee_id}")
        print(f"{'Source':<25} {'Local':>20} {'Online':>20} {'Diff':>20}")
        print("-" * 90)
        tracked_local = Decimal("0")
        tracked_online = Decimal("0")
        for key in ["fuel", "oil", "maintenance", "employee", "opening", "fuel_oil_opening"]:
            diff = local_ws[key] - online_ws[key]
            tracked_local += local_ws[key]
            tracked_online += online_ws[key]
            print(f"{key:<25} {local_ws[key]:>20.2f} {online_ws[key]:>20.2f} {diff:>20.2f}")
        print("-" * 90)
        print(f"{'Tracked Total':<25} {tracked_local:>20.2f} {tracked_online:>20.2f} {tracked_local - tracked_online:>20.2f}")
        print(f"{'Transfers':<25} {local_ws['transfers']:>20.2f} {online_ws['transfers']:>20.2f} {local_ws['transfers'] - online_ws['transfers']:>20.2f}")
        print(f"{'Month Close Records':<25} {local_ws['month_close']:>20} {online_ws['month_close']:>20}")
        print()

    # 5. Table counts
    print("--- TABLE RECORD COUNTS ---")
    tables = [
        "driver", "employee", "vehicle", "project", "district", "company",
        "fuel_expense", "oil_expense", "maintenance_expense", "employee_expense",
        "workspace_opening_expense", "workspace_fuel_oil_opening_expense",
        "workspace_fund_transfer", "workspace_month_close",
        "journal_entry", "journal_entry_line", "payment_voucher", "receipt_voucher", "bank_entry",
    ]
    local_counts = table_counts(local_sess, tables)
    online_counts = table_counts(online_sess, tables)
    print(f"{'Table':<35} {'Local':>10} {'Online':>10} {'Diff':>10}")
    print("-" * 70)
    for t in tables:
        lc = local_counts[t]
        oc = online_counts[t]
        if isinstance(lc, int) and isinstance(oc, int):
            diff = lc - oc
            marker = " <<<" if diff != 0 else ""
            print(f"{t:<35} {lc:>10} {oc:>10} {diff:>10}{marker}")
        else:
            print(f"{t:<35} {str(lc):>10} {str(oc):>10}")
    print()

    print("=" * 70)
    print("TIP: If the local DB is correct, take a backup and restore it to Render.")
    print("If the online DB is correct, update your local DATABASE_URL to match.")
    print("=" * 70)


if __name__ == "__main__":
    main()
