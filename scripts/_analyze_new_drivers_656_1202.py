"""Find why new drivers on 656 and 1202 missing from Day Wise report."""
import os
import sys
from calendar import monthrange
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('DATABASE_URL', 'sqlite:///' + os.path.join(ROOT, 'db', 'local.db').replace('\\', '/'))

from app import app
from models import db, Driver, Vehicle, DriverAttendance, DriverTransfer, DriverStatusChange

with app.app_context():
    from routes import (
        _tra_report_driver_ids_for_month,
        _TraMonthCache,
        _build_driver_daily_attendance_report_payload,
    )

    year, month = 2026, 6
    _, ndays = monthrange(year, month)
    start_d, end_d = date(year, month, 1), date(year, month, ndays)

    vehicles = Vehicle.query.filter(
        db.or_(
            Vehicle.vehicle_no.like('%656%'),
            Vehicle.vehicle_no.like('%1202%'),
        )
    ).all()
    print('=== VEHICLES ===')
    for v in vehicles:
        print(f'{v.vehicle_no} id={v.id} proj={v.project_id} dist={v.district_id} cap={v.driver_capacity}')

    print('\n=== DRIVERS currently on these vehicles ===')
    vids = [v.id for v in vehicles]
    for d in Driver.query.filter(Driver.vehicle_id.in_(vids)).order_by(Driver.name):
        vno = d.vehicle.vehicle_no if d.vehicle else None
        print(
            f'id={d.id} {d.name} status={d.status} veh={vno} shift={d.shift} '
            f'assign_date={d.assign_date}'
        )

    print('\n=== Recent transfers involving these vehicles (2026) ===')
    for t in DriverTransfer.query.filter(
        db.or_(
            DriverTransfer.old_vehicle_id.in_(vids),
            DriverTransfer.new_vehicle_id.in_(vids),
        ),
        DriverTransfer.transfer_date >= date(2026, 1, 1),
    ).order_by(DriverTransfer.transfer_date.desc()):
        print(
            f'{t.transfer_date} driver={t.driver.name} '
            f'{t.old_vehicle.vehicle_no if t.old_vehicle else None} -> '
            f'{t.new_vehicle.vehicle_no if t.new_vehicle else None}'
        )

    print('\n=== Recent rejoins TO these vehicles (2026) ===')
    for sc in DriverStatusChange.query.filter(
        DriverStatusChange.action_type == 'rejoin',
        DriverStatusChange.new_vehicle_id.in_(vids),
        DriverStatusChange.change_date >= date(2026, 1, 1),
    ).order_by(DriverStatusChange.change_date.desc()):
        print(f'{sc.change_date} {sc.driver.name} -> {sc.new_vehicle.vehicle_no if sc.new_vehicle else None}')

    for v in vehicles:
        pid, did = v.project_id, v.district_id
        print(f'\n=== REPORT CHECK {v.vehicle_no} (id={v.id}) ===')
        eligible = _tra_report_driver_ids_for_month(
            start_d, end_d, pid, did, v.id, None, [], [], [], [],
        )
        print(f'eligible count={len(eligible)}')
        cache = _TraMonthCache(start_d, end_d, eligible)
        cache.load()
        for d in Driver.query.filter(Driver.vehicle_id == v.id):
            on_m = cache.driver_on_duty_in_month(d)
            segs = cache.segments(d)
            print(f'  CURRENT {d.name}: eligible={d.id in eligible} on_duty_month={on_m} segments={len(segs)}')
            for seg in segs:
                eff = seg['eff']
                vn = eff.get('vehicle').vehicle_no if eff.get('vehicle') else None
                print(f'    {seg["segment_start"]}..{seg["segment_end"]} veh={vn}')

        payload = _build_driver_daily_attendance_report_payload(
            month, year, pid, did, vehicle_id=v.id,
        )
        names = [r['driver_name'] for r in payload['report']]
        print(f'  payload rows ({len(names)}): {names}')

        for d in Driver.query.filter(Driver.vehicle_id == v.id):
            if d.name not in names:
                print(f'  MISSING FROM PAYLOAD: {d.name} (assign_date={d.assign_date})')

        # Attendance in June where driver was on this vehicle
        print('  June attendance on this vehicle (by transfer history):')
        seen = set()
        for a in DriverAttendance.query.filter(
            DriverAttendance.attendance_date >= start_d,
            DriverAttendance.attendance_date <= end_d,
        ).order_by(DriverAttendance.attendance_date):
            vid = cache.vehicle_id_on_date(a.driver_id, a.attendance_date)
            if vid != v.id or a.driver_id in seen:
                continue
            seen.add(a.driver_id)
            d = Driver.query.get(a.driver_id)
            in_names = d.name in names
            print(f'    {d.name} in_payload={in_names} assign={d.assign_date} current_veh={d.vehicle.vehicle_no if d.vehicle else None}')
