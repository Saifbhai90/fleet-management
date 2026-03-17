#!/usr/bin/env python3
"""
STANDALONE DATABASE CLEANUP SCRIPT
==================================
This script wipes all dummy data from the Fleet Management database while preserving:
- Master user account and all roles/permissions
- System settings and configurations
- Login logs and activity logs

SAFETY: This script is OUTSIDE your main application logic.
It only runs when you manually execute it from terminal.

Author: Database Administrator
Date: 2026-03-17
"""

import os
import sys
from datetime import datetime

# Add the project directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from models import (
    # Association tables (cleared first)
    project_district, employee_project, employee_district, vehicle_district,
    
    # Expense data (cleared early due to foreign keys)
    FuelExpense, OilExpense, OilExpenseItem, OilExpenseAttachment,
    MaintenanceExpense, MaintenanceExpenseItem, MaintenanceExpenseAttachment,
    
    # Daily operations
    DriverAttendance, VehicleDailyTask, RedTask, EmergencyTaskRecord,
    VehicleMileageRecord, VehicleMoveWithoutTask, PenaltyRecord,
    
    # Transfers and assignments
    DriverTransfer, ProjectTransfer, VehicleTransfer, DriverStatusChange,
    
    # Finance/Accounting
    JournalEntry, JournalEntryLine, PaymentVoucher, ReceiptVoucher,
    BankEntry, EmployeeExpense, Account,
    
    # Master data (cleared last)
    Driver, Vehicle, Project, District, ParkingStation, Company, Party, Product,
    Employee, EmployeeDocument, EmployeePost,
    
    # Other cleanup
    ProductBalance, VoucherSequence,
)

# Tables to PRESERVE (never delete)
PRESERVED_TABLES = {
    'user', 'role', 'permission', 'role_permissions',  # Users & RBAC
    'login_log', 'activity_log', 'client_activity_log',  # Audit logs
    'notification', 'notification_read', 'reminder',  # Notifications
    'attendance_time_control',  # System settings
}

def reset_sequence(table_name):
    """Reset auto-increment sequence for a table (SQLite/PostgreSQL/MySQL compatible)"""
    try:
        # Get database dialect
        dialect = db.engine.dialect.name.lower()
        
        if dialect == 'sqlite':
            # SQLite: delete from sqlite_sequence
            db.session.execute(f"DELETE FROM sqlite_sequence WHERE name='{table_name}';")
        elif dialect == 'postgresql':
            # PostgreSQL: reset sequence
            db.session.execute(f"ALTER SEQUENCE {table_name}_id_seq RESTART WITH 1;")
        elif dialect == 'mysql':
            # MySQL: reset auto increment
            db.session.execute(f"ALTER TABLE {table_name} AUTO_INCREMENT = 1;")
        
        print(f"  ✓ Reset sequence for {table_name}")
    except Exception as e:
        print(f"  ⚠ Could not reset sequence for {table_name}: {e}")

def clear_table(model_class, table_name=None):
    """Clear all records from a table and reset sequence"""
    if table_name is None:
        table_name = model_class.__tablename__
    
    try:
        # Delete all records
        deleted = model_class.query.delete()
        db.session.commit()
        print(f"  ✓ Cleared {table_name}: {deleted} records")
        
        # Reset auto-increment sequence
        reset_sequence(table_name)
        
    except Exception as e:
        print(f"  ✗ Error clearing {table_name}: {e}")
        db.session.rollback()
        raise

def clear_association_table(table_obj, table_name):
    """Clear association table (many-to-many)"""
    try:
        deleted = db.session.execute(table_obj.delete()).rowcount
        db.session.commit()
        print(f"  ✓ Cleared association {table_name}: {deleted} records")
        reset_sequence(table_name)
    except Exception as e:
        print(f"  ✗ Error clearing association {table_name}: {e}")
        db.session.rollback()
        raise

