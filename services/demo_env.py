"""Demo environment helpers — isolated Render service + DB.

Set DEMO_MODE=1 on the demo web service only. Production must leave this unset/0.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta

logger = logging.getLogger(__name__)

DEMO_COMPANY_NAME = 'Demo Fleet Co'
DEMO_PROJECT_NAME = 'Demo EMS Project'
DEMO_USERNAME = 'demo'
DEMO_PASSWORD = 'Demo@2026'


def is_demo_mode() -> bool:
    return (os.environ.get('DEMO_MODE') or '').strip().lower() in (
        '1', 'true', 'yes', 'on',
    )


def seed_demo_data(app=None) -> dict:
    """Idempotent sample data for demo environments.

    Safe to call on every boot when DEMO_MODE=1. Skips when demo company already exists.
    """
    if not is_demo_mode():
        return {'ok': False, 'skipped': True, 'reason': 'DEMO_MODE off'}

    from models import (
        db, Company, Project, District, ParkingStation, Vehicle, Driver, User, Role,
    )
    from werkzeug.security import generate_password_hash as _gph

    created = {
        'company': False,
        'project': False,
        'districts': 0,
        'parking': 0,
        'vehicles': 0,
        'drivers': 0,
        'user': False,
        'admin_full_access': False,
    }

    def _run():
        nonlocal created
        company = Company.query.filter_by(name=DEMO_COMPANY_NAME).first()
        if company:
            _ensure_demo_user(_gph, created)
            db.session.commit()
            return

        today = date.today()
        company = Company(
            name=DEMO_COMPANY_NAME,
            office_address='Demo Office, Sample Block',
            state='Punjab',
            district='Lahore',
            mobile='03001234567',
            email='demo@fleet-demo.local',
            remarks='SAMPLE DATA — demo environment only. Safe to edit/delete.',
        )
        db.session.add(company)
        db.session.flush()
        created['company'] = True

        project = Project(
            name=DEMO_PROJECT_NAME,
            start_date=today - timedelta(days=90),
            status='Active',
            assign_date=today - timedelta(days=90),
            company_id=company.id,
            remarks='Demo project for client walkthroughs.',
            ufone_close_reminder_minutes=90,
        )
        db.session.add(project)
        db.session.flush()
        created['project'] = True

        district_specs = [
            ('Lahore', 'Punjab'),
            ('Faisalabad', 'Punjab'),
            ('Multan', 'Punjab'),
        ]
        districts = []
        for name, province in district_specs:
            d = District.query.filter_by(name=name).first()
            if not d:
                d = District(name=name, province=province, remarks='Demo district')
                db.session.add(d)
                db.session.flush()
                created['districts'] += 1
            districts.append(d)
            if d not in list(project.districts):
                project.districts.append(d)

        parking_rows = []
        for d in districts:
            pname = f'{d.name} Demo Station'
            ps = ParkingStation.query.filter_by(name=pname, district=d.name).first()
            if not ps:
                ps = ParkingStation(
                    name=pname,
                    district=d.name,
                    tehsil=d.name,
                    address_location=f'Sample parking — {d.name}',
                    capacity=10,
                    project_id=project.id,
                    create_date=today,
                )
                db.session.add(ps)
                db.session.flush()
                created['parking'] += 1
            parking_rows.append(ps)

        vehicle_specs = [
            ('DEMO-25-001', 'Suzuki Bolan', 'Ambulance', districts[0], parking_rows[0]),
            ('DEMO-25-002', 'Toyota Hiace', 'Ambulance', districts[1], parking_rows[1]),
            ('DEMO-25-003', 'Suzuki Bolan', 'Ambulance', districts[2], parking_rows[2]),
        ]
        vehicles = []
        for i, (vno, model, vtype, dist, park) in enumerate(vehicle_specs, start=1):
            v = Vehicle.query.filter_by(vehicle_no=vno).first()
            if not v:
                v = Vehicle(
                    vehicle_no=vno,
                    model=model,
                    engine_no=f'DEMO-ENG-{i:03d}',
                    chassis_no=f'DEMO-CHS-{i:03d}',
                    vehicle_type=vtype,
                    vehicle_family='Ambulance',
                    fuel_type='Petrol',
                    phone_no=f'0300{1000000 + i}',
                    active_date=today - timedelta(days=60),
                    driver_capacity=2,
                    target_mpg=12,
                    fuel_tank_capacity=40,
                    project_id=project.id,
                    district_id=dist.id,
                    parking_station_id=park.id,
                    assign_to_district_date=today - timedelta(days=30),
                    parking_assign_date=today - timedelta(days=30),
                    remarks='Demo vehicle — sample only',
                    project_sort_order=i,
                )
                db.session.add(v)
                db.session.flush()
                created['vehicles'] += 1
            vehicles.append(v)

        driver_specs = [
            ('DEM-001', 'Ali Demo', '03001110001', '35202-1111111-1', 'LIC-DEMO-001', vehicles[0], districts[0]),
            ('DEM-002', 'Sara Demo', '03001110002', '35202-2222222-2', 'LIC-DEMO-002', vehicles[1], districts[1]),
            ('DEM-003', 'Hassan Demo', '03001110003', '35202-3333333-3', 'LIC-DEMO-003', vehicles[2], districts[2]),
        ]
        for did, name, phone, cnic, lic, veh, dist in driver_specs:
            drv = Driver.query.filter_by(driver_id=did).first()
            if drv:
                continue
            drv = Driver(
                driver_id=did,
                post='Driver',
                application_date=today - timedelta(days=120),
                name=name,
                father_name='Demo Father',
                phone1=phone,
                address=f'Sample address — {dist.name}',
                cnic_no=cnic,
                cnic_issue_date=today - timedelta(days=800),
                cnic_expiry_date=today + timedelta(days=400),
                cnic_status='Valid',
                license_no=lic,
                license_issue_date=today - timedelta(days=500),
                license_valid_from=today - timedelta(days=500),
                license_expiry_date=today + timedelta(days=300),
                license_status='Valid',
                issue_district=dist.name,
                license_type='LTV',
                shift='Morning',
                driver_district=dist.name,
                assign_date=today - timedelta(days=30),
                status='Active',
                project_id=project.id,
                vehicle_id=veh.id,
                district_id=dist.id,
                remarks='Demo driver — sample only',
            )
            db.session.add(drv)
            db.session.flush()
            veh.driver_id = drv.id
            created['drivers'] += 1

        _ensure_demo_user(_gph, created)
        db.session.commit()

    def _ensure_demo_user(gph, created_map):
        admin_role = Role.query.filter_by(name='Admin').first()
        master_role = Role.query.filter_by(name='Master').first()
        # Free-roam demo: Admin gets all permissions on demo env
        if admin_role and master_role:
            master_codes = {p.id for p in master_role.permissions}
            admin_codes = {p.id for p in admin_role.permissions}
            if master_codes and admin_codes != master_codes:
                admin_role.permissions = list(master_role.permissions)
                created_map['admin_full_access'] = True

        role = admin_role or master_role
        if not role:
            return

        user = User.query.filter_by(username=DEMO_USERNAME).first()
        if not user:
            user = User(
                username=DEMO_USERNAME,
                password_hash=gph(DEMO_PASSWORD),
                full_name='Demo Client',
                role_id=role.id,
                is_active=True,
                force_password_change=False,
            )
            db.session.add(user)
            created_map['user'] = True
        else:
            user.role_id = role.id
            user.is_active = True
            user.force_password_change = False

        # Soften first-login friction for seeded master/admin on demo only
        for uname in ('master', 'admin', DEMO_USERNAME):
            u = User.query.filter_by(username=uname).first()
            if u and u.force_password_change:
                u.force_password_change = False

    try:
        if app is not None:
            with app.app_context():
                _run()
        else:
            _run()
        logger.info('Demo seed complete: %s', created)
        return {'ok': True, 'created': created, 'login': DEMO_USERNAME}
    except Exception as exc:
        try:
            from models import db
            db.session.rollback()
        except Exception:
            pass
        logger.warning('Demo seed failed: %s', exc)
        return {'ok': False, 'error': str(exc)}
