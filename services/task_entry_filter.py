"""Pure filter-lock helpers for New Task Entry / Pending (no Flask / DB)."""


def coerce_task_entry_location_locks(
    district_id,
    project_id,
    *,
    is_master_or_admin,
    allowed_districts,
    allowed_projects,
    valid_district_ids,
    scoped_project_ids,
):
    """Lock district/project only when the assigned id is still in the live scoped lists."""
    tef = {'lock_district': False, 'lock_project': False, 'lock_vehicle': False}
    did = int(district_id or 0)
    pid = int(project_id or 0)
    valid_district_ids = set(valid_district_ids or [])
    if is_master_or_admin:
        if did and valid_district_ids and did not in valid_district_ids:
            did = 0
        if pid and scoped_project_ids is not None and pid not in scoped_project_ids:
            pid = 0
        return did, pid, tef

    lad = set(allowed_districts or [])
    lap = set(allowed_projects or [])
    if len(lad) == 1:
        only_d = next(iter(lad))
        if not valid_district_ids or only_d in valid_district_ids:
            did = only_d
            tef['lock_district'] = True
    if len(lap) == 1:
        only_p = next(iter(lap))
        if scoped_project_ids is None or only_p in scoped_project_ids:
            pid = only_p
            tef['lock_project'] = True
    if did and valid_district_ids and did not in valid_district_ids:
        did = 0
        tef['lock_district'] = False
    if pid and scoped_project_ids is not None and pid not in scoped_project_ids:
        pid = 0
        tef['lock_project'] = False
    return did, pid, tef


def coerce_task_entry_vehicle_lock(
    vehicle_id,
    tef,
    *,
    is_master_or_admin,
    allowed_vehicles,
    scoped_vehicle_ids,
):
    """Lock vehicle only when the assigned vehicle is in the current district/project list."""
    tef = dict(tef or {})
    tef.setdefault('lock_district', False)
    tef.setdefault('lock_project', False)
    tef['lock_vehicle'] = False
    vid = int(vehicle_id or 0)
    scoped_vehicle_ids = set(scoped_vehicle_ids or [])
    if is_master_or_admin:
        if vid and scoped_vehicle_ids and vid not in scoped_vehicle_ids:
            vid = 0
        return vid, tef

    lav = set(allowed_vehicles or [])
    if len(lav) == 1:
        only_v = next(iter(lav))
        if only_v in scoped_vehicle_ids:
            vid = only_v
            tef['lock_vehicle'] = True
        else:
            vid = 0
    elif vid and scoped_vehicle_ids and vid not in scoped_vehicle_ids:
        vid = 0
    return vid, tef
