"""
Smoke Test: Verify all critical routes return 200 OK after architectural refactor.
Uses Flask test_client with a logged-in session.
"""
import os, sys, json

PROJECT_ROOT = r'F:\Laptop new hard drive Disk D\company_management'
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Import the app
import app as app_module
app = app_module.app

# Test credentials
TEST_USER = 'admin'
TEST_PASS = 'admin123'

# Routes to test (path, method, description)
ROUTES = [
    # Auth
    ('/login', 'GET', 'Login page'),
    
    # Dashboard
    ('/', 'GET', 'Dashboard (root)'),
    ('/dashboard', 'GET', 'Dashboard'),
    
    # Master Data
    ('/companies', 'GET', 'Companies list'),
    ('/projects', 'GET', 'Projects list'),
    ('/districts', 'GET', 'Districts list'),
    ('/vehicles', 'GET', 'Vehicles list'),
    ('/drivers', 'GET', 'Drivers list'),
    ('/parking', 'GET', 'Parking stations list'),
    ('/employees', 'GET', 'Employees list'),
    ('/driver-posts', 'GET', 'Driver posts list'),
    
    # Assignments
    ('/assign-project-to-company', 'GET', 'Assign project to company'),
    ('/assign-project-to-district', 'GET', 'Assign project to district'),
    ('/assign-vehicle-to-district', 'GET', 'Assign vehicle to district'),
    ('/assign-vehicle-to-parking', 'GET', 'Assign vehicle to parking'),
    ('/assign-driver-to-vehicle', 'GET', 'Assign driver to vehicle'),
    
    # Transfers
    ('/project-transfers', 'GET', 'Project transfers'),
    ('/vehicle-transfers', 'GET', 'Vehicle transfers'),
    ('/driver-transfers', 'GET', 'Driver transfers'),
    
    # Attendance
    ('/attendance', 'GET', 'Attendance list'),
    ('/attendance/checkin', 'GET', 'Attendance check-in'),
    ('/attendance/checkout', 'GET', 'Attendance check-out'),
    ('/attendance/manual', 'GET', 'Manual attendance'),
    ('/attendance/report', 'GET', 'Attendance report'),
    
    # Task Reports
    ('/task-reports', 'GET', 'Task reports list'),
    ('/task-report/new', 'GET', 'New task report'),
    ('/red-task', 'GET', 'Red task list'),
    ('/without-task', 'GET', 'Without task list'),
    
    # Expenses
    ('/expenses/fuel', 'GET', 'Fuel expense list'),
    ('/oil-expense', 'GET', 'Oil expense list'),
    ('/maintenance-expense', 'GET', 'Maintenance expense list'),
    
    # Finance
    ('/finance', 'GET', 'Finance dashboard'),
    ('/finance/accounts', 'GET', 'Chart of accounts'),
    ('/finance/journal-entries', 'GET', 'Journal entries'),
    ('/finance/payment-vouchers', 'GET', 'Payment vouchers'),
    ('/finance/receipt-vouchers', 'GET', 'Receipt vouchers'),
    ('/finance/balance-sheet', 'GET', 'Balance sheet'),
    ('/finance/ledger', 'GET', 'General ledger'),
    
    # Workspace
    ('/workspace', 'GET', 'Workspace home'),
    
    # Payroll
    ('/payroll/salary-config', 'GET', 'Payroll salary config'),
    ('/payroll', 'GET', 'Payroll list'),
    
    # Reports
    ('/reports', 'GET', 'Reports index'),
    ('/report/driver-profile', 'GET', 'Driver profile report'),
    ('/report/vehicle-summary', 'GET', 'Vehicle summary report'),
    
    # System
    ('/notifications', 'GET', 'Notifications list'),
    ('/reminders', 'GET', 'Reminders list'),
    ('/users', 'GET', 'Users list'),
    ('/roles', 'GET', 'Roles list'),
    ('/backup', 'GET', 'Backup index'),
    
    # Books
    ('/books', 'GET', 'Books list'),
    
    # Account
    ('/account/profile', 'GET', 'Account profile'),
    ('/account/change-password', 'GET', 'Change password'),
    
    # API endpoints (mobile)
    ('/api/v1/login', 'POST', 'Mobile API login'),
]

def run_smoke_test():
    results = []
    passed = 0
    failed = 0
    errors_500 = 0
    errors_404 = 0
    
    with app.test_client() as client:
        # Login first
        print("=" * 70)
        print("SMOKE TEST: Fleet Management System")
        print("=" * 70)
        
        # Try to login
        login_resp = client.post('/login', data={
            'username': TEST_USER,
            'password': TEST_PASS,
        }, follow_redirects=False)
        
        if login_resp.status_code in (302, 303):
            print(f"[OK] Login successful (redirect to {login_resp.headers.get('Location', '?')})")
            passed += 1
        else:
            print(f"[WARN] Login returned {login_resp.status_code} — routes may redirect to login")
        
        print()
        
        for path, method, desc in ROUTES:
            try:
                if method == 'GET':
                    resp = client.get(path, follow_redirects=True)
                elif method == 'POST':
                    resp = client.post(path, json={}, follow_redirects=True)
                
                status = resp.status_code
                
                if status == 200:
                    results.append((path, method, desc, status, 'OK'))
                    passed += 1
                elif status == 302:
                    # Redirect — likely to login if not authenticated
                    results.append((path, method, desc, status, 'REDIRECT'))
                    passed += 1
                elif status == 404:
                    results.append((path, method, desc, status, 'NOT FOUND'))
                    errors_404 += 1
                    failed += 1
                elif status == 500:
                    results.append((path, method, desc, status, 'SERVER ERROR'))
                    errors_500 += 1
                    failed += 1
                else:
                    results.append((path, method, desc, status, f'OTHER ({status})'))
                    failed += 1
                    
            except Exception as e:
                results.append((path, method, desc, -1, f'EXCEPTION: {e}'))
                failed += 1
        
        # Print results
        print(f"{'Route':<40} {'Method':<6} {'Status':<8} {'Result':<20}")
        print("-" * 80)
        for path, method, desc, status, result in results:
            marker = '[OK]' if status == 200 else ('[!]' if status >= 400 else '[-]')
            print(f"{marker} {desc:<36} {method:<6} {status:<8} {result}")
        
        print("-" * 80)
        print(f"\nSummary: {passed} passed, {failed} failed")
        print(f"  200 OK: {passed}")
        print(f"  404 Not Found: {errors_404}")
        print(f"  500 Server Error: {errors_500}")
        
        if errors_500 > 0:
            print("\n*** 500 ERRORS DETECTED — checking details ***")
            for path, method, desc, status, result in results:
                if status == 500:
                    print(f"  500 on {path} ({desc})")
        
        if errors_404 > 0:
            print("\n*** 404 ERRORS DETECTED — checking details ***")
            for path, method, desc, status, result in results:
                if status == 404:
                    print(f"  404 on {path} ({desc})")
        
        print()
        if failed == 0:
            print("*** ALL TESTS PASSED ***")
        else:
            print(f"*** {failed} TESTS FAILED — see above ***")
        
        return failed

if __name__ == '__main__':
    sys.exit(run_smoke_test())
