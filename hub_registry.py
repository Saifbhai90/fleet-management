"""
Module Hub registry — sidebar hubs with Report Centre–aligned icons.
Icons/tiles match reports_index.html where the same feature exists.
"""
from __future__ import annotations

from flask import url_for


def _item(route, label, icon, tile, perm=None, master_only=False, **kwargs):
    d = {'route': route, 'label': label, 'icon': icon, 'tile': tile, 'kwargs': kwargs}
    if perm is not None:
        d['perm'] = perm
    if master_only:
        d['master_only'] = True
    return d


HUBS = {
    'master-data': {
        'title': 'Master Data',
        'header_icon': 'bi-folder2-open',
        'section_perm': 'master',
        'extra_endpoints': (
            'companies', 'company_form', 'projects_list', 'project_detail', 'project_form',
            'districts_list', 'district_form', 'vehicles_list', 'vehicle_form', 'parking_list',
            'parking_form', 'drivers_list', 'driver_form', 'employees_list', 'employee_form',
            'driver_post_list', 'driver_post_form', 'report_vehicle_profile', 'report_driver_profile',
            'employee_profile_print', 'driver_doc_updates_list', 'driver_update_portal',
            'driver_update_portal_info', 'driver_update_portal_save',
        ),
        'sections': [
            {
                'title': 'Organization',
                'items': [
                    _item('companies', 'Companies', 'fa-solid fa-city', 'rc-tile--company', 'companies'),
                    _item('projects_list', 'Projects', 'fa-solid fa-diagram-project', 'rc-tile--project', 'projects'),
                    _item('districts_list', 'Districts', 'fa-solid fa-location-dot', 'rc-tile--district', 'districts'),
                ],
            },
            {
                'title': 'Fleet',
                'items': [
                    _item('vehicles_list', 'Vehicles', 'fa-solid fa-bus', 'rc-tile--vehicle-summary', 'vehicles'),
                    _item('parking_list', 'Parking Stations', 'fa-solid fa-square-parking', 'rc-tile--parking', 'parking'),
                ],
            },
            {
                'title': 'People',
                'items': [
                    _item('employees_list', 'Employees', 'fa-solid fa-users', 'rc-tile--active-drivers', 'employees'),
                    _item('drivers_list', 'Drivers', 'fa-solid fa-id-card', 'rc-tile--driver-profile', 'drivers'),
                    _item('driver_doc_updates_list', 'Driver Update Portal', 'fa-solid fa-pen-to-square', 'rc-tile--driver-profile', master_only=True),
                    _item('driver_post_list', 'Designations', 'fa-solid fa-id-badge', 'rc-tile--seat', 'driver_post'),
                ],
            },
        ],
    },
    'assignments': {
        'title': 'Assignments',
        'header_icon': 'bi-link-45deg',
        'section_perm': 'assignment',
        'extra_endpoints': (
            'assign_project_to_company', 'assign_project_to_district', 'assign_vehicle_to_district',
            'assign_vehicle_to_parking_list', 'assign_vehicle_to_parking_new', 'assign_vehicle_to_parking_edit',
            'assign_driver_to_vehicle_list', 'assign_driver_to_vehicle_new', 'assign_driver_to_vehicle_edit',
        ),
        'sections': [
            {
                'title': 'Fleet & Organisation',
                'items': [
                    _item('assign_project_to_company', 'Project to Company', 'fa-solid fa-city', 'rc-tile--company', 'assign_project_to_company'),
                    _item('assign_project_to_district', 'District to Project', 'fa-solid fa-location-dot', 'rc-tile--district', 'assign_project_to_district'),
                    _item('assign_vehicle_to_district', 'Vehicle to District', 'fa-solid fa-bus', 'rc-tile--vehicle-summary', 'assign_vehicle_to_district'),
                    _item('assign_vehicle_to_parking_list', 'Vehicle to Parking', 'fa-solid fa-square-parking', 'rc-tile--parking', 'assign_vehicle_to_parking'),
                    _item('assign_driver_to_vehicle_list', 'Driver to Vehicle', 'fa-solid fa-id-card', 'rc-tile--driver-profile', 'assign_driver_to_vehicle'),
                ],
            },
        ],
    },
    'transfers': {
        'title': 'Transfers',
        'header_icon': 'bi-arrow-left-right',
        'section_perm': 'transfer',
        'extra_endpoints': (
            'project_transfers', 'project_transfer_new', 'project_transfer_edit',
            'vehicle_transfers', 'vehicle_transfer_new', 'vehicle_transfer_edit',
            'driver_transfers', 'driver_transfer_new', 'driver_transfer_edit',
        ),
        'sections': [
            {
                'title': 'Transfers',
                'items': [
                    _item('project_transfers', 'Project Transfer', 'fa-solid fa-right-left', 'rc-tile--transfer', 'project_transfers'),
                    _item('vehicle_transfers', 'Vehicle Transfer', 'fa-solid fa-bus', 'rc-tile--vehicle-summary', 'vehicle_transfers'),
                    _item('driver_transfers', 'Driver Transfer', 'fa-solid fa-id-card', 'rc-tile--driver-profile', 'driver_transfers'),
                ],
            },
        ],
    },
    'workforce': {
        'title': 'Workforce',
        'header_icon': 'bi-person-gear',
        'section_perm': 'driver_status',
        'extra_endpoints': (
            'driver_job_left_new', 'driver_job_left_list', 'driver_rejoin_new', 'driver_rejoin_list',
            'penalty_record_list', 'penalty_record_new', 'penalty_record_edit',
            'employee_lifecycle_assign', 'employee_lifecycle_deassign', 'employee_lifecycle_left',
            'employee_lifecycle_rejoin', 'employee_lifecycle_history', 'employee_profile_report',
            'employee_lifecycle_assign_list', 'employee_lifecycle_deassign_list',
            'employee_lifecycle_left_list', 'employee_lifecycle_rejoin_list',
        ),
        'sections': [
            {
                'title': 'Drivers',
                'items': [
                    _item('driver_job_left_list', 'Resignation / Exit', 'fa-solid fa-user-minus', 'rc-tile--resignation', 'driver_job_left'),
                    _item('driver_rejoin_list', 'Re-employment', 'fa-solid fa-user-plus', 'rc-tile--rejoin', 'driver_rejoin'),
                    _item('penalty_record_list', 'Penalties', 'fa-solid fa-circle-exclamation', 'rc-tile--penalty', 'penalty_record'),
                ],
            },
            {
                'title': 'Employees',
                'items': [
                    _item('employee_lifecycle_history', 'Assignment History', 'fa-solid fa-clock-rotate-left', 'rc-tile--activity', 'employees'),
                    _item('employee_lifecycle_assign_list', 'Assign', 'fa-solid fa-user-plus', 'rc-tile--rejoin', 'employees'),
                    _item('employee_lifecycle_deassign_list', 'Deassign', 'fa-solid fa-user-minus', 'rc-tile--resignation', 'employees'),
                    _item('employee_lifecycle_left_list', 'Employee Left', 'fa-solid fa-user-xmark', 'rc-tile--resignation', 'employees'),
                    _item('employee_lifecycle_rejoin_list', 'Employee Rejoin', 'fa-solid fa-user-check', 'rc-tile--rejoin', 'employees'),
                ],
            },
        ],
    },
    'attendance': {
        'title': 'Attendance',
        'header_icon': 'bi-calendar-check',
        'section_perm': 'attendance',
        'extra_endpoints': (
            'driver_attendance_list', 'driver_attendance_mark', 'driver_attendance_bulk_off',
            'driver_attendance_pending', 'driver_attendance_missing_checkout',
            'driver_attendance_checkin', 'driver_attendance_checkout', 'driver_attendance_tra_report',
            'driver_attendance_report', 'driver_attendance_daily_report',
            'leave_request_list', 'leave_request_new', 'leave_request_review',
        ),
        'sections': [
            {
                'title': 'Check In / Out',
                'items': [
                    _item('driver_attendance_checkin', 'Check In (GPS & Camera)', 'fa-solid fa-location-dot', 'rc-tile--hub-att-check', 'driver_attendance_checkin'),
                    _item('driver_attendance_checkout', 'Check Out (GPS & Camera)', 'fa-solid fa-right-from-bracket', 'rc-tile--hub-att-check', 'driver_attendance_checkout'),
                    _item('driver_attendance_pending', 'Missing Check IN', 'fa-solid fa-circle-exclamation', 'rc-tile--red-task', 'driver_attendance_pending'),
                    _item('driver_attendance_missing_checkout', 'Missing Check OUT', 'fa-solid fa-circle-exclamation', 'rc-tile--red-task', 'driver_attendance_missing_checkout'),
                ],
            },
            {
                'title': 'Management',
                'items': [
                    _item('driver_attendance_mark', 'Leave / Late / Half Day / Off', 'fa-solid fa-pen-to-square', 'rc-tile--hub-att-mgmt', 'driver_attendance_mark'),
                    _item('driver_attendance_bulk_off', 'Bulk Status', 'fa-solid fa-calendar-xmark', 'rc-tile--hub-att-mgmt', 'driver_attendance_bulk_off'),
                    _item('leave_request_list', 'Leave Requests', 'fa-solid fa-calendar-check', 'rc-tile--monthly-att', 'leave_request_list'),
                ],
            },
            {
                'title': 'Reports',
                'items': [
                    _item('driver_attendance_tra_report', 'TRA Attendance Sheet', 'fa-solid fa-table-list', 'rc-tile--tra-att', 'driver_attendance_tra_report'),
                    _item('driver_attendance_list', 'Attendance List', 'fa-solid fa-list', 'rc-tile--tra-att', 'driver_attendance_list'),
                    _item('driver_attendance_report', 'Monthly Attendance Report', 'fa-solid fa-calendar-check', 'rc-tile--monthly-att', 'driver_attendance_report'),
                    _item('driver_attendance_daily_report', 'Day Wise Attendance Report', 'fa-solid fa-calendar-days', 'rc-tile--daily-att', 'driver_attendance_report'),
                ],
            },
        ],
    },
    'task-logbook': {
        'title': 'Task & Logbook',
        'header_icon': 'bi-clipboard2-data',
        'section_perm': 'task_report',
        'extra_endpoints': (
            'task_report_upload', 'task_report_upload_list', 'task_report_new', 'task_report_pending',
            'task_report_list', 'red_task_list', 'without_task_list', 'task_report_logbook_cover',
            'speed_monitoring_report', 'mileage_report', 'tracker_difference_report',
            'unauthorized_movement_report', 'task_start_delay_report', 'task_turnaround_report',
            'unexecuted_task_report',
        ),
        'sections': [
            {
                'title': 'Data Entry',
                'items': [
                    _item('task_report_upload', 'Workbook Upload', 'fa-solid fa-cloud-arrow-up', 'rc-tile--upload', 'task_report_upload'),
                    _item('task_report_upload_list', 'Workbook Upload Log', 'fa-solid fa-file-shield', 'rc-tile--upload-log', 'task_report_upload_list'),
                    _item('task_report_new', 'New Task Entry', 'fa-solid fa-plus-circle', 'rc-tile--new-task', 'task_report_entry'),
                ],
            },
            {
                'title': 'Reports',
                'items': [
                    _item('task_report_list', 'Daily Task Report', 'fa-solid fa-calendar-day', 'rc-tile--daily-task', 'task_report_list'),
                    _item('task_report_pending', 'Pending Task Report', 'fa-solid fa-hourglass-half', 'rc-tile--pending-task', 'task_report_pending'),
                    _item('red_task_list', 'Red Task Justification', 'fa-solid fa-flag', 'rc-tile--red-task', 'red_task'),
                    _item('without_task_list', 'Movement without Task', 'fa-solid fa-circle-stop', 'rc-tile--no-task', 'without_task'),
                    _item('task_report_logbook_cover', 'Logbook Covers', 'fa-solid fa-book-open', 'rc-tile--logbook', 'task_report_logbook'),
                    _item('speed_monitoring_report', 'Speed Monitoring Report', 'fa-solid fa-gauge-high', 'rc-tile--speed', 'speed_monitoring_report'),
                    _item('mileage_report', 'Mileage Report', 'fa-solid fa-route', 'rc-tile--mileage', 'mileage_report'),
                    _item('tracker_difference_report', 'Tracker Difference Report', 'fa-solid fa-tower-broadcast', 'rc-tile--tracker', 'tracker_difference_report'),
                    _item('unauthorized_movement_report', 'Unauthorized Movement Report', 'fa-solid fa-triangle-exclamation', 'rc-tile--unauthorized', 'unauthorized_movement_report'),
                    _item('task_start_delay_report', 'Driver Response Time Report', 'fa-solid fa-hourglass-half', 'rc-tile--response', 'task_start_delay_report'),
                    _item('task_turnaround_report', 'Task Turnaround Report', 'fa-solid fa-arrows-rotate', 'rc-tile--turnaround', 'task_turnaround_report'),
                    _item('unexecuted_task_report', 'Unexecuted Task Report', 'fa-solid fa-circle-xmark', 'rc-tile--unexecuted', 'unexecuted_task_report'),
                ],
            },
        ],
    },
    'finance': {
        'title': 'Finance',
        'header_icon': 'bi-bank',
        'section_perm': 'accounts',
        'extra_endpoints': (
            'wallet_dashboard', 'chart_of_accounts_list', 'chart_of_accounts_add', 'chart_of_accounts_edit',
            'fund_transfers_list', 'fund_transfer_add', 'fund_transfer_edit',
            'payment_vouchers_list', 'receipt_vouchers_list', 'bank_entries_list',
            'journal_vouchers_list', 'accounts_balance_sheet', 'accounts_account_ledger',
        ),
        'sections': [
            {
                'title': 'Dashboard',
                'items': [
                    _item('wallet_dashboard', 'Wallet Dashboard', 'fa-solid fa-wallet', 'rc-tile--wallet'),
                    _item('chart_of_accounts_list', 'Chart of Accounts', 'fa-solid fa-sitemap', 'rc-tile--chart-accounts'),
                ],
            },
            {
                'title': 'Transactions',
                'items': [
                    _item('fund_transfers_list', 'Fund Transfer', 'fa-solid fa-right-left', 'rc-tile--transfer'),
                    _item('payment_vouchers_list', 'Payment Vouchers', 'fa-solid fa-money-bill-wave', 'rc-tile--payment', 'accounts_quick_payment'),
                    _item('receipt_vouchers_list', 'Receipt Vouchers', 'fa-solid fa-file-invoice-dollar', 'rc-tile--receipt', 'accounts_quick_receipt'),
                    _item('bank_entries_list', 'Bank Entries', 'fa-solid fa-university', 'rc-tile--bank-entry', 'accounts_bank_entry'),
                    _item('journal_vouchers_list', 'Journal Voucher', 'fa-solid fa-book', 'rc-tile--journal-v'),
                ],
            },
            {
                'title': 'Reports',
                'items': [
                    _item('accounts_balance_sheet', 'Balance Sheet', 'fa-solid fa-chart-pie', 'rc-tile--balance', 'accounts_balance_sheet'),
                    _item('accounts_account_ledger', 'Account Ledger', 'fa-solid fa-list-check', 'rc-tile--ledger', 'accounts_account_ledger'),
                ],
            },
        ],
    },
    'payroll': {
        'title': 'Payroll',
        'header_icon': 'bi-cash-stack',
        'section_perm': 'payroll',
        'extra_endpoints': (
            'payroll_salary_config_list', 'payroll_salary_config_form', 'payroll_salary_config_edit',
            'payroll_driver_bulk_salary', 'payroll_list', 'payroll_generate', 'payroll_bulk_generate',
            'payroll_view', 'payroll_edit', 'payroll_pending', 'payroll_payslip',
        ),
        'sections': [
            {
                'title': 'Payroll',
                'items': [
                    _item('payroll_salary_config_list', 'Salary Config', 'fa-solid fa-sliders', 'rc-tile--chart-accounts', 'payroll_config_list'),
                    _item('payroll_list', 'Payroll Records', 'fa-solid fa-file-lines', 'rc-tile--ledger', 'payroll_list'),
                    _item('payroll_generate', 'Generate Payroll', 'fa-solid fa-calculator', 'rc-tile--hub-payroll', 'payroll_generate'),
                    _item('payroll_bulk_generate', 'Bulk Generate', 'fa-solid fa-bolt', 'rc-tile--hub-payroll', 'payroll_generate'),
                    _item('payroll_pending', 'Pending Salaries', 'fa-solid fa-hourglass-half', 'rc-tile--red-task', 'payroll_pending'),
                ],
            },
        ],
    },
    'books': {
        'title': 'Book Management',
        'header_icon': 'bi-book',
        'section_perm': 'books',
        'extra_endpoints': (
            'book_inventory_list', 'book_stock_entry', 'book_stock_edit', 'book_issue',
            'book_assignment_list', 'book_return', 'book_pending_returns',
        ),
        'sections': [
            {
                'title': 'Books',
                'items': [
                    _item('book_inventory_list', 'Book Inventory', 'fa-solid fa-stairs', 'rc-tile--book-inv', 'book_inventory_list'),
                    _item('book_issue', 'Issue Book', 'fa-solid fa-book', 'rc-tile--book-assign', 'book_issue'),
                    _item('book_assignment_list', 'Assignments', 'fa-solid fa-bookmark', 'rc-tile--book-assign', 'book_assignment_list'),
                    _item('book_pending_returns', 'Pending Returns', 'fa-solid fa-arrow-rotate-left', 'rc-tile--book-return', 'book_pending_returns'),
                ],
            },
        ],
    },
    'notifications': {
        'title': 'Notifications',
        'header_icon': 'bi-bell-fill',
        'section_perm': None,
        'access': 'notifications',
        'extra_endpoints': (
            'notification_list', 'notification_add', 'reminder_list', 'reminder_add', 'reminder_edit',
        ),
        'sections': [
            {
                'title': 'Notifications',
                'items': [
                    _item('notification_list', 'All Notifications', 'fa-solid fa-bell', 'rc-tile--hub-notify', 'notification_list'),
                    _item('notification_add', 'Create Notification', 'fa-solid fa-circle-plus', 'rc-tile--new-task', 'notification_add'),
                    _item('reminder_list', 'My Reminders', 'fa-solid fa-calendar-check', 'rc-tile--monthly-att'),
                ],
            },
        ],
    },
    'administration': {
        'title': 'Administration',
        'header_icon': 'bi-shield-lock',
        'section_perm': None,
        'access': 'administration',
        'extra_endpoints': (
            'user_list', 'user_form', 'user_edit', 'role_list', 'role_form', 'role_edit',
            'form_control', 'system_health', 'admin_app_releases', 'admin_personal_tools',
            'admin_personal_tools_quick_print', 'admin_personal_tools_library',
            'admin_personal_tools_library_detail',
            'tool_workstation_index', 'tool_workstation_tool', 'tool_workstation_api_tools',
            'tracker_automation', 'tracker_automation_save_settings',
            'tracker_automation_start', 'tracker_automation_job_status',
            'tracker_automation_download_zip',
        ),
        'sections': [
            {
                'title': 'Administration',
                'items': [
                    _item('user_list', 'User Management', 'fa-solid fa-users-gear', 'rc-tile--hub-admin', 'user_list'),
                    _item('role_list', 'Roles & Permissions', 'fa-solid fa-shield-halved', 'rc-tile--hub-admin', 'role_list'),
                    _item('form_control', 'Setting', 'fa-solid fa-sliders', 'rc-tile--chart-accounts', 'form_control'),
                    _item('system_health', 'System Health', 'fa-solid fa-heart-pulse', 'rc-tile--red-task', master_only=True),
                    _item('admin_app_releases', 'App Updates', 'fa-solid fa-mobile-screen', 'rc-tile--hub-admin', master_only=True),
                    _item('admin_personal_tools', 'Personal Tool', 'fa-solid fa-screwdriver-wrench', 'rc-tile--hub-admin', master_only=True),
                    _item('tool_workstation_index', 'Tool Workstation', 'fa-solid fa-toolbox', 'rc-tile--hub-admin', master_only=True),
                    _item('tracker_automation', 'Tracker Automation', 'fa-solid fa-robot', 'rc-tile--tracker', master_only=True),
                ],
            },
        ],
    },
}


