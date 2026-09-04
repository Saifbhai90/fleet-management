# -*- coding: utf-8 -*-
"""Driver job-history helpers: eligibility + timeline build."""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from sqlalchemy import or_

from app import db
from models import Driver, DriverStatusChange, DriverTransfer


def driver_has_prior_job_history(driver_id: int) -> bool:
    """True if driver ever left/rejoined or was transferred."""
    if not driver_id:
        return False
    if (
        db.session.query(DriverStatusChange.id)
        .filter_by(driver_id=driver_id)
        .limit(1)
        .first()
    ):
        return True
    if (
        db.session.query(DriverTransfer.id)
        .filter_by(driver_id=driver_id)
        .limit(1)
        .first()
    ):
        return True
    return False


def is_first_assignment_eligible(driver: Driver | None) -> bool:
    """Driver-Vehicle Assign form: only never-before-assigned (no job history)."""
    if not driver:
        return False
    if driver.vehicle_id:
        return False
    status = (driver.status or "Active").strip().lower()
    if status == "left":
        return False
    if driver_has_prior_job_history(driver.id):
        return False
    return True


def query_first_assignment_eligible_drivers():
    """Unassigned drivers with no left/rejoin/transfer history."""
    hist_sc = db.session.query(DriverStatusChange.driver_id).distinct()
    hist_tr = db.session.query(DriverTransfer.driver_id).distinct()
    hist_ids = {r[0] for r in hist_sc.all()} | {r[0] for r in hist_tr.all()}
    q = Driver.query.filter(Driver.vehicle_id.is_(None))
    q = q.filter(
        or_(
            Driver.status.is_(None),
            ~Driver.status.ilike("left"),
        )
    )
    if hist_ids:
        q = q.filter(~Driver.id.in_(hist_ids))
    return q.order_by(Driver.name)


def _assignment_snap_from_left(left: DriverStatusChange):
    return SimpleNamespace(
        vehicle=left.left_vehicle,
        project=left.left_project,
        district=left.left_district,
        shift=left.left_shift,
        assign_remarks="",
    )


def _assignment_snap_from_transfer(transfer: DriverTransfer, remarks: str = ""):
    return SimpleNamespace(
        vehicle=transfer.old_vehicle,
        project=transfer.old_project,
        district=transfer.old_district,
        shift=transfer.old_shift,
        assign_remarks=remarks or "",
    )


def _recover_initial_assign_date(driver: Driver, first_left: DriverStatusChange) -> date:
    """Best-effort original start date when assign_date was overwritten."""
    created = None
    if getattr(driver, "created_at", None):
        created = driver.created_at.date()
    if created and created < first_left.change_date:
        return created
    # Fall back to day before first left
    return first_left.change_date - timedelta(days=1)


def build_driver_job_history(driver: Driver) -> list[dict]:
    """Profile/timeline events: assignment, transfer, status (left/rejoin).

    - Initial ASSIGNMENT uses original assign_date (not rejoin overwrite).
    - Vehicle snapshot prefers transfer.old_* / current vehicle / first left_*.
    - Bogus assign_date after last left with no vehicle is ignored.
    """
    transfers = (
        DriverTransfer.query.filter_by(driver_id=driver.id)
        .order_by(DriverTransfer.transfer_date.asc(), DriverTransfer.id.asc())
        .all()
    )
    status_changes = (
        DriverStatusChange.query.filter_by(driver_id=driver.id)
        .order_by(DriverStatusChange.change_date.asc(), DriverStatusChange.id.asc())
        .all()
    )

    first_left = next((s for s in status_changes if s.action_type == "left"), None)
    rejoin_dates = {
        s.change_date for s in status_changes if s.action_type == "rejoin"
    }
    last_status_date = status_changes[-1].change_date if status_changes else None

    job_history: list[dict] = []

    assign_date = driver.assign_date
    bogus_after_cycle = bool(
        assign_date
        and last_status_date
        and assign_date > last_status_date
        and not driver.vehicle_id
    )
    # Legacy rejoin overwrote assign_date to rejoin_date
    assign_is_rejoin_overwrite = bool(
        assign_date
        and assign_date in rejoin_dates
        and first_left
        and assign_date > first_left.change_date
    )

    def _snap_for_initial():
        if transfers:
            return _assignment_snap_from_transfer(
                transfers[0], driver.assign_remarks or ""
            )
        if driver.vehicle_id and driver.vehicle:
            return driver
        if first_left and first_left.left_vehicle_id:
            return _assignment_snap_from_left(first_left)
        return driver

    initial_date = None
    if assign_date and not bogus_after_cycle and not assign_is_rejoin_overwrite:
        if not first_left or assign_date <= first_left.change_date:
            initial_date = assign_date
        elif first_left:
            # assign_date after first left but not caught as bogus (e.g. still on vehicle)
            initial_date = _recover_initial_assign_date(driver, first_left)
    elif first_left and (bogus_after_cycle or assign_is_rejoin_overwrite or not assign_date):
        initial_date = _recover_initial_assign_date(driver, first_left)
    elif assign_date and not first_left and not bogus_after_cycle:
        initial_date = assign_date

    if initial_date:
        job_history.append(
            {
                "date": initial_date,
                "type": "assignment",
                "data": _snap_for_initial(),
            }
        )

    for t in transfers:
        job_history.append({"date": t.transfer_date, "type": "transfer", "data": t})
    for s in status_changes:
        job_history.append({"date": s.change_date, "type": "status", "data": s})

    job_history.sort(key=lambda x: (x["date"], 0 if x["type"] == "assignment" else 1))

    today = date.today()
    for i, h in enumerate(job_history):
        next_date = job_history[i + 1]["date"] if i + 1 < len(job_history) else today
        h["duration_days"] = (next_date - h["date"]).days

    return job_history


