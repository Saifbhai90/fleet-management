"""
Task Operations: Red Tasks, Without Task, Unexecuted Task, Penalty Records.

Extracted from routes.py to reduce file size.
"""

from flask import (
    render_template, redirect, url_for, flash, request,
    session, jsonify, make_response, abort,
    Response, current_app,
)
from app import app, db, csrf
from models import (
    Vehicle, Driver, Project, District, Company, ParkingStation,
    VehicleDailyTask, RedTask, VehicleMoveWithoutTask,
    UnexecutedTaskRecord, PenaltyRecord, DriverAttendance,
    SystemSetting, User, ActivityLog,
)
from forms import (
    RedTaskForm, VehicleMoveWithoutTaskForm, PenaltyRecordForm,
)
from datetime import datetime, date, timedelta
from sqlalchemy import func, text, or_, and_
from auth_utils import user_can_access, get_user_context
from utils import pk_now, pk_date, parse_date, format_date_ddmmyyyy, generate_csv_response
from vehicle_sort_utils import vehicle_order_by, sort_vehicles_in_memory
import re
import os
import json
import csv
import io
from io import BytesIO, StringIO

# Import shared helpers from routes.py
from routes import (
    _multi_word_filter,
    media_url_filter,
    _get_user_scope,
    require_login,
    _nav_back_ctx,
    enforce_data_freeze,
    _vehicle_query_task_report_scope,
    SimplePagination,
    _ensure_unexecuted_task_table,
    _filter_unexecuted_rows_by_search,
    _norm_district_name_key,
    _penalty_record_query,
    _unexecuted_task_rows,
    _workforce_nav_back,
)

from models import EmergencyTaskRecord, VehicleMileageRecord
from forms import PenaltyRecordFilterForm, RedTaskFilterForm, VehicleMoveWithoutTaskFilterForm
from decimal import Decimal
from utils import generate_excel_template
from models import project_district
@app.route('/red-task', methods=['GET', 'POST'])
def red_task_list():
    form = RedTaskFilterForm()
    form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in District.query.order_by(District.name).all()]
    today = pk_date()
    from_date = today
    to_date = today
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    if request.method == 'POST':
        from_date = parse_date(request.form.get('from_date')) or today
        to_date = parse_date(request.form.get('to_date')) or today
        district_id = request.form.get('district_id', type=int) or 0
        project_id = request.form.get('project_id', type=int) or 0
        if from_date and to_date and from_date > to_date:
            from_date, to_date = to_date, from_date
        return redirect(url_for('red_task_list', from_date=from_date.strftime('%d-%m-%Y') if from_date else '', to_date=to_date.strftime('%d-%m-%Y') if to_date else '', district_id=district_id, project_id=project_id))
    from_str = request.args.get('from_date', '')
    to_str = request.args.get('to_date', '')
    if from_str:
        from_date = parse_date(from_str) or from_date
    if to_str:
        to_date = parse_date(to_str) or to_date
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date
    form.from_date.data = from_date
    form.to_date.data = to_date
    form.district_id.data = district_id
    if district_id:
        projects = Project.query.join(project_district).filter(project_district.c.district_id == district_id).order_by(Project.name).all()
        form.project_id.choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in projects]
    else:
        form.project_id.choices = [(0, '-- All Projects --')]
    form.project_id.data = project_id
    query = RedTask.query.filter(RedTask.task_date >= from_date, RedTask.task_date <= to_date)
    if district_id:
        query = query.filter(RedTask.district_id == district_id)
    if project_id:
        query = query.filter(RedTask.project_id == project_id)
    rows = query.order_by(RedTask.task_date.desc(), RedTask.id.desc()).all()
    search = (request.args.get('search') or '').strip()
    if search:
        tokens = [t.lower() for t in search.split() if t]
        def _match(r):
            blob = ' '.join([
                str(r.task_date), r.task_id or '',
                r.district.name if r.district else '',
                r.project.name if r.project else '',
                r.vehicle.vehicle_no if r.vehicle else '',
                r.reason or '', r.driver_name or '',
                r.call_to_dto or '', r.dto_investigation or '', r.action or '',
            ]).lower()
            return all(tok in blob for tok in tokens)
        rows = [r for r in rows if _match(r)]
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = SimplePagination(rows, page, per_page)
    rows = pagination.items
    return render_template('red_task_list.html', form=form, rows=rows, from_date=from_date, to_date=to_date, pagination=pagination, per_page=per_page, search=search,
                          **_nav_back_ctx(url_for('reports_index'), show_without_nav_from=True))



@app.route('/red-task/summary', methods=['GET'])
def red_task_summary():
    """Direct Emergency Task Report (category Red): every Red row counted; group by master district if Excel name matches else by Excel district text."""
    form = RedTaskFilterForm()
    all_districts = District.query.order_by(District.name).all()
    valid_district_ids = {d.id for d in all_districts}

    form.district_id.choices = [(0, '-- Tamam districts --')] + [(d.id, d.name) for d in all_districts]
    today = pk_date()
    from_date = today
    to_date = today
    district_id = request.args.get('district_id', type=int) or 0
    show = request.args.get('show', type=int) or 0

    from_str = request.args.get('from_date', '').strip()
    to_str = request.args.get('to_date', '').strip()
    if from_str:
        from_date = parse_date(from_str) or from_date
    if to_str:
        to_date = parse_date(to_str) or to_date
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date

    if district_id and district_id not in valid_district_ids:
        district_id = 0

    form.from_date.data = from_date
    form.to_date.data = to_date
    form.district_id.data = district_id
    form.project_id.choices = [(0, '—')]
    form.project_id.data = 0

    summary_rows = []
    summary_kind = ''
    summary_title = ''
    grand_count = 0
    grand_fine = Decimal('0')

    if show:
        name_map_all = {}
        for d in all_districts:
            k = _norm_district_name_key(d.name)
            if k not in name_map_all:
                name_map_all[k] = d

        if district_id:
            sel = db.session.get(District, district_id)
            name_map = {_norm_district_name_key(sel.name): sel} if sel else {}
            summary_kind = 'single'
            summary_title = 'Direct Emergency (Red) — selected district (sirf jahan Excel naam is district se match ho)'
        else:
            name_map = name_map_all
            summary_kind = 'by_district'
            summary_title = 'Direct Emergency Task Report — Red category (har Red row; Excel district master se match ho ya na ho)'

        dist_by_id = {d.id: d for d in all_districts}

        fine_lookup = {}
        for rt in RedTask.query.filter(RedTask.task_date >= from_date, RedTask.task_date <= to_date).all():
            k = (rt.task_date, (rt.task_id or '').strip())
            fa = rt.fine_amount if rt.fine_amount is not None else Decimal('0')
            if not isinstance(fa, Decimal):
                fa = Decimal(str(fa))
            fine_lookup[k] = fine_lookup.get(k, Decimal('0')) + fa

        emg_rows = EmergencyTaskRecord.query.filter(
            EmergencyTaskRecord.task_date >= from_date,
            EmergencyTaskRecord.task_date <= to_date,
            EmergencyTaskRecord.category == 'Red',
        ).all()

        groups = {}
        for r in emg_rows:
            nk_excel = _norm_district_name_key(r.district_name)
            d = name_map.get(nk_excel)

            if district_id:
                if not d or d.id != district_id:
                    continue
                gkey = ('id', d.id)
                if gkey not in groups:
                    groups[gkey] = {
                        'district_id': d.id, 'label': d.name, 'count': 0, 'fine': Decimal('0'),
                    }
            elif d:
                gkey = ('id', d.id)
                if gkey not in groups:
                    groups[gkey] = {
                        'district_id': d.id, 'label': d.name, 'count': 0, 'fine': Decimal('0'),
                    }
            else:
                gkey = ('excel', nk_excel)
                if gkey not in groups:
                    groups[gkey] = {
                        'district_id': None,
                        'label': (r.district_name or '').strip() or '(Excel district khali)',
                        'excel_norm': nk_excel,
                        'count': 0, 'fine': Decimal('0'),
                    }

            ent = groups[gkey]
            ent['count'] += 1
            fk = (r.task_date, (r.task_id_ext or '').strip())
            ent['fine'] += fine_lookup.get(fk, Decimal('0'))

        def _sort_summary_key(gk):
            kind, val = gk
            if kind == 'id':
                return (0, (dist_by_id.get(val).name or '').lower())
            return (1, (groups[gk]['label'] or '').lower())

        for gk in sorted(groups.keys(), key=_sort_summary_key):
            ent = groups[gk]
            is_master = gk[0] == 'id'
            summary_rows.append({
                'label': ent['label'],
                'count': ent['count'],
                'fine': ent['fine'],
                'detail_kind': 'master' if is_master else 'excel',
                'district_id': ent['district_id'],
                'excel_norm': ent.get('excel_norm'),
            })
            grand_count += ent['count']
            grand_fine += ent['fine']

    return render_template(
        'red_task_summary.html',
        form=form,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=0,
        summary_rows=summary_rows,
        summary_kind=summary_kind,
        summary_title=summary_title,
        grand_count=grand_count,
        grand_fine=grand_fine,
        show=bool(show),
    )



