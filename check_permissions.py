"""
Quick script to check if user has assign_driver_to_vehicle permission in database.
Run this to verify permissions are properly saved.
"""
from app import app
from models import db, User, Role, Permission

with app.app_context():
    # Find the user (replace with actual username)
    username = input("Enter username to check: ").strip()
    user = User.query.filter_by(username=username).first()
    
    if not user:
        print(f"User '{username}' not found!")
        exit(1)
    
    print(f"\nUser: {user.username}")
    print(f"Full Name: {user.full_name}")
    print(f"Role: {user.role.name if user.role else 'No role'}")
    print(f"Active: {user.is_active}")
    
    if user.role:
        print(f"\nRole Permissions ({len(user.role.permissions)} total):")
        perms = sorted([p.code for p in user.role.permissions])
        
        # Check for assign_driver_to_vehicle permission
        has_assign_driver = 'assign_driver_to_vehicle' in perms
        has_assignment_full = 'assignment' in perms
        
        print(f"\n✓ Has 'assign_driver_to_vehicle': {has_assign_driver}")
        print(f"✓ Has 'assignment' (full): {has_assignment_full}")
        
        if has_assign_driver or has_assignment_full:
            print("\n✅ USER SHOULD HAVE ACCESS to /assign_driver_to_vehicle")
            print("\nIf still getting error:")
            print("1. User must LOGOUT completely")
            print("2. Clear browser cache/cookies")
            print("3. LOGIN again (this refreshes session permissions)")
        else:
            print("\n❌ USER DOES NOT HAVE REQUIRED PERMISSION")
            print("\nGrant one of these permissions:")
            print("  - assign_driver_to_vehicle (specific)")
            print("  - assignment (full section access)")
        
        print(f"\nAll permissions for this role:")
        for i, p in enumerate(perms, 1):
            marker = "  ← REQUIRED" if p == 'assign_driver_to_vehicle' else ""
            print(f"  {i}. {p}{marker}")
    else:
        print("\n❌ User has no role assigned!")