def confirm_master_user():
    """Verify Master user exists before proceeding"""
    from models import User, Role
    try:
        master_role = Role.query.filter_by(name='Master').first()
        if not master_role:
            print("❌ ERROR: 'Master' role not found!")
            return False
        
        master_users = User.query.filter_by(role_id=master_role.id, is_active=True).all()
        if not master_users:
            print("❌ ERROR: No active Master users found!")
            return False
        
        print(f"✅ Found {len(master_users)} Master user(s):")
        for user in master_users:
            print(f"   - {user.username} ({user.full_name or 'No name'})")
        return True
        
    except Exception as e:
        print(f"❌ Error checking Master user: {e}")
        return False

def list_tables_to_clear():
    """Display all tables that will be cleared"""
    print("\n" + "="*80)
    print("📋 TABLES THAT WILL BE CLEARED")
    print("="*80)
    
    tables = [
        # Association tables (cleared first)
        ("project_district", "Many-to-many: Projects ↔ Districts"),
        ("employee_project", "Many-to-many: Employees ↔ Projects"),
        ("employee_district", "Many-to-many: Employees ↔ Districts"),
        ("vehicle_district", "Many-to-many: Vehicles ↔ Districts"),
        
        # Expense data
        ("fuel_expense", "Fueling records"),
        ("oil_expense", "Oil changes and lubricants"),
        ("oil_expense_item", "Oil expense line items"),
        ("oil_expense_attachment", "Oil expense attachments"),
        ("maintenance_expense", "Vehicle maintenance"),
        ("maintenance_expense_item", "Maintenance line items"),
        ("maintenance_expense_attachment", "Maintenance attachments"),
        
        # Daily operations
        ("driver_attendance", "Daily attendance records"),
        ("vehicle_daily_task", "Daily vehicle task reports"),
        ("red_task", "Red task entries"),
        ("emergency_task_record", "Emergency task records"),
        ("vehicle_mileage_record", "Vehicle mileage records"),
        ("vehicle_move_without_task", "Vehicle movement without tasks"),
        ("penalty_record", "Driver penalty records"),
        
        # Transfers and assignments
        ("driver_transfer", "Driver transfer history"),
        ("project_transfer", "Project transfer history"),
        ("vehicle_transfer", "Vehicle transfer history"),
        ("driver_status_change", "Driver status changes (left/rejoin)"),
        
        # Finance/Accounting
        ("journal_entry", "Journal entries (transactions)"),
        ("journal_entry_line", "Journal entry lines"),
        ("payment_voucher", "Payment vouchers"),
        ("receipt_voucher", "Receipt vouchers"),
        ("bank_entry", "Bank entries"),
        ("employee_expense", "Employee expenses"),
        ("account", "Chart of Accounts"),
        
        # Master data
        ("driver", "Driver records"),
        ("vehicle", "Vehicle records"),
        ("project", "Project records"),
        ("district", "District records"),
        ("parking_station", "Parking stations"),
        ("company", "Company records"),
        ("party", "Parties (Pumps/Workshops)"),
        ("product", "Products (Fuel/Oil/Parts)"),
        ("employee", "Employee records"),
        ("employee_document", "Employee documents"),
        ("driver_post", "Employee posts/designations"),
        
        # System cleanup
        ("product_balance", "Product stock balances"),
        ("voucher_sequence", "Voucher sequence counters"),
    ]
    
    for table, description in tables:
        print(f"  🗑️  {table:<30} - {description}")
    
    print("\n" + "="*80)
    print("🔒 TABLES THAT WILL BE PRESERVED")
    print("="*80)
    preserved = [
        ("user", "User accounts (including Master)"),
        ("role", "User roles"),
        ("permission", "Permission codes"),
        ("role_permissions", "Role-permission assignments"),
        ("login_log", "User login history"),
        ("activity_log", "System activity logs"),
        ("client_activity_log", "Client-side activity logs"),
        ("notification", "System notifications"),
        ("notification_read", "Per-user notification read state"),
        ("reminder", "Personal reminders"),
        ("attendance_time_control", "Attendance time window settings"),
    ]
    
    for table, description in preserved:
        print(f"  🔒 {table:<30} - {description}")