@app.route('/red-task/summary/detail', methods=['GET'])
def red_task_summary_detail():
    """Emergency Report Red rows: either master district match or Excel-only bucket (excel_norm query param)."""
    today = pk_date()
    from_date = today
    to_date = today
    district_id = request.args.get('district_id', type=int) or 0
    excel_mode = ('excel_norm' in request.args) and not district_id
    excel_norm = request.args.get('excel_norm', '') if excel_mode else None

    from_str = request.args.get('from_date', '').strip()
    to_str = request.args.get('to_date', '').strip()
    if from_str:
        from_date = parse_date(from_str) or from_date
    if to_str:
        to_date = parse_date(to_str) or to_date
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date

    if not district_id and not excel_mode:
        flash('Detail ke liye district ya Excel district bucket zaroori hai.', 'warning')
        return redirect(url_for(
            'red_task_summary',
            show=1,
            from_date=from_date.strftime('%d-%m-%Y'),
            to_date=to_date.strftime('%d-%m-%Y'),
        ))

    saved_map = {}
    for rt in RedTask.query.filter(
        RedTask.task_date >= from_date,
        RedTask.task_date <= to_date,
    ).order_by(RedTask.id.asc()).all():
        k = (rt.task_date, (rt.task_id or '').strip())
        saved_map[k] = rt

    emg_q = EmergencyTaskRecord.query.filter(
        EmergencyTaskRecord.task_date >= from_date,
        EmergencyTaskRecord.task_date <= to_date,
        EmergencyTaskRecord.category == 'Red',
    ).order_by(EmergencyTaskRecord.task_date.desc(), EmergencyTaskRecord.id.desc())

    rows = []
    dist = None
    target_norm = None
    if district_id:
        dist = District.query.get_or_404(district_id)
        target_norm = _norm_district_name_key(dist.name)
        back_q = url_for(
            'red_task_summary',
            show=1,
            from_date=from_date.strftime('%d-%m-%Y'),
            to_date=to_date.strftime('%d-%m-%Y'),
            district_id=district_id,
        )
    else:
        target_norm = excel_norm
        back_q = url_for(
            'red_task_summary',
            show=1,
            from_date=from_date.strftime('%d-%m-%Y'),
            to_date=to_date.strftime('%d-%m-%Y'),
        )

    for r in emg_q.all():
        if _norm_district_name_key(r.district_name) != target_norm:
            continue
        fk = (r.task_date, (r.task_id_ext or '').strip())
        rows.append({'emg': r, 'saved': saved_map.get(fk)})

    if dist:
        scope_label = dist.name
    elif rows:
        scope_label = (rows[0]['emg'].district_name or '').strip() or '(Excel district khali)'
    else:
        scope_label = '(Excel district)'

    return render_template(
        'red_task_summary_detail.html',
        district=dist,
        scope_label=scope_label,
        rows=rows,
        from_date=from_date,
        to_date=to_date,
        back_summary_url=back_q,
    )