def build_driver_job_history_api(driver: Driver) -> list[dict]:
    """Compact timeline rows for /get_driver_details JSON."""
    events = build_driver_job_history(driver)
    out = []
    for h in events:
        d = h["date"]
        date_str = d.strftime("%d-%m-%Y") if d else "-"
        if h["type"] == "assignment":
            snap = h["data"]
            veh = getattr(snap, "vehicle", None)
            veh_no = veh.vehicle_no if veh else "-"
            if veh and getattr(veh, "model", None):
                veh_no += f" ({veh.model})"
            proj = getattr(snap, "project", None)
            dist = getattr(snap, "district", None)
            out.append(
                {
                    "date": date_str,
                    "type": "assignment",
                    "title": "ASSIGNMENT",
                    "line1": f"To Vehicle: {veh_no}",
                    "line2": f"Project: {proj.name if proj else '-'}",
                    "line3": (
                        f"District: {dist.name if dist else '-'} | "
                        f"Shift: {getattr(snap, 'shift', None) or '-'}"
                    ),
                    "remarks": getattr(snap, "assign_remarks", None) or "",
                }
            )
        elif h["type"] == "transfer":
            t = h["data"]
            new_veh = t.new_vehicle.vehicle_no if t.new_vehicle else "-"
            if t.new_vehicle and t.new_vehicle.model:
                new_veh += f" ({t.new_vehicle.model})"
            if t.is_shift_only:
                out.append(
                    {
                        "date": date_str,
                        "type": "shift_change",
                        "title": "SHIFT CHANGE",
                        "line1": f"Vehicle: {new_veh}",
                        "line2": f"Shift: {t.old_shift or '-'} → {t.new_shift or '-'}",
                        "line3": (
                            f"Project: {t.new_project.name if t.new_project else '-'} | "
                            f"District: {t.new_district.name if t.new_district else '-'}"
                        ),
                        "remarks": t.remarks or "",
                    }
                )
            else:
                out.append(
                    {
                        "date": date_str,
                        "type": "transfer",
                        "title": "TRANSFER",
                        "line1": f"To Vehicle: {new_veh}",
                        "line2": f"Project: {t.new_project.name if t.new_project else '-'}",
                        "line3": (
                            f"District: {t.new_district.name if t.new_district else '-'} | "
                            f"Shift: {t.new_shift or '-'}"
                        ),
                        "remarks": t.remarks or "",
                    }
                )
        elif h["type"] == "status":
            sc = h["data"]
            if sc.action_type == "left":
                lv = sc.left_vehicle.vehicle_no if sc.left_vehicle else "-"
                if sc.left_vehicle and sc.left_vehicle.model:
                    lv += f" ({sc.left_vehicle.model})"
                out.append(
                    {
                        "date": date_str,
                        "type": "left",
                        "title": "JOB LEFT",
                        "line1": f"Reason: {sc.reason or '-'}",
                        "line2": f"From Vehicle: {lv}",
                        "line3": (
                            f"District: {sc.left_district.name if sc.left_district else '-'} | "
                            f"Project: {sc.left_project.name if sc.left_project else '-'}"
                        ),
                        "remarks": sc.remarks or "",
                    }
                )
            elif sc.action_type == "rejoin":
                rv = sc.new_vehicle.vehicle_no if sc.new_vehicle else "-"
                if sc.new_vehicle and sc.new_vehicle.model:
                    rv += f" ({sc.new_vehicle.model})"
                out.append(
                    {
                        "date": date_str,
                        "type": "rejoin",
                        "title": "REJOINED",
                        "line1": f"To Vehicle: {rv}",
                        "line2": f"Project: {sc.new_project.name if sc.new_project else '-'}",
                        "line3": (
                            f"District: {sc.new_district.name if sc.new_district else '-'} | "
                            f"Shift: {sc.new_shift or '-'}"
                        ),
                        "remarks": sc.remarks or "",
                    }
                )
    return out


def job_history_counts(job_history: list[dict]) -> dict:
    counts = {
        "assignment": 0,
        "transfer": 0,
        "shift_change": 0,
        "left": 0,
        "rejoin": 0,
    }
    for h in job_history:
        if h["type"] == "assignment":
            counts["assignment"] += 1
        elif h["type"] == "transfer":
            if h["data"].is_shift_only:
                counts["shift_change"] += 1
            else:
                counts["transfer"] += 1
        elif h["type"] == "status":
            if h["data"].action_type == "left":
                counts["left"] += 1
            else:
                counts["rejoin"] += 1
    return counts
