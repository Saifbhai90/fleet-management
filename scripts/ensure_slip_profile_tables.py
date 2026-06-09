"""One-off / dev helper: ensure workspace_slip_profile tables exist in SQLite."""
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
    if c.fetchone():
        print("workspace_slip_profile tables already exist")
        conn.close()
        return 0
    c.executescript(
        """
CREATE TABLE workspace_slip_profile (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER,
    name VARCHAR(120) NOT NULL,
    fingerprint_keywords TEXT,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME,
    updated_at DATETIME,
    FOREIGN KEY(employee_id) REFERENCES employee (id) ON DELETE SET NULL
);
CREATE INDEX ix_workspace_slip_profile_employee_id ON workspace_slip_profile (employee_id);
CREATE TABLE workspace_slip_profile_field (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    field_key VARCHAR(30) NOT NULL,
    region_x NUMERIC(6, 2) NOT NULL DEFAULT 0,
    region_y NUMERIC(6, 2) NOT NULL DEFAULT 0,
    region_w NUMERIC(6, 2) NOT NULL DEFAULT 100,
    region_h NUMERIC(6, 2) NOT NULL DEFAULT 100,
    FOREIGN KEY(profile_id) REFERENCES workspace_slip_profile (id) ON DELETE CASCADE,
    CONSTRAINT uq_ws_slip_profile_field UNIQUE (profile_id, field_key)
);
CREATE INDEX ix_workspace_slip_profile_field_profile_id ON workspace_slip_profile_field (profile_id);
"""
    )
    conn.commit()
    conn.close()
    print("Created workspace_slip_profile + workspace_slip_profile_field")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
