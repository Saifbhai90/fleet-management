# -*- coding: utf-8 -*-
"""Backfill fleet_score_daily so the Fleet Score Trend has history on day one.

The report only reads days that were snapshotted, and the nightly job only ever
adds today onward. A day costs one SOAP call per vehicle, which is why the page
caps on-demand backfill at 10 days — run this to fill a longer stretch.

    python tools/snapshot_fleet_scores.py --days 30      # last 30 days
    python tools/snapshot_fleet_scores.py --days 7       # last week
    python tools/snapshot_fleet_scores.py --rebuild --days 3   # redo recent days
    python tools/snapshot_fleet_scores.py --account 1 --days 30
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('SKIP_STARTUP_TASKS', '1')

from sqlalchemy import func  # noqa: E402

from app import app, db  # noqa: E402
from models import FleetScoreDaily, FleetScoreSyncStatus, PortalXSAccount  # noqa: E402
from services.fleet_score_service import (  # noqa: E402
    missing_days, snapshot_day,
)
from utils import pk_date  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=30,
                    help='how many days back from today (default 30)')
    ap.add_argument('--account', type=int, default=0,
                    help='PortalXS account id (default: every active one)')
    ap.add_argument('--rebuild', action='store_true',
                    help='re-snapshot days that already have one')
    args = ap.parse_args()

    with app.app_context():
        print('creating tables if needed...')
        FleetScoreDaily.__table__.create(db.engine, checkfirst=True)
        FleetScoreSyncStatus.__table__.create(db.engine, checkfirst=True)

        if args.account:
            accounts = [db.session.get(PortalXSAccount, args.account)]
            accounts = [a for a in accounts if a]
        else:
            accounts = PortalXSAccount.query.filter_by(is_active=True).all()
        if not accounts:
            print('no active PortalXS account found')
            return

        today = pk_date()
        first = today - timedelta(days=args.days - 1)

        for acct in accounts:
            if args.rebuild:
                days = [first + timedelta(days=i) for i in range(args.days)]
            else:
                days = missing_days(acct.id, first, today)
            print(f'\naccount {acct.id} ({acct.label}): '
                  f'{len(days)} day(s) to snapshot, {first} .. {today}')

            started = time.perf_counter()
            for i, day in enumerate(days, 1):
                t0 = time.perf_counter()
                try:
                    res = snapshot_day(acct.id, day, source='manual')
                except Exception as exc:
                    db.session.rollback()
                    print(f'  [{i}/{len(days)}] {day}  FAILED: '
                          f'{str(exc).splitlines()[0][:80]}')
                    continue
                print(f"  [{i}/{len(days)}] {day}  "
                      f"{res['stored']:>3}/{res['vehicles']:<3} vehicles, "
                      f"{res['error_count']} error(s)  "
                      f'({time.perf_counter() - t0:.1f}s)')
            print(f'  done in {time.perf_counter() - started:.0f}s')

        total = db.session.query(func.count(FleetScoreDaily.id)).scalar() or 0
        span = db.session.query(func.min(FleetScoreDaily.task_date),
                                func.max(FleetScoreDaily.task_date)).first()
        print(f'\nfleet_score_daily: {total:,} rows, {span[0]} .. {span[1]}')


if __name__ == '__main__':
    main()