def _hub_access(hub, can_see_section_fn, can_see_page_fn, can_see_admin_fn, is_master):
    access = hub.get('access')
    if access == 'notifications':
        return can_see_page_fn('notification_list')
    if access == 'administration':
        return can_see_admin_fn()
    perm = hub.get('section_perm')
    if perm:
        return can_see_section_fn(perm)
    return True


def build_hub_sections(slug, can_see_page_fn, is_master=False):
    hub = HUBS.get(slug)
    if not hub:
        return None, []
    out_sections = []
    for sec in hub.get('sections', []):
        items = []
        for it in sec.get('items', []):
            if it.get('master_only') and not is_master:
                continue
            perm = it.get('perm')
            if perm == 'task_report_entry':
                if not (can_see_page_fn('task_report_entry') or can_see_page_fn('task_report_add')):
                    continue
            elif perm and not can_see_page_fn(perm):
                continue
            try:
                kwargs = dict(it.get('kwargs', {}))
                kwargs['nav_from'] = f'hub:{slug}'
                href = url_for(it['route'], **kwargs)
            except Exception:
                from flask import current_app
                current_app.logger.warning(
                    'hub_registry: url_for failed for route=%s kwargs=%s',
                    it.get('route'),
                    it.get('kwargs'),
                )
                continue
            items.append({
                'href': href,
                'label': it['label'],
                'icon': it['icon'],
                'tile': it['tile'],
            })
        if items:
            out_sections.append({'title': sec['title'], 'links': items})
    return hub, out_sections