@app.route('/red-task/new', methods=['GET', 'POST'])
def red_task_new():
    districts = District.query.order_by(District.name).all()
    view_date = pk_date()
    district_id = request.args.get('district_id', 0, type=int)
    project_id = request.args.get('project_id', 0, type=int)
    date_str = request.args.get('date', '')
    if date_str:
        view_date = parse_date(date_str) or view_date
    projects = []
    if district_id:
        projects = Project.query.join(project_district).filter(project_district.c.district_id == district_id).order_by(Project.name).all()
    else:
        projects = Project.query.order_by(Project.name).all()

    if request.method == 'POST' and request.form.get('save_batch'):
        task_date = parse_date(request.form.get('task_date')) or pk_date()
        did = int(request.form.get('district_id') or 0) or None
        pid = int(request.form.get('project_id') or 0) or None
        saved = 0
        idx = 0
        while True:
            veh_id_raw = request.form.get(f'row_{idx}_vehicle_id')
            if veh_id_raw is None:
                break
            edit_mode = request.form.get(f'row_{idx}_edit_mode', '1') == '1'
            veh_id = int(veh_id_raw) if veh_id_raw else None
            _veh = db.session.get(Vehicle, veh_id) if veh_id else None
            row_did = did or (_veh.district_id if _veh else None)
            row_pid = pid or (_veh.project_id if _veh else None)
            driver_id = int(request.form.get(f'row_{idx}_driver_id') or 0) or None
            reason = (request.form.get(f'row_{idx}_reason') or '').strip() or None
            task_id_ext = (request.form.get(f'row_{idx}_task_id') or '').strip() or None
            call_to_dto = request.form.get(f'row_{idx}_call_to_dto') or None
            dto_investigation = (request.form.get(f'row_{idx}_dto_investigation') or '').strip() or None
            try:
                fine_amt = float(request.form.get(f'row_{idx}_fine_amount') or 0)
            except (ValueError, TypeError):
                fine_amt = 0
            driver_name_val = None
            if driver_id:
                drv = db.session.get(Driver, driver_id)
                if drv:
                    driver_name_val = drv.name
            emg_rec_id = request.form.get(f'row_{idx}_emg_id')
            existing = None
            if emg_rec_id:
                existing = RedTask.query.filter_by(task_date=task_date, vehicle_id=veh_id, task_id=task_id_ext).first()
            if existing:
                # Locked row: do not modify unless user explicitly enables edit mode.
                if not edit_mode:
                    idx += 1
                    continue
                # Extra safety: preserve historical driver if left blank during edit.
                effective_driver_id = driver_id if driver_id is not None else existing.driver_id
                if effective_driver_id:
                    drv_eff = db.session.get(Driver, effective_driver_id)
                    driver_name_val = drv_eff.name if drv_eff else existing.driver_name
                else:
                    driver_name_val = None
                existing.district_id = row_did
                existing.project_id = row_pid
                existing.driver_id = effective_driver_id
                existing.driver_name = driver_name_val
                existing.reason = reason
                existing.call_to_dto = call_to_dto
                existing.dto_investigation = dto_investigation
                existing.action = 'Fine' if fine_amt > 0 else 'No'
                existing.fine_amount = fine_amt
                rec = existing
            else:
                rec = RedTask(
                    task_date=task_date, task_id=task_id_ext, district_id=row_did, project_id=row_pid,
                    vehicle_id=veh_id, driver_id=driver_id, driver_name=driver_name_val,
                    reason=reason, call_to_dto=call_to_dto,
                    dto_investigation=dto_investigation,
                    action='Fine' if fine_amt > 0 else 'No',
                    fine_amount=fine_amt,
                )
                db.session.add(rec)
            db.session.flush()
            PenaltyRecord.query.filter_by(source_type='red_task', source_id=rec.id).delete()
            if fine_amt > 0 and driver_id:
                pen = PenaltyRecord(
                    district_id=row_did, project_id=row_pid, vehicle_id=veh_id,
                    driver_id=driver_id, record_date=task_date,
                    fine=str(fine_amt), remarks='Red Task Fine',
                    source_type='red_task', source_id=rec.id,
                )
                db.session.add(pen)
            saved += 1
            idx += 1
        db.session.commit()
        flash(f'{saved} Red Task entries saved.', 'success')
        return redirect(url_for('red_task_list'))

    rows = []
    _has_filter = date_str != ''
    if _has_filter or district_id or project_id:
        vq = Vehicle.query
        if district_id:
            vq = vq.filter_by(district_id=district_id)
        if project_id:
            vq = vq.filter_by(project_id=project_id)
        _vehs = vq.all()
        vehicle_nos = [v.vehicle_no for v in _vehs]
        veh_map = {v.vehicle_no: v for v in _vehs}
        emg_recs = EmergencyTaskRecord.query.filter(
            EmergencyTaskRecord.task_date == view_date,
            EmergencyTaskRecord.amb_reg_no.in_(vehicle_nos) if vehicle_nos else EmergencyTaskRecord.id > 0,
            EmergencyTaskRecord.category == 'Red',
        ).all()
        saved_recs = RedTask.query.filter_by(task_date=view_date)
        if district_id:
            saved_recs = saved_recs.filter_by(district_id=district_id)
        if project_id:
            saved_recs = saved_recs.filter_by(project_id=project_id)
        saved_map = {}
        for sr in saved_recs.all():
            key = (sr.vehicle_id, sr.task_id or '')
            saved_map[key] = sr
        for e in emg_recs:
            veh = veh_map.get(e.amb_reg_no)
            drivers = []
            if veh:
                drivers = Driver.query.filter_by(vehicle_id=veh.id, status='Active').all()
            saved = saved_map.get((veh.id if veh else None, e.task_id_ext or ''))
            if saved and saved.driver_id:
                _saved_drv = db.session.get(Driver, saved.driver_id)
                if _saved_drv and all(d.id != _saved_drv.id for d in drivers):
                    drivers.append(_saved_drv)
            rows.append({
                'emg': e,
                'vehicle': veh,
                'drivers': drivers,
                'saved': saved,
            })
    return render_template('red_task_form.html', rows=rows, view_date=view_date,
                           district_id=district_id, project_id=project_id,
                           districts=districts, projects=projects, title='Add Red Task',
                           **_nav_back_ctx(url_for('red_task_list'), show_without_nav_from=True))



@app.route('/red-task/<int:pk>/edit', methods=['GET', 'POST'])
def red_task_edit(pk):
    rec = RedTask.query.get_or_404(pk)
    form = RedTaskForm(obj=rec)
    form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in District.query.order_by(District.name).all()]
    form.vehicle_id.choices = [(0, '-- Select Vehicle --')] + [(v.id, v.vehicle_no) for v in Vehicle.query.order_by(*vehicle_order_by()).all()]
    if rec.district_id:
        projects = Project.query.join(project_district).filter(project_district.c.district_id == rec.district_id).order_by(Project.name).all()
        form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in projects]
    else:
        form.project_id.choices = [(0, '-- Select Project --')]
    if request.method == 'GET':
        form.task_date.data = rec.task_date
        form.task_id.data = rec.task_id or ''
        form.district_id.data = rec.district_id or 0
        form.project_id.data = rec.project_id or 0
        form.vehicle_id.data = rec.vehicle_id or 0
        form.reason.data = rec.reason or ''
        form.driver_name.data = rec.driver_name or ''
        form.call_to_dto.data = rec.call_to_dto or ''
        form.dto_investigation.data = rec.dto_investigation or ''
        form.action.data = rec.action or ''
    if request.method == 'POST' and form.validate_on_submit():
        task_date = form.task_date.data
        district_id = form.district_id.data or None
        if district_id == 0:
            district_id = None
        project_id = form.project_id.data or None
        if project_id == 0:
            project_id = None
        vehicle_id = form.vehicle_id.data or None
        if vehicle_id == 0:
            vehicle_id = None
        rec.task_date = task_date
        rec.task_id = form.task_id.data.strip() or None
        rec.district_id = district_id
        rec.project_id = project_id
        rec.vehicle_id = vehicle_id
        rec.reason = form.reason.data.strip() or None
        rec.driver_name = form.driver_name.data.strip() or None
        rec.call_to_dto = form.call_to_dto.data or None
        rec.dto_investigation = form.dto_investigation.data.strip() or None
        rec.action = form.action.data or None
        db.session.commit()
        flash('Red Task updated.', 'success')
        return redirect(url_for('red_task_list'))
    return render_template('red_task_edit.html', form=form, title='Edit Red Task', rec=rec,
                          **_nav_back_ctx(url_for('red_task_list'), show_without_nav_from=True))



