"""
One-time script: Add geofence columns to driver_attendance table (SQLite).
Run from project root: python add_attendance_geofence_columns.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from app import app
from sqlalchemy import text

def column_exists(engine, table, col):
    with engine.connect() as c:
        r = c.execute(text("PRAGMA table_info(" + table + ")"))
        return any(row[1] == col for row in r)

with app.app_context():
    from models import db
    engine = db.engine
    if engine.dialect.name != 'sqlite':
        print("Not SQLite. Run: flask db upgrade")
        sys.exit(0)
    cols = [
        ('parking_station_id', 'INTEGER'),
        ('check_in_latitude', 'REAL'),
        ('check_in_longitude', 'REAL'),
        ('check_in_photo_path', 'VARCHAR(500)'),
    ]
    with engine.connect() as conn:
        for col_name, col_type in cols:
            if not column_exists(engine, 'driver_attendance', col_name):
                conn.execute(text(
                    "ALTER TABLE driver_attendance ADD COLUMN " + col_name + " " + col_type
                ))
                conn.commit()
                print("Added column driver_attendance." + col_name)
            else:
                print("Column driver_attendance." + col_name + " already exists.")
    print("Done.")
