"""Add missing OCR columns to local SQLite if needed."""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "db" / "local.db"


def table_exists(conn, name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def column_names(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def main():
    if not DB.exists():
        print(f"No database at {DB}")
        return

    conn = sqlite3.connect(DB)
    try:
        if table_exists(conn, "employee"):
            cols = column_names(conn, "employee")
            if "last_slip_profile_id" not in cols:
                conn.execute(
                    "ALTER TABLE employee ADD COLUMN last_slip_profile_id INTEGER "
                    "REFERENCES workspace_slip_profile(id)"
                )
                print("Added employee.last_slip_profile_id")
            else:
                print("employee.last_slip_profile_id already exists")

        if table_exists(conn, "workspace_slip_profile_field"):
            cols = column_names(conn, "workspace_slip_profile_field")
            if "ocr_recipe_json" not in cols:
                conn.execute(
                    "ALTER TABLE workspace_slip_profile_field ADD COLUMN ocr_recipe_json TEXT"
                )
                print("Added workspace_slip_profile_field.ocr_recipe_json")
            else:
                print("workspace_slip_profile_field.ocr_recipe_json already exists")

        conn.commit()
        print("Done.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