@app.route('/vehicle-move-without-task', methods=['GET', 'POST'])
def without_task_list():
    form = VehicleMoveWithoutTaskFilterForm()
    form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in District.query.order_by(District.name).all()]
    today = pk_date()
    from_date = today
    to_date = today
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    if request.method == 'POST':
        from_date = parse_date(request.form.get('from_date')) or today
        to_date = parse_date(request.form.get('to_date')) or today
        district_id = request.form.get('district_id', type=int) or 0
        project_id = request.form.get('project_id', type=int) or 0
        if from_date and to_date and from_date > to_date:
            from_date, to_date = to_date, from_date
        return redirect(url_for('without_task_list', from_date=from_date.strftime('%d-%m-%Y') if from_date else '', to_date=to_date.strftime('%d-%m-%Y') if to_date else '', district_id=district_id, project_id=project_id))
    from_str = request.args.get('from_date', '')
    to_str = request.args.get('to_date', '')
    if from_str:
        from_date = parse_date(from_str) or from_date
    if to_str:
        to_date = parse_date(to_str) or to_date
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date
    form.from_date.data = from_date
    form.to_date.data = to_date
    form.district_id.data = district_id
    if district_id:
        projects = Project.query.join(project_district).filter(project_district.c.district_id == district_id).order_by(Project.name).all()
        form.project_id.choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in projects]
    else:
        form.project_id.choices = [(0, '-- All Projects --')]
    form.project_id.data = project_id
    query = VehicleMoveWithoutTask.query.options(
        db.joinedload(VehicleMoveWithoutTask.district),
        db.joinedload(VehicleMoveWithoutTask.project),
        db.joinedload(VehicleMoveWithoutTask.vehicle),
        db.joinedload(VehicleMoveWithoutTask.driver),
    ).filter(
        VehicleMoveWithoutTask.move_date >= from_date,
        VehicleMoveWithoutTask.move_date <= to_date
    )
    if district_id:
        query = query.filter(VehicleMoveWithoutTask.district_id == district_id)
    if project_id:
        query = query.filter(VehicleMoveWithoutTask.project_id == project_id)
    rows = query.order_by(VehicleMoveWithoutTask.move_date.desc(), VehicleMoveWithoutTask.id.desc()).all()
    search = (request.args.get('search') or '').strip()
    if search:
        tokens = [t.lower() for t in search.split() if t]
        def _match(r):
            blob = ' '.join([
                str(r.move_date),
                r.district.name if r.district else '',
                r.project.name if r.project else '',
                r.vehicle.vehicle_no if r.vehicle else '',
                r.driver.name if r.driver else '',
                r.remarks or '', r.fine or '',
            ]).lower()
            return all(tok in blob for tok in tokens)
        rows = [r for r in rows if _match(r)]
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = SimplePagination(rows, page, per_page)
    rows = pagination.items
    return render_template('without_task_list.html', form=form, rows=rows, from_date=from_date, to_date=to_date, pagination=pagination, per_page=per_page, search=search,
                          **_nav_back_ctx(url_for('reports_index'), show_without_nav_from=True))



@app.route('/unexecuted-task-report', methods=['GET', 'POST'])
def unexecuted_task_report():
    _ensure_unexecuted_task_table()
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)

    today = pk_date()
    from_date = parse_date(request.values.get('from_date')) or today
    to_date = parse_date(request.values.get('to_date')) or today
    if from_date > to_date:
        from_date, to_date = to_date, from_date
    district_id = request.values.get('district_id', type=int) or 0
    project_id = request.values.get('project_id', type=int) or 0
    vehicle_id = request.values.get('vehicle_id', type=int) or 0
    category = (request.values.get('category') or '').strip()
    shift = (request.values.get('shift') or '').strip().lower()
    check_type = (request.values.get('check_type') or '').strip().lower()
    if check_type not in ('', 'above', 'below'):
        check_type = ''
    running_km_limit_raw = (request.values.get('running_km_limit') or '').strip()
    running_km_limit = None
    if running_km_limit_raw:
        try:
            running_km_limit = float(running_km_limit_raw)
            if running_km_limit < 0:
                running_km_limit = None
                running_km_limit_raw = ''
        except Exception:
            running_km_limit = None
            running_km_limit_raw = ''

    if request.method == 'POST' and request.form.get('save_batch') == '1':
        saved = 0
        idx = 0
        while True:
            emg_id_raw = request.form.get(f'row_{idx}_emg_id')
            if emg_id_raw is None:
                break
            try:
                emg_id = int(emg_id_raw)
            except (ValueError, TypeError):
                idx += 1
                continue
            emg = db.session.get(EmergencyTaskRecord, emg_id)
            if not emg:
                idx += 1
                continue

            try:
                did = int(request.form.get(f'row_{idx}_district_id') or 0) or None
            except (ValueError, TypeError):
                did = None
            try:
                pid = int(request.form.get(f'row_{idx}_project_id') or 0) or None
            except (ValueError, TypeError):
                pid = None
            try:
                vid = int(request.form.get(f'row_{idx}_vehicle_id') or 0) or None
            except (ValueError, TypeError):
                vid = None
            try:
                driver_id = int(request.form.get(f'row_{idx}_driver_id') or 0) or None
            except (ValueError, TypeError):
                driver_id = None
            remarks = (request.form.get(f'row_{idx}_remarks') or '').strip() or None
            try:
                fine_amt = float(request.form.get(f'row_{idx}_fine') or 0)
            except (ValueError, TypeError):
                fine_amt = 0

            rec = UnexecutedTaskRecord.query.filter_by(emergency_task_record_id=emg_id).first()
            if rec:
                rec.task_date = emg.task_date
                rec.district_id = did
                rec.project_id = pid
                rec.vehicle_id = vid
                rec.driver_id = driver_id
                rec.remarks = remarks
                rec.fine = str(fine_amt) if fine_amt > 0 else 'No'
                rec.fine_amount = fine_amt
            else:
                rec = UnexecutedTaskRecord(
                    task_date=emg.task_date,
                    emergency_task_record_id=emg_id,
                    district_id=did,
                    project_id=pid,
                    vehicle_id=vid,
                    driver_id=driver_id,
                    remarks=remarks,
                    fine=str(fine_amt) if fine_amt > 0 else 'No',
                    fine_amount=fine_amt,
                )
                db.session.add(rec)
            db.session.flush()

            PenaltyRecord.query.filter_by(source_type='unexecuted_task', source_id=rec.id).delete()
            if fine_amt > 0 and driver_id:
                db.session.add(PenaltyRecord(
                    district_id=did, project_id=pid, vehicle_id=vid, driver_id=driver_id,
                    record_date=emg.task_date,
                    fine=str(fine_amt),
                    remarks='Unexecuted Task Fine',
                    source_type='unexecuted_task',
                    source_id=rec.id,
                ))
            saved += 1
            idx += 1

        db.session.commit()
        flash(f'{saved} unexecuted task record(s) saved.', 'success')
        return redirect(url_for(
            'unexecuted_task_report',
            from_date=from_date.strftime('%d-%m-%Y'),
            to_date=to_date.strftime('%d-%m-%Y'),
            district_id=district_id,
            project_id=project_id,
            vehicle_id=vehicle_id,
            category=category,
            shift=shift,
            check_type=check_type,
            running_km_limit=running_km_limit_raw,
        ))

    district_q = District.query.order_by(District.name)
    project_q = Project.query.order_by(Project.name)
    vehicle_q = Vehicle.query.order_by(*vehicle_order_by())

    # Global dropdown scope based on valid assignment+deployment combinations.
    valid_project_pairs = set(
        (int(pid), int(did))
        for pid, did in db.session.query(project_district.c.project_id, project_district.c.district_id).all()
    )
    valid_vehicles = [v for v in vehicle_q.all()
                      if v and v.project_id and v.district_id
                      and (int(v.project_id), int(v.district_id)) in valid_project_pairs]
    valid_vehicle_ids = [v.id for v in valid_vehicles]
    valid_district_ids = sorted({int(v.district_id) for v in valid_vehicles if v.district_id})
    valid_project_ids = sorted({int(v.project_id) for v in valid_vehicles if v.project_id})

    district_q = district_q.filter(District.id.in_(valid_district_ids or [-1]))
    project_q = project_q.filter(Project.id.in_(valid_project_ids or [-1]))
    vehicle_q = Vehicle.query.filter(Vehicle.id.in_(valid_vehicle_ids or [-1])).order_by(*vehicle_order_by())

    if not is_master_or_admin:
        allowed_vehicle_ids = list(set(allowed_vehicles or []))
        if not allowed_vehicle_ids:
            allowed_vehicle_ids = [-1]
        vehicle_q = vehicle_q.filter(Vehicle.id.in_(allowed_vehicle_ids))
        district_ids_from_vehicle = [d[0] for d in db.session.query(Vehicle.district_id).filter(Vehicle.id.in_(allowed_vehicle_ids), Vehicle.district_id.isnot(None)).distinct().all()]
        project_ids_from_vehicle = [p[0] for p in db.session.query(Vehicle.project_id).filter(Vehicle.id.in_(allowed_vehicle_ids), Vehicle.project_id.isnot(None)).distinct().all()]
        district_q = district_q.filter(District.id.in_(district_ids_from_vehicle or [-1]))
        project_q = project_q.filter(Project.id.in_(project_ids_from_vehicle or [-1]))

    if district_id:
        project_q = project_q.join(project_district).filter(project_district.c.district_id == district_id)
        vehicle_q = vehicle_q.filter(Vehicle.district_id == district_id)
    if project_id:
        vehicle_q = vehicle_q.filter(Vehicle.project_id == project_id)

    districts = district_q.all()
    projects = project_q.all()
    vehicles = vehicle_q.all()

    out_rows = _unexecuted_task_rows(
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        vehicle_id=vehicle_id,
        category=category,
        shift=shift,
        check_type=check_type,
        running_km_limit=running_km_limit,
        allowed_projects=allowed_projects,
        allowed_districts=allowed_districts,
        allowed_vehicles=allowed_vehicles,
        is_master_or_admin=is_master_or_admin,
    )
    total = len(out_rows)
    _uv = set()
    for _r in out_rows:
        _v = _r.get('vehicle')
        if _v and getattr(_v, 'id', None):
            _uv.add(int(_v.id))
    unique_vehicle_count = len(_uv)

    return render_template(
        'unexecuted_task_report.html',
        rows=out_rows,
        total=total,
        unique_vehicle_count=unique_vehicle_count,
        from_date=from_date,
        to_date=to_date,
        district_id=district_id,
        project_id=project_id,
        vehicle_id=vehicle_id,
        category=category,
        shift=shift,
        check_type=check_type,
        running_km_limit=running_km_limit_raw,
        districts=districts,
        projects=projects,
        vehicles=vehicles,
        **_nav_back_ctx(url_for('reports_index'), show_without_nav_from=True),
    )