def hub_active_endpoints():
    out = {}
    for slug, hub in HUBS.items():
        eps = set(hub.get('extra_endpoints', ()))
        for sec in hub.get('sections', []):
            for it in sec.get('items', []):
                eps.add(it['route'])
        out[slug] = frozenset(eps)
    return out


HUB_ACTIVE_ENDPOINTS = hub_active_endpoints()


def _build_endpoint_to_hub_slug():
    """Map Flask endpoint name → hub slug (same registry sidebar highlight uses)."""
    mapping = {}
    for slug, eps in HUB_ACTIVE_ENDPOINTS.items():
        for ep in eps:
            mapping.setdefault(ep, slug)
    return mapping


ENDPOINT_TO_HUB_SLUG = _build_endpoint_to_hub_slug()


def hub_slug_for_endpoint(endpoint=None):
    """Which sidebar hub owns this route (e.g. driver_attendance_list → attendance)."""
    if not endpoint:
        return None
    return ENDPOINT_TO_HUB_SLUG.get(endpoint)


def hub_url_for_slug(slug):
    if not slug or slug not in HUBS:
        return None
    try:
        return url_for('module_hub', hub_slug=slug)
    except Exception:
        return None


def hub_url_for_endpoint(endpoint=None):
    """Module hub URL for the page's owning section (sidebar-equivalent home)."""
    slug = hub_slug_for_endpoint(endpoint)
    return hub_url_for_slug(slug) if slug else None