def perform_cleanup():
    """Execute the actual database cleanup"""
    print("\n🚀 STARTING DATABASE CLEANUP...")
    print("="*50)
    
    # Clear in safe order (dependencies first)
    cleanup_steps = [
        # 1. Association tables (many-to-many)
        (project_district, "project_district"),
        (employee_project, "employee_project"),
        (employee_district, "employee_district"),
        (vehicle_district, "vehicle_district"),
        
        # 2. Expense data (with cascading items/attachments)
        (FuelExpense, "fuel_expense"),
        (OilExpense, "oil_expense"),
        (MaintenanceExpense, "maintenance_expense"),
        
        # 3. Daily operations
        (DriverAttendance, "driver_attendance"),
        (VehicleDailyTask, "vehicle_daily_task"),
        (RedTask, "red_task"),
        (EmergencyTaskRecord, "emergency_task_record"),
        (VehicleMileageRecord, "vehicle_mileage_record"),
        (VehicleMoveWithoutTask, "vehicle_move_without_task"),
        (PenaltyRecord, "penalty_record"),
        
        # 4. Transfers and assignments
        (DriverTransfer, "driver_transfer"),
        (ProjectTransfer, "project_transfer"),
        (VehicleTransfer, "vehicle_transfer"),
        (DriverStatusChange, "driver_status_change"),
        
        # 5. Finance/Accounting
        (JournalEntry, "journal_entry"),
        (PaymentVoucher, "payment_voucher"),
        (ReceiptVoucher, "receipt_voucher"),
        (BankEntry, "bank_entry"),
        (EmployeeExpense, "employee_expense"),
        (Account, "account"),
        
        # 6. Master data (cleared last)
        (Driver, "driver"),
        (Vehicle, "vehicle"),
        (Project, "project"),
        (District, "district"),
        (ParkingStation, "parking_station"),
        (Company, "company"),
        (Party, "party"),
        (Product, "product"),
        (Employee, "employee"),
        (EmployeeDocument, "employee_document"),
        (EmployeePost, "driver_post"),
        
        # 7. System cleanup
        (ProductBalance, "product_balance"),
        (VoucherSequence, "voucher_sequence"),
    ]
    
    total_cleared = 0
    for step in cleanup_steps:
        model_or_table, name = step
        if isinstance(model_or_table, db.Table):
            clear_association_table(model_or_table, name)
        else:
            clear_table(model_or_table, name)
        total_cleared += 1
    
    print(f"\n✅ CLEANUP COMPLETED! Cleared {total_cleared} table groups.")
    print("🔄 All ID sequences have been reset to start from 1.")

def main():
    """Main execution function"""
    print("🔧 FLEET MANAGEMENT DATABASE CLEANUP")
    print("="*50)
    print("⚠️  WARNING: This will permanently delete ALL dummy data!")
    print("📅 Date:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    
    # Create app context
    app = create_app()
    with app.app_context():
        # Step 1: Verify Master user exists
        if not confirm_master_user():
            print("\n❌ CANNOT PROCEED: Master user verification failed!")
            sys.exit(1)
        
        # Step 2: List tables to be cleared
        list_tables_to_clear()
        
        # Step 3: Final confirmation
        print("\n" + "!"*80)
        print("🚨 FINAL CONFIRMATION REQUIRED")
        print("!"*80)
        print("This action CANNOT be undone!")
        print("All business data will be permanently deleted.")
        print("Only system infrastructure will remain.")
        print("!"*80)
        
        confirm = input("\nType 'WIPE DATA' to proceed: ").strip()
        
        if confirm != "WIPE DATA":
            print("\n❌ CANCELLED: Cleanup aborted.")
            sys.exit(0)
        
        # Step 4: Perform cleanup
        try:
            perform_cleanup()
            print("\n🎉 SUCCESS: Database has been cleaned!")
            print("📝 You can now start entering fresh production data.")
            print("🗑️  Delete this script (manual_cleanup.py) after verification.")
        except Exception as e:
            print(f"\n💥 ERROR during cleanup: {e}")
            print("🔄 Database has been rolled back to previous state.")
            sys.exit(1)

if __name__ == "__main__":
    main()