@app.route('/unexecuted-task-report/export')
def unexecuted_task_report_export():
    _ensure_unexecuted_task_table()
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    from_date = parse_date(request.args.get('from_date')) or pk_date()
    to_date = parse_date(request.args.get('to_date')) or pk_date()
    if from_date > to_date:
        from_date, to_date = to_date, from_date
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    category = (request.args.get('category') or '').strip()
    shift = (request.args.get('shift') or '').strip().lower()
    check_type = (request.args.get('check_type') or '').strip().lower()
    if check_type not in ('', 'above', 'below'):
        check_type = ''
    running_km_limit_raw = (request.args.get('running_km_limit') or '').strip()
    running_km_limit = None
    if running_km_limit_raw:
        try:
            running_km_limit = float(running_km_limit_raw)
            if running_km_limit < 0:
                running_km_limit = None
        except Exception:
            running_km_limit = None
    table_search = (request.args.get('table_search') or '').strip()

    rows = _unexecuted_task_rows(
        from_date, to_date, district_id, project_id, vehicle_id, category, shift,
        check_type=check_type, running_km_limit=running_km_limit,
        allowed_projects=allowed_projects, allowed_districts=allowed_districts, allowed_vehicles=allowed_vehicles,
        is_master_or_admin=is_master_or_admin,
    )
    rows = _filter_unexecuted_rows_by_search(rows, table_search)

    headers = ['Sr', 'District', 'Project', 'Vehicle', 'Task ID', 'Task Assign DateTime', 'Task Close DateTime', 'Total Time', 'Category', 'Running KMs (Activity)', 'Shift', 'Driver Name', 'Fine']
    data_rows = []
    for i, row in enumerate(rows, 1):
        data_rows.append([
            i,
            row['district'].name if row.get('district') else (row['emg'].district_name or '-'),
            row['project'].name if row.get('project') else '-',
            row['vehicle'].vehicle_no if row.get('vehicle') else (row['emg'].amb_reg_no or '-'),
            row['emg'].task_id_ext or '-',
            row['assign_dt'].strftime('%d-%m-%Y %I:%M %p') if row.get('assign_dt') else '-',
            row['close_dt'].strftime('%d-%m-%Y %I:%M %p') if row.get('close_dt') else '-',
            row['total_time'] or '-',
            row['emg'].category or '-',
            row['activity_km'],
            row['shift'] or '-',
            row['saved'].driver.name if row.get('saved') and row['saved'].driver else '-',
            row['saved'].fine if row.get('saved') and row['saved'].fine else '-',
        ])
    return generate_excel_template(headers, data_rows, required_columns=[], filename=f'unexecuted_task_report_{pk_now().strftime("%Y%m%d_%H%M%S")}.xlsx')



