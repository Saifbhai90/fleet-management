# -*- coding: utf-8 -*-
"""Create the activity-rollup tables / device-health index and backfill history.

The Stoppage & Dwell and Device Health reports build missing days on demand, but
that path is budgeted for a web request. Run this once after deploying to fill
in the existing history in one pass.

    python tools/build_activity_rollup.py              # all days present in source
    python tools/build_activity_rollup.py --days 30    # only the last 30 days
    python tools/build_activity_rollup.py --rebuild    # redo days already built
    python tools/build_activity_rollup.py --summary-only  # presence rollup only
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('SKIP_STARTUP_TASKS', '1')

from sqlalchemy import func  # noqa: E402

from app import app, db  # noqa: E402
from models import (  # noqa: E402
    VehicleActivityDaySummary,
    VehicleActivityRecord,
    VehicleStopLocationDaily,
    VehicleStopRollupStatus,
)
from services.activity_rollup_service import (  # noqa: E402
    build_all_day_summaries, build_day, unbuilt_days,
)
from services.device_health_service import ensure_device_health_index  # noqa: E402


def source_days(limit_days: int = 0) -> list:
    """Dates that actually have GPS points, newest first."""
    query = (db.session.query(VehicleActivityRecord.task_date)
             .distinct()
             .order_by(VehicleActivityRecord.task_date.desc()))
    if limit_days:
        query = query.limit(limit_days)
    return [row[0] for row in query.all()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=0,
                        help='only the most recent N days with data')
    parser.add_argument('--rebuild', action='store_true',
                        help='rebuild days that already have a rollup')
    parser.add_argument('--summary-only', action='store_true',
                        help='rebuild only the per-vehicle presence rollup')
    args = parser.parse_args()

    with app.app_context():
        print('creating tables if needed...')
        VehicleStopLocationDaily.__table__.create(db.engine, checkfirst=True)
        VehicleStopRollupStatus.__table__.create(db.engine, checkfirst=True)
        VehicleActivityDaySummary.__table__.create(db.engine, checkfirst=True)

        print('creating device-health partial index...')
        started = time.perf_counter()
        name = ensure_device_health_index()
        print(f'  {name} ready in {time.perf_counter() - started:.1f}s')

        if args.summary_only:
            # One grouped pass over the whole table beats 126 per-day queries.
            print('\nrebuilding per-vehicle presence rollup in one pass...')
            started = time.perf_counter()
            rows = build_all_day_summaries()
            print(f'  {rows:,} (day, vehicle) rows in {time.perf_counter() - started:.0f}s')
            db.session.remove()
            return

        days = source_days(args.days)
        if not args.rebuild:
            pending = set(unbuilt_days(min(days), max(days))) if days else set()
            days = [d for d in days if d in pending]
        print(f'\nbuilding {len(days)} day(s)...')

        started = time.perf_counter()
        total_rows = 0
        for i, day in enumerate(days, 1):
            t0 = time.perf_counter()
            try:
                result = build_day(day)
            except Exception as exc:
                db.session.rollback()
                print(f'  [{i}/{len(days)}] {day}  FAILED: {str(exc).splitlines()[0][:80]}')
                continue
            if result['rollup_rows'] is None:
                print(f'  [{i}/{len(days)}] {day}  skipped (a running app is '
                      f'rebuilding this day)')
                continue
            total_rows += result['rollup_rows']
            print(f'  [{i}/{len(days)}] {day}  '
                  f"{result['source_points']:>7,} points -> "
                  f"{result['rollup_rows']:>6,} stop rows, "
                  f"{result['vehicles']:>3} vehicles  "
                  f'({time.perf_counter() - t0:.1f}s)')

        elapsed = time.perf_counter() - started
        print(f'\ndone: {total_rows:,} rollup rows in {elapsed:.0f}s')

        stops = db.session.query(func.count(VehicleStopLocationDaily.id)).scalar()
        presence = db.session.query(func.count(VehicleActivityDaySummary.id)).scalar()
        print(f'vehicle_stop_location_daily   {stops:,} rows')
        print(f'vehicle_activity_day_summary  {presence:,} rows')
        db.session.remove()


if __name__ == '__main__':
    main()
