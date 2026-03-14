# Permission Fix Guide - Assign Driver to Vehicle Access

## Problem
User with Employee record (1 district, 1 project assigned) getting "Internal Server Error" when accessing `/assign_driver_to_vehicle` page.

## Root Cause
**Permission Issue** - User does not have the required `assign_driver_to_vehicle` permission to access the route.

The error occurs at the `@app.before_request` middleware (routes.py line 85-178) which checks permissions BEFORE the route handler executes. This is why:
- `get_user_context()` function never gets called
- Debug logs don't appear
- Internal Server Error is shown instead of "Access Denied"

## Solution Steps

### Option 1: Grant Specific Permission (Recommended)
1. Login as **Admin** or **Master** user
2. Go to **User Management** → **Roles**
3. Find the role assigned to this user (e.g., "Employee" or "Incharge")
4. Click **Edit Role**
5. Under **Assignment** section, enable:
   - ✅ **Driver to Vehicle – List / View** (`assign_driver_to_vehicle`)
   
6. Click **Save**
7. User needs to **logout and login again** for permissions to refresh

### Option 2: Grant Full Assignment Section Access
If user needs access to ALL assignment features:
1. Login as **Admin** or **Master** user
2. Go to **User Management** → **Roles**
3. Find the role assigned to this user
4. Click **Edit Role**
5. Under **Assignment** section, enable:
   - ✅ **Assignment (full)** - This grants access to all assignment sub-pages
6. Click **Save**
7. User needs to **logout and login again**

## Permission Hierarchy

```
assignment (full)
├── assign_project_to_company
│   ├── assign_project_to_company (List/View)
│   ├── assign_project_to_company_add
│   ├── assign_project_to_company_edit
│   └── assign_project_to_company_desassign
├── assign_project_to_district
│   ├── assign_project_to_district (List/View)
│   ├── assign_project_to_district_add
│   ├── assign_project_to_district_edit
│   └── assign_project_to_district_desassign
├── assign_vehicle_to_district
│   ├── assign_vehicle_to_district (List/View)
│   ├── assign_vehicle_to_district_add
│   ├── assign_vehicle_to_district_edit
│   └── assign_vehicle_to_district_desassign
├── assign_vehicle_to_parking
│   ├── assign_vehicle_to_parking (List/View)
│   ├── assign_vehicle_to_parking_add
│   ├── assign_vehicle_to_parking_edit
│   └── assign_vehicle_to_parking_desassign
└── assign_driver_to_vehicle ← **USER NEEDS THIS**
    ├── assign_driver_to_vehicle (List/View) ← **MINIMUM REQUIRED**
    ├── assign_driver_to_vehicle_add
    ├── assign_driver_to_vehicle_edit
    └── assign_driver_to_vehicle_desassign
```

## Verification Steps

After granting permission:
1. User should **logout completely**
2. **Login again** (this refreshes session permissions)
3. Try accessing `/assign_driver_to_vehicle` page
4. Should now see the page with data filtered by their assigned district/project

## Technical Details

### Permission Check Flow
```
Request → @app.before_request → require_login()
  ↓
Check if logged in
  ↓
Get required permission for endpoint
  ↓
Check user_can_access(user_permissions, required_permission)
  ↓
If NO permission → Redirect to login (shows as Internal Server Error)
If HAS permission → Continue to route handler → get_user_context() → Filter data
```

### Why Debug Logs Didn't Show
The debug logs in `get_user_context()` only execute if the request reaches the route handler. Since permission check failed at middleware level, the route handler (`assign_driver_to_vehicle_list()`) never executed.

## Related Files
- `routes.py` line 85-178: Permission middleware
- `routes.py` line 5326-5374: assign_driver_to_vehicle_list route
- `auth_utils.py` line 343-365: user_can_access() function
- `permissions_config.py` line 108-111: assign_driver_to_vehicle permissions

## Notes
- Master and Admin users have full access by default
- Employee/Driver users need explicit permissions
- Data scoping (filtering by assigned district/project) only works AFTER permission check passes
- Session must be refreshed (logout/login) for permission changes to take effect