@app.route('/unexecuted-task-report/preview')
def unexecuted_task_report_preview():
    _ensure_unexecuted_task_table()
    from auth_utils import get_user_context
    user_id = session.get('user_id')
    user_context = get_user_context(user_id) if user_id else {}
    allowed_projects = user_context.get('allowed_projects', set())
    allowed_districts = user_context.get('allowed_districts', set())
    allowed_vehicles = user_context.get('allowed_vehicles', set())
    is_master_or_admin = user_context.get('is_master_or_admin', False)
    from_date = parse_date(request.args.get('from_date')) or pk_date()
    to_date = parse_date(request.args.get('to_date')) or pk_date()
    if from_date > to_date:
        from_date, to_date = to_date, from_date
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    vehicle_id = request.args.get('vehicle_id', type=int) or 0
    category = (request.args.get('category') or '').strip()
    shift = (request.args.get('shift') or '').strip().lower()
    check_type = (request.args.get('check_type') or '').strip().lower()
    if check_type not in ('', 'above', 'below'):
        check_type = ''
    running_km_limit_raw = (request.args.get('running_km_limit') or '').strip()
    running_km_limit = None
    if running_km_limit_raw:
        try:
            running_km_limit = float(running_km_limit_raw)
            if running_km_limit < 0:
                running_km_limit = None
        except Exception:
            running_km_limit = None
    table_search = (request.args.get('table_search') or '').strip()

    rows = _unexecuted_task_rows(
        from_date, to_date, district_id, project_id, vehicle_id, category, shift,
        check_type=check_type, running_km_limit=running_km_limit,
        allowed_projects=allowed_projects, allowed_districts=allowed_districts, allowed_vehicles=allowed_vehicles,
        is_master_or_admin=is_master_or_admin,
    )
    rows = _filter_unexecuted_rows_by_search(rows, table_search)
    return render_template(
        'unexecuted_task_report_print.html',
        rows=rows,
        total=len(rows),
        from_date=from_date,
        to_date=to_date,
        category=category,
        shift=shift,
        check_type=check_type,
        running_km_limit_raw=running_km_limit_raw,
        now=datetime.now,
    )



@app.route('/vehicle-move-without-task/new', methods=['GET', 'POST'])
def without_task_new():
    districts = District.query.order_by(District.name).all()
    view_date = pk_date()
    district_id = request.args.get('district_id', 0, type=int)
    project_id = request.args.get('project_id', 0, type=int)
    date_str = request.args.get('date', '')
    if date_str:
        view_date = parse_date(date_str) or view_date
    projects = []
    if district_id:
        projects = Project.query.join(project_district).filter(project_district.c.district_id == district_id).order_by(Project.name).all()
    else:
        projects = Project.query.order_by(Project.name).all()

    if request.method == 'POST' and request.form.get('save_batch'):
        move_date = parse_date(request.form.get('task_date')) or pk_date()
        did = int(request.form.get('district_id') or 0) or None
        pid = int(request.form.get('project_id') or 0) or None
        saved = 0
        idx = 0
        while True:
            veh_id_raw = request.form.get(f'row_{idx}_vehicle_id')
            if veh_id_raw is None:
                break
            veh_id = int(veh_id_raw) if veh_id_raw else None
            _veh = db.session.get(Vehicle, veh_id) if veh_id else None
            row_did = did or (_veh.district_id if _veh else None)
            row_pid = pid or (_veh.project_id if _veh else None)
            try:
                km_in = float(request.form.get(f'row_{idx}_km_in') or 0)
            except (ValueError, TypeError):
                km_in = 0
            try:
                km_out = float(request.form.get(f'row_{idx}_km_out') or 0)
            except (ValueError, TypeError):
                km_out = 0
            d_km = km_out - km_in if km_out >= km_in else 0
            try:
                logbook_task = int(request.form.get(f'row_{idx}_logbook_task') or 0)
            except (ValueError, TypeError):
                logbook_task = 0
            try:
                t_km = float(request.form.get(f'row_{idx}_t_km') or 0)
            except (ValueError, TypeError):
                t_km = 0
            remarks = (request.form.get(f'row_{idx}_remarks') or '').strip() or None
            try:
                fine_amt = float(request.form.get(f'row_{idx}_fine') or 0)
            except (ValueError, TypeError):
                fine_amt = 0
            try:
                driver_id = int(request.form.get(f'row_{idx}_driver_id') or 0) or None
            except (ValueError, TypeError):
                driver_id = None
            edit_mode = str(request.form.get(f'row_{idx}_edit_mode') or '1') == '1'
            existing = VehicleMoveWithoutTask.query.filter_by(vehicle_id=veh_id, move_date=move_date).first()
            if existing:
                # Locked row: keep old record exactly as-is unless user explicitly clicks Edit.
                if not edit_mode:
                    idx += 1
                    continue
                # Extra safety: if driver is left blank on re-save, preserve the previously saved driver.
                effective_driver_id = driver_id if driver_id is not None else existing.driver_id
                existing.district_id = row_did
                existing.project_id = row_pid
                existing.km_in = km_in
                existing.km_out = km_out
                existing.d_km = d_km
                existing.logbook_task = logbook_task
                existing.emg_task = 0
                existing.t_km = t_km
                existing.remarks = remarks
                existing.fine = str(fine_amt) if fine_amt > 0 else 'No'
                existing.fine_amount = fine_amt
                existing.driver_id = effective_driver_id
                rec = existing
            else:
                rec = VehicleMoveWithoutTask(
                    move_date=move_date, district_id=row_did, project_id=row_pid, vehicle_id=veh_id,
                    km_in=km_in, km_out=km_out, d_km=d_km,
                    logbook_task=logbook_task, emg_task=0, t_km=t_km,
                    remarks=remarks, fine=str(fine_amt) if fine_amt > 0 else 'No',
                    fine_amount=fine_amt, driver_id=driver_id,
                )
                db.session.add(rec)
            db.session.flush()
            PenaltyRecord.query.filter_by(source_type='without_task', source_id=rec.id).delete()
            if fine_amt > 0 and driver_id:
                pen = PenaltyRecord(
                    district_id=row_did, project_id=row_pid, vehicle_id=veh_id,
                    driver_id=driver_id, record_date=move_date,
                    fine=str(fine_amt), remarks='Vehicle Move Without Task Fine',
                    source_type='without_task', source_id=rec.id,
                )
                db.session.add(pen)
            saved += 1
            idx += 1
        db.session.commit()
        flash(f'{saved} Vehicle Move without Task entries saved.', 'success')
        return redirect(url_for('without_task_list'))

    rows = []
    load_attempted = bool(date_str or district_id or project_id)
    if load_attempted:
        saved_recs = VehicleMoveWithoutTask.query.filter(
            VehicleMoveWithoutTask.move_date == view_date
        )
        if district_id:
            saved_recs = saved_recs.filter(VehicleMoveWithoutTask.district_id == district_id)
        if project_id:
            saved_recs = saved_recs.filter(VehicleMoveWithoutTask.project_id == project_id)
        saved_map = {r.vehicle_id: r for r in saved_recs.all()}

        tq = VehicleDailyTask.query.filter(VehicleDailyTask.task_date == view_date)
        needs_vehicle_join = bool(district_id or project_id)
        if needs_vehicle_join:
            tq = tq.join(Vehicle, Vehicle.id == VehicleDailyTask.vehicle_id)
        if district_id:
            tq = tq.filter(
                or_(
                    VehicleDailyTask.district_id == district_id,
                    and_(VehicleDailyTask.district_id.is_(None), Vehicle.district_id == district_id),
                )
            )
        if project_id:
            tq = tq.filter(
                or_(
                    VehicleDailyTask.project_id == project_id,
                    and_(VehicleDailyTask.project_id.is_(None), Vehicle.project_id == project_id),
                )
            )
        tasks = tq.all()
        seen_vids = set()
        for t in tasks:
            v = t.vehicle
            if not v:
                continue
            if v.id in seen_vids:
                continue
            seen_vids.add(v.id)
            prev = VehicleDailyTask.query.filter(
                VehicleDailyTask.vehicle_id == t.vehicle_id,
                VehicleDailyTask.task_date < view_date
            ).order_by(VehicleDailyTask.task_date.desc()).first()
            if prev and prev.close_reading is not None:
                start_reading = float(prev.close_reading)
            elif t.start_reading is not None:
                start_reading = float(t.start_reading)
            else:
                start_reading = 0
            close_reading = float(t.close_reading) if t.close_reading else 0
            kms_driven = close_reading - start_reading
            if kms_driven < 0:
                kms_driven = 0
            emg_count = EmergencyTaskRecord.query.filter(
                EmergencyTaskRecord.task_date == view_date,
                EmergencyTaskRecord.amb_reg_no == v.vehicle_no,
                EmergencyTaskRecord.category.in_(['Green', 'Yellow']),
            ).count()
            if kms_driven > 0 and emg_count == 0:
                _mil_rec = VehicleMileageRecord.query.filter_by(task_date=view_date, reg_no=v.vehicle_no).first()
                tracker_km = _mil_rec.effective_km() if _mil_rec else 0
                assigned_drivers = Driver.query.filter_by(vehicle_id=v.id, status='Active').order_by(Driver.name).all()
                saved = saved_map.get(v.id)
                # Keep historical integrity: include previously saved driver even if now left/unassigned.
                if saved and saved.driver_id:
                    _saved_drv = db.session.get(Driver, saved.driver_id)
                    if _saved_drv and all(d.id != _saved_drv.id for d in assigned_drivers):
                        assigned_drivers.append(_saved_drv)
                rows.append({
                    'vehicle': v,
                    'start_reading': start_reading,
                    'close_reading': close_reading,
                    'kms_driven': round(kms_driven, 2),
                    'logbook_task': t.tasks_count or 0,
                    'tracker_km': round(tracker_km, 2),
                    'drivers': assigned_drivers,
                    'saved': saved,
                })

        for vid, sr in saved_map.items():
            if vid not in seen_vids:
                v = sr.vehicle
                if not v:
                    continue
                assigned_drivers = Driver.query.filter_by(vehicle_id=v.id, status='Active').order_by(Driver.name).all()
                if sr.driver_id:
                    _saved_drv = db.session.get(Driver, sr.driver_id)
                    if _saved_drv and all(d.id != _saved_drv.id for d in assigned_drivers):
                        assigned_drivers.append(_saved_drv)
                rows.append({
                    'vehicle': v,
                    'start_reading': float(sr.km_in or 0),
                    'close_reading': float(sr.km_out or 0),
                    'kms_driven': float(sr.d_km or 0),
                    'logbook_task': sr.logbook_task or 0,
                    'tracker_km': float(sr.t_km or 0),
                    'drivers': assigned_drivers,
                    'saved': sr,
                })
    return render_template('without_task_form.html', rows=rows, view_date=view_date,
                           district_id=district_id, project_id=project_id,
                           districts=districts, projects=projects, load_attempted=load_attempted,
                           title='Add Vehicle Move without Task',
                           **_nav_back_ctx(url_for('without_task_list'), show_without_nav_from=True))



