"""Fuel expense settings stored in SystemSetting (tolerance, KM gap rules)."""

import json

from models import SystemSetting

_FUEL_PRICE_TOLERANCE_KEY = 'fuel_price_tolerance_rs'
_FUEL_KM_GAP_RULES_KEY = 'fuel_km_gap_rules'
_DEFAULT_TOLERANCE = 5.0
_DEFAULT_KM_GAP = 500


def get_fuel_price_tolerance_rs():
    raw = (SystemSetting.get(_FUEL_PRICE_TOLERANCE_KEY, '') or '').strip()
    if not raw:
        return _DEFAULT_TOLERANCE
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TOLERANCE
    return max(0.0, val)


def save_fuel_price_tolerance_rs(value):
    try:
        val = float(value)
    except (TypeError, ValueError):
        val = _DEFAULT_TOLERANCE
    val = max(0.0, val)
    SystemSetting.set(_FUEL_PRICE_TOLERANCE_KEY, str(val))
    return val


def get_fuel_km_gap_rules():
    raw = (SystemSetting.get(_FUEL_KM_GAP_RULES_KEY, '') or '').strip()
    if not raw:
        return {'default_max_km': _DEFAULT_KM_GAP, 'rules': []}
    try:
        data = json.loads(raw)
    except Exception:
        return {'default_max_km': _DEFAULT_KM_GAP, 'rules': []}
    if not isinstance(data, dict):
        return {'default_max_km': _DEFAULT_KM_GAP, 'rules': []}
    try:
        default_max = int(float(data.get('default_max_km') or _DEFAULT_KM_GAP))
    except (TypeError, ValueError):
        default_max = _DEFAULT_KM_GAP
    rules = []
    for row in (data.get('rules') or []):
        if not isinstance(row, dict):
            continue
        try:
            max_km = int(float(row.get('max_km')))
        except (TypeError, ValueError):
            continue
        if max_km <= 0:
            continue
        district_id = row.get('district_id')
        project_id = row.get('project_id')
        vehicle_family = (row.get('vehicle_family') or '').strip()
        try:
            district_id = int(district_id) if district_id not in (None, '', 0, '0') else None
        except (TypeError, ValueError):
            district_id = None
        try:
            project_id = int(project_id) if project_id not in (None, '', 0, '0') else None
        except (TypeError, ValueError):
            project_id = None
        if not any([district_id, project_id, vehicle_family]):
            continue
        rules.append({
            'district_id': district_id,
            'project_id': project_id,
            'vehicle_family': vehicle_family,
            'max_km': max_km,
        })
    return {'default_max_km': max(1, default_max), 'rules': rules}


def save_fuel_km_gap_rules(default_max_km, rules):
    try:
        default_val = int(float(default_max_km))
    except (TypeError, ValueError):
        default_val = _DEFAULT_KM_GAP
    default_val = max(1, default_val)
    clean_rules = []
    seen = set()
    for row in (rules or []):
        if not isinstance(row, dict):
            continue
        try:
            max_km = int(float(row.get('max_km')))
        except (TypeError, ValueError):
            continue
        if max_km <= 0:
            continue
        district_id = row.get('district_id')
        project_id = row.get('project_id')
        vehicle_family = (row.get('vehicle_family') or '').strip()
        try:
            district_id = int(district_id) if district_id not in (None, '', 0, '0') else None
        except (TypeError, ValueError):
            district_id = None
        try:
            project_id = int(project_id) if project_id not in (None, '', 0, '0') else None
        except (TypeError, ValueError):
            project_id = None
        if not any([district_id, project_id, vehicle_family]):
            continue
        key = (district_id, project_id, vehicle_family.lower())
        if key in seen:
            continue
        seen.add(key)
        clean_rules.append({
            'district_id': district_id,
            'project_id': project_id,
            'vehicle_family': vehicle_family,
            'max_km': max_km,
        })
    payload = {'default_max_km': default_val, 'rules': clean_rules}
    SystemSetting.set(_FUEL_KM_GAP_RULES_KEY, json.dumps(payload, ensure_ascii=True))
    return payload


def resolve_fuel_km_gap_max(district_id=None, project_id=None, vehicle_family=None):
    cfg = get_fuel_km_gap_rules()
    default_max = int(cfg.get('default_max_km') or _DEFAULT_KM_GAP)
    rules = cfg.get('rules') or []
    fam = (vehicle_family or '').strip().lower()
    try:
        district_id = int(district_id) if district_id not in (None, '', 0, '0') else None
    except (TypeError, ValueError):
        district_id = None
    try:
        project_id = int(project_id) if project_id not in (None, '', 0, '0') else None
    except (TypeError, ValueError):
        project_id = None

    best = None
    best_score = -1
    for rule in rules:
        score = 0
        rid = rule.get('district_id')
        rpid = rule.get('project_id')
        rfam = (rule.get('vehicle_family') or '').strip().lower()
        if rid and rid != district_id:
            continue
        if rid:
            score += 1
        if rpid and rpid != project_id:
            continue
        if rpid:
            score += 4
        if rfam and rfam != fam:
            continue
        if rfam:
            score += 2
        if score > best_score:
            best_score = score
            best = rule
    if best and best.get('max_km'):
        return int(best['max_km'])
    return default_max


def fuel_expense_settings_payload():
    cfg = get_fuel_km_gap_rules()
    return {
        'price_tolerance_rs': get_fuel_price_tolerance_rs(),
        'km_gap_default_max_km': cfg.get('default_max_km', _DEFAULT_KM_GAP),
        'km_gap_rules': cfg.get('rules') or [],
    }
