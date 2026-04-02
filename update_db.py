# update_db.py
from app import app, db
from sqlalchemy import text, inspect
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError
from datetime import datetime
from utils import pk_now


def column_exists(table_name, column_name):
    """Check if a column already exists in the table"""
    inspector = inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def table_exists(table_name):
    """Check if table exists"""
    inspector = inspect(db.engine)
    return table_name in inspector.get_table_names()


def update_database_schema():
    with app.app_context():
        print("=== Starting database schema update script ===\n")
        print("Current time:", pk_now().strftime("%Y-%m-%d %H:%M:%S PKT"))
        print("-" * 80)

        success = 0
        skipped = 0
        errors = 0

        # ────────────────────────────────────────────────
        # STEP 0: RECREATE TABLES WITH SCHEMA CHANGES
        # ────────────────────────────────────────────────
        print("[STEP 0] Checking tables that need full recreation...")
        tables_to_recreate = {
            'emergency_task_record': {'amb_reg_no', 'task_id_ext', 'request_from'},
            'vehicle_mileage_record': {'reg_no', 'mileage', 'ptop'},
        }
        for tname, required_cols in tables_to_recreate.items():
            if table_exists(tname):
                existing_cols = {c['name'] for c in inspect(db.engine).get_columns(tname)}
                if not required_cols.issubset(existing_cols):
                    try:
                        db.session.execute(text(f'DROP TABLE IF EXISTS {tname}'))
                        db.session.commit()
                        print(f" [DROPPED] Outdated table '{tname}' (will be recreated)")
                    except Exception as e:
                        print(f" [ERROR] Could not drop '{tname}': {e}")
                        db.session.rollback()
                        errors += 1
                else:
                    print(f" [OK] Table '{tname}' schema is current")
            else:
                print(f" [INFO] Table '{tname}' does not exist yet")

        # ────────────────────────────────────────────────
        # STEP 1: CREATE ALL MISSING TABLES
        # ────────────────────────────────────────────────
        print("\n[STEP 1] Creating missing tables...")
        try:
            db.create_all()
            print("[SUCCESS] All missing tables created (if any).\n")
        except Exception as e:
            print(f"[ERROR] Failed to create tables: {e}\n")
            errors += 1

        # ────────────────────────────────────────────────
        # STEP 2: ADD MISSING COLUMNS (with safe checks)
        # ────────────────────────────────────────────────
        print("[STEP 2] Adding missing columns...\n")

        # Format: (table_name, column_name, column_definition)
        column_additions = [
            # Vehicle table
            ('vehicle', 'project_id', 'INTEGER REFERENCES project(id)'),
            ('vehicle', 'district_id', 'INTEGER REFERENCES district(id)'),
            ('vehicle', 'parking_station_id', 'INTEGER REFERENCES parking_station(id)'),
            ('vehicle', 'assign_to_district_date', 'DATE'),
            ('vehicle', 'assignment_remarks', 'TEXT'),

            # Driver table
            ('driver', 'district_id', 'INTEGER REFERENCES district(id)'),
            ('driver', 'project_id', 'INTEGER REFERENCES project(id)'),  # agar zarurat ho

            # Driver Transfer table
            ('driver_transfer', 'old_district_id', 'INTEGER REFERENCES district(id)'),
            ('driver_transfer', 'new_district_id', 'INTEGER REFERENCES district(id)'),
            ('driver_transfer', 'is_shift_only', 'BOOLEAN DEFAULT 0 NOT NULL'),

            # NEW: Driver Status Change table columns (agar table bana to columns bhi check)
            ('driver_status_change', 'driver_id', 'INTEGER NOT NULL REFERENCES driver(id)'),
            ('driver_status_change', 'action_type', 'VARCHAR(20) NOT NULL'),
            ('driver_status_change', 'reason', 'VARCHAR(100)'),
            ('driver_status_change', 'change_date', 'DATE NOT NULL DEFAULT CURRENT_DATE'),
            ('driver_status_change', 'remarks', 'TEXT'),
            ('driver_status_change', 'created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
            ('driver_status_change', 'left_project_id', 'INTEGER REFERENCES project(id)'),
            ('driver_status_change', 'left_district_id', 'INTEGER REFERENCES district(id)'),
            ('driver_status_change', 'left_vehicle_id', 'INTEGER REFERENCES vehicle(id)'),
            ('driver_status_change', 'left_shift', 'VARCHAR(20)'),
            ('driver_status_change', 'new_project_id', 'INTEGER REFERENCES project(id)'),
            ('driver_status_change', 'new_district_id', 'INTEGER REFERENCES district(id)'),
            ('driver_status_change', 'new_vehicle_id', 'INTEGER REFERENCES vehicle(id)'),
            ('driver_status_change', 'new_shift', 'VARCHAR(20)'),
            ('driver', 'status', "VARCHAR(20) DEFAULT 'Active'"),
            ('driver', 'emergency_relation', 'VARCHAR(100)'),
        ]

        for table_name, column_name, col_def in column_additions:
            if not table_exists(table_name):
                print(f" [SKIPPED] Table '{table_name}' does not exist yet → {column_name}")
                skipped += 1
                continue

            if column_exists(table_name, column_name):
                print(f" [SKIPPED] Column already exists → {table_name}.{column_name}")
                skipped += 1
                continue

            cmd = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {col_def}"
            try:
                db.session.execute(text(cmd))
                db.session.commit()
                print(f" [ADDED] → {table_name}.{column_name}")
                success += 1
            except OperationalError as e:
                if "duplicate column name" in str(e).lower():
                    print(f" [SKIPPED] Column already exists → {table_name}.{column_name}")
                    skipped += 1
                else:
                    print(f" [OPERATIONAL ERROR] {cmd}\n    → {e}")
                    errors += 1
                db.session.rollback()
            except ProgrammingError as e:
                print(f" [SYNTAX/PROGRAMMING ERROR] {cmd}\n    → {e}")
                errors += 1
                db.session.rollback()
            except SQLAlchemyError as e:
                print(f" [SQLALCHEMY ERROR] {cmd}\n    → {type(e).__name__}: {e}")
                errors += 1
                db.session.rollback()
            except Exception as e:
                print(f" [GENERAL ERROR] {cmd}\n    → {type(e).__name__}: {e}")
                errors += 1
                db.session.rollback()

        # ────────────────────────────────────────────────
        # SUMMARY
        # ────────────────────────────────────────────────
        print("\n" + "=" * 80)
        print("DATABASE UPDATE SUMMARY:")
        print(f"  Successful column additions : {success}")
        print(f"  Skipped (already existed / table missing) : {skipped}")
        print(f"  Errors encountered              : {errors}")
        print("=" * 80)

        if errors == 0:
            print("Database schema is now fully up-to-date! 🎉\n")
        else:
            print("Some errors occurred – please check the logs above and fix manually if needed.\n")


if __name__ == "__main__":
    print("Running update_db.py ...\n")
    update_database_schema()