@app.route('/vehicle-move-without-task/<int:pk>/edit', methods=['GET', 'POST'])
def without_task_edit(pk):
    rec = VehicleMoveWithoutTask.query.get_or_404(pk)
    form = VehicleMoveWithoutTaskForm(obj=rec)
    form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in District.query.order_by(District.name).all()]
    form.vehicle_id.choices = [(0, '-- Select Vehicle --')] + [(v.id, v.vehicle_no) for v in Vehicle.query.order_by(*vehicle_order_by()).all()]
    if rec.district_id:
        projects = Project.query.join(project_district).filter(project_district.c.district_id == rec.district_id).order_by(Project.name).all()
        form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in projects]
    else:
        form.project_id.choices = [(0, '-- Select Project --')]
    if request.method == 'GET':
        form.move_date.data = rec.move_date
        form.district_id.data = rec.district_id or 0
        form.project_id.data = rec.project_id or 0
        form.vehicle_id.data = rec.vehicle_id or 0
        form.km_in.data = rec.km_in
        form.km_out.data = rec.km_out
        form.d_km.data = rec.d_km
        form.logbook_task.data = rec.logbook_task or 0
        form.emg_task.data = rec.emg_task or 0
        form.t_km.data = rec.t_km
        form.remarks.data = rec.remarks or ''
        form.fine.data = rec.fine or ''
    if request.method == 'POST' and form.validate_on_submit():
        move_date = form.move_date.data
        district_id = form.district_id.data or None
        if district_id == 0:
            district_id = None
        project_id = form.project_id.data or None
        if project_id == 0:
            project_id = None
        vehicle_id = form.vehicle_id.data or None
        if vehicle_id == 0:
            vehicle_id = None
        rec.move_date = move_date
        rec.district_id = district_id
        rec.project_id = project_id
        rec.vehicle_id = vehicle_id
        rec.km_in = form.km_in.data
        rec.km_out = form.km_out.data
        rec.d_km = form.d_km.data
        rec.logbook_task = form.logbook_task.data or 0
        rec.emg_task = form.emg_task.data or 0
        rec.t_km = form.t_km.data
        rec.remarks = form.remarks.data.strip() or None
        rec.fine = form.fine.data.strip() or None
        db.session.commit()
        flash('Vehicle Move without Task updated.', 'success')
        return redirect(url_for('without_task_list'))
    return render_template('without_task_edit.html', form=form, title='Edit Vehicle Move without Task', rec=rec,
                          **_nav_back_ctx(url_for('without_task_list'), show_without_nav_from=True))



