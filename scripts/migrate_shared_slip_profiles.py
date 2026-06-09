"""Make workspace_slip_profile company-wide: nullable employee_id, clear existing links."""
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(ROOT, "db", "local.db")


def main():
    if not os.path.exists(DB_FILE):
        print(f"DB not found: {DB_FILE}")
        return 1
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='workspace_slip_profile'"
    )
    if not c.fetchone():
        print("workspace_slip_profile table not found — nothing to migrate")
        conn.close()
        return 0

    c.execute("SELECT sql FROM sqlite_master WHERE name='workspace_slip_profile'")
    ddl = (c.fetchone() or [""])[0] or ""
    if "employee_id INTEGER NOT NULL" not in ddl:
        c.execute("UPDATE workspace_slip_profile SET employee_id = NULL")
        conn.commit()
        print("employee_id already nullable — cleared links on existing profiles")
        conn.close()
        return 0

    c.executescript(
        """
PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE workspace_slip_profile_new (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER,
    name VARCHAR(120) NOT NULL,
    fingerprint_keywords TEXT,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME,
    updated_at DATETIME,
    FOREIGN KEY(employee_id) REFERENCES employee (id) ON DELETE SET NULL
);
INSERT INTO workspace_slip_profile_new
    (id, employee_id, name, fingerprint_keywords, is_active, created_at, updated_at)
SELECT id, NULL, name, fingerprint_keywords, is_active, created_at, updated_at
FROM workspace_slip_profile;
DROP TABLE workspace_slip_profile;
ALTER TABLE workspace_slip_profile_new RENAME TO workspace_slip_profile;
CREATE INDEX IF NOT EXISTS ix_workspace_slip_profile_employee_id ON workspace_slip_profile (employee_id);
COMMIT;
PRAGMA foreign_keys=ON;
"""
    )
    conn.commit()
    conn.close()
    print("Migrated workspace_slip_profile to company-wide (employee_id nullable, existing cleared)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