@app.route('/penalty-record', methods=['GET', 'POST'])
def penalty_record_list():
    form = PenaltyRecordFilterForm()
    form.district_id.choices = [(0, '-- All Districts --')] + [(d.id, d.name) for d in District.query.order_by(District.name).all()]
    today = pk_date()
    from_date = today
    to_date = today
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    if request.method == 'POST':
        from_date = parse_date(request.form.get('from_date')) or today
        to_date = parse_date(request.form.get('to_date')) or today
        district_id = request.form.get('district_id', type=int) or 0
        project_id = request.form.get('project_id', type=int) or 0
        if from_date and to_date and from_date > to_date:
            from_date, to_date = to_date, from_date
        return redirect(url_for('penalty_record_list', from_date=from_date.strftime('%d-%m-%Y') if from_date else '', to_date=to_date.strftime('%d-%m-%Y') if to_date else '', district_id=district_id, project_id=project_id))
    from_str = request.args.get('from_date', '')
    to_str = request.args.get('to_date', '')
    if from_str:
        from_date = parse_date(from_str) or from_date
    if to_str:
        to_date = parse_date(to_str) or to_date
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date
    form.from_date.data = from_date
    form.to_date.data = to_date
    form.district_id.data = district_id
    if district_id:
        projects = Project.query.join(project_district).filter(project_district.c.district_id == district_id).order_by(Project.name).all()
        form.project_id.choices = [(0, '-- All Projects --')] + [(p.id, p.name) for p in projects]
    else:
        form.project_id.choices = [(0, '-- All Projects --')]
    form.project_id.data = project_id
    query = PenaltyRecord.query.filter(
        PenaltyRecord.record_date >= from_date,
        PenaltyRecord.record_date <= to_date
    )
    if district_id:
        query = query.filter(PenaltyRecord.district_id == district_id)
    if project_id:
        query = query.filter(PenaltyRecord.project_id == project_id)
    rows = query.order_by(PenaltyRecord.record_date.desc(), PenaltyRecord.id.desc()).all()
    search = (request.args.get('search') or '').strip()
    if search:
        tokens = [t.lower() for t in search.split() if t]
        def _match(r):
            blob = ' '.join([
                str(r.record_date),
                r.district.name if r.district else '',
                r.project.name if r.project else '',
                r.vehicle.vehicle_no if r.vehicle else '',
                r.driver.name if r.driver else '',
                r.source_type or '', r.remarks or '',
            ]).lower()
            return all(tok in blob for tok in tokens)
        rows = [r for r in rows if _match(r)]
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = SimplePagination(rows, page, per_page)
    rows = pagination.items
    return render_template('penalty_record_list.html', form=form, rows=rows, from_date=from_date, to_date=to_date, district_id=district_id, project_id=project_id, pagination=pagination, per_page=per_page, search=search, **_workforce_nav_back())



@app.route('/penalty-record/export')
def penalty_record_export():
    today = pk_date()
    from_date = parse_date(request.args.get('from_date')) or today
    to_date = parse_date(request.args.get('to_date')) or today
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date
    rows = _penalty_record_query(from_date, to_date, district_id, project_id).all()
    headers = ['S.No', 'District', 'Project', 'Vehicle', 'Driver Name', 'Date', 'Fine', 'Remarks']
    data_rows = []
    for i, row in enumerate(rows, 1):
        data_rows.append([
            i,
            row.district.name if row.district else '-',
            row.project.name if row.project else '-',
            row.vehicle.vehicle_no if row.vehicle else '-',
            row.driver.name if row.driver else '-',
            row.record_date.strftime('%Y-%m-%d') if row.record_date else '-',
            row.fine or '-',
            (row.remarks or '')[:200]
        ])
    filename = f'penalty_records_{from_date.strftime("%Y-%m-%d")}_to_{to_date.strftime("%Y-%m-%d")}.xlsx'
    return generate_excel_template(headers, data_rows, required_columns=[], filename=filename)



@app.route('/penalty-record/print')
def penalty_record_print():
    today = pk_date()
    from_date = parse_date(request.args.get('from_date')) or today
    to_date = parse_date(request.args.get('to_date')) or today
    district_id = request.args.get('district_id', type=int) or 0
    project_id = request.args.get('project_id', type=int) or 0
    if from_date and to_date and from_date > to_date:
        from_date, to_date = to_date, from_date
    rows = _penalty_record_query(from_date, to_date, district_id, project_id).all()
    return render_template('penalty_record_print.html', rows=rows, from_date=from_date, to_date=to_date, district_id=district_id, project_id=project_id)



@app.route('/penalty-record/new', methods=['GET', 'POST'])
def penalty_record_new():
    form = PenaltyRecordForm()
    form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in District.query.order_by(District.name).all()]
    form.project_id.choices = [(0, '-- Select Project --')]
    form.vehicle_id.choices = [(0, '-- Select Vehicle --')] + [(v.id, v.vehicle_no) for v in Vehicle.query.order_by(*vehicle_order_by()).all()]
    form.driver_id.choices = [(0, '-- Select Driver --')] + [(d.id, d.name) for d in Driver.query.order_by(Driver.name).all()]
    if request.method == 'POST' and form.validate_on_submit():
        record_date = form.record_date.data
        district_id = form.district_id.data or None
        if district_id == 0:
            district_id = None
        project_id = form.project_id.data or None
        if project_id == 0:
            project_id = None
        vehicle_id = form.vehicle_id.data or None
        if vehicle_id == 0:
            vehicle_id = None
        driver_id = form.driver_id.data or None
        if driver_id == 0:
            driver_id = None
        rec = PenaltyRecord(
            record_date=record_date, district_id=district_id, project_id=project_id, vehicle_id=vehicle_id, driver_id=driver_id,
            fine=form.fine.data.strip() or None, remarks=form.remarks.data.strip() or None
        )
        db.session.add(rec)
        db.session.commit()
        flash('Penalty record saved.', 'success')
        return redirect(url_for('penalty_record_list'))
    return render_template('penalty_record_form.html', form=form, title='Add Penalty Record', **_workforce_nav_back())



@app.route('/penalty-record/<int:pk>/edit', methods=['GET', 'POST'])
def penalty_record_edit(pk):
    rec = PenaltyRecord.query.get_or_404(pk)
    form = PenaltyRecordForm(obj=rec)
    form.district_id.choices = [(0, '-- Select District --')] + [(d.id, d.name) for d in District.query.order_by(District.name).all()]
    form.vehicle_id.choices = [(0, '-- Select Vehicle --')] + [(v.id, v.vehicle_no) for v in Vehicle.query.order_by(*vehicle_order_by()).all()]
    form.driver_id.choices = [(0, '-- Select Driver --')] + [(d.id, d.name) for d in Driver.query.order_by(Driver.name).all()]
    if rec.district_id:
        projects = Project.query.join(project_district).filter(project_district.c.district_id == rec.district_id).order_by(Project.name).all()
        form.project_id.choices = [(0, '-- Select Project --')] + [(p.id, p.name) for p in projects]
    else:
        form.project_id.choices = [(0, '-- Select Project --')]
    if request.method == 'GET':
        form.record_date.data = rec.record_date
        form.district_id.data = rec.district_id or 0
        form.project_id.data = rec.project_id or 0
        form.vehicle_id.data = rec.vehicle_id or 0
        form.driver_id.data = rec.driver_id or 0
        form.fine.data = rec.fine or ''
        form.remarks.data = rec.remarks or ''
    if request.method == 'POST' and form.validate_on_submit():
        record_date = form.record_date.data
        district_id = form.district_id.data or None
        if district_id == 0:
            district_id = None
        project_id = form.project_id.data or None
        if project_id == 0:
            project_id = None
        vehicle_id = form.vehicle_id.data or None
        if vehicle_id == 0:
            vehicle_id = None
        driver_id = form.driver_id.data or None
        if driver_id == 0:
            driver_id = None
        rec.record_date = record_date
        rec.district_id = district_id
        rec.project_id = project_id
        rec.vehicle_id = vehicle_id
        rec.driver_id = driver_id
        rec.fine = form.fine.data.strip() or None
        rec.remarks = form.remarks.data.strip() or None
        db.session.commit()
        flash('Penalty record updated.', 'success')
        return redirect(url_for('penalty_record_list'))
    return render_template('penalty_record_form.html', form=form, title='Edit Penalty Record', rec=rec, **_workforce_nav_back())


