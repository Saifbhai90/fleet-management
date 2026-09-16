/* ═══════════════════════════════════════════════════════════════════
   Fleet Manager — Fuel Expense cascade wiring (shared)
   Used by BOTH templates/fuel_expense_form.html (desktop) and
   templates/_fuel_expense_form_logic.html (mobile form). Those two pages
   used to carry verbatim copies of this wiring; the only real behavioral
   difference (how the fuel-type UI resets when the cascade clears) is
   injected via hooks. All helpers are provided by the page through `deps`
   — this file must stay page-agnostic.
   Call this inside the page's DOMContentLoaded handler, after the page's
   select/helper variables exist. Cache note: bump the ?v= on the <script
   src> include in both templates whenever this file changes.
   ═══════════════════════════════════════════════════════════════════ */
(function() {
    'use strict';

    window.wireFuelCascade = function(deps) {
        deps = deps || {};
        var districtSelect = deps.districtSelect;
        var projectSelect = deps.projectSelect;
        var vehicleSelect = deps.vehicleSelect;
        var smoothFill = deps.smoothFill || function() {};
        var smoothLoading = deps.smoothLoading || function() {};
        var projectsFromColdCache = deps.projectsFromColdCache || function() { return null; };
        var vehiclesFromColdCache = deps.vehiclesFromColdCache || function() { return null; };
        var rememberVehicleMeta = deps.rememberVehicleMeta || function() {};
        var fetchVehicleLastEntry = deps.fetchVehicleLastEntry || function() {};
        var onCascadeReset = deps.onCascadeReset || function() {};

        if (!window._cascadeCache) window._cascadeCache = {};

        /* ── Suppress dropdown auto-open while a cascade refills ── */
        if (districtSelect && projectSelect && typeof window.fleetBeginCascade === 'function') {
            districtSelect.addEventListener('change', function() {
                window.fleetBeginCascade(projectSelect);
                if (vehicleSelect) window.fleetBeginCascade(vehicleSelect);
            }, true);
        }
        if (projectSelect && vehicleSelect && typeof window.fleetBeginCascade === 'function') {
            projectSelect.addEventListener('change', function() {
                window.fleetBeginCascade(vehicleSelect);
            }, true);
        }

        /* ── District change → refill Project (+ clear Vehicle) ── */
        if (districtSelect && projectSelect) {
            districtSelect.addEventListener('change', function() {
                var did = this.value;
                smoothLoading(projectSelect);
                smoothLoading(vehicleSelect);
                onCascadeReset();
                fetchVehicleLastEntry();
                if (did && did !== '0') {
                    var _cKey = 'proj_d' + did;
                    var coldP = projectsFromColdCache(did);
                    if (coldP !== null) {
                        smoothFill(projectSelect, coldP, function(p) { return { value: String(p.id), text: p.name }; });
                    } else if (window._cascadeCache[_cKey]) {
                        smoothFill(projectSelect, window._cascadeCache[_cKey], function(p) { return { value: String(p.id), text: p.name }; });
                    } else {
                        smoothLoading(projectSelect);
                        fetch('/get_projects_by_district/' + did)
                            .then(function(r) { return r.json(); })
                            .then(function(arr) {
                                window._cascadeCache[_cKey] = arr;
                                smoothFill(projectSelect, arr, function(p) { return { value: String(p.id), text: p.name }; });
                            })
                            .catch(function() { smoothFill(projectSelect, [], function(p) { return p; }); });
                    }
                    smoothFill(vehicleSelect, [], function(v) { return { value: String(v.id), text: v.vehicle_no }; });
                } else {
                    smoothFill(projectSelect, [], function(p) { return { value: String(p.id), text: p.name }; });
                    smoothFill(vehicleSelect, [], function(v) { return { value: String(v.id), text: v.vehicle_no }; });
                }
            });
        }

        /* ── Project change → refill Vehicle (cold cache → cache → fetch) ── */
        if (projectSelect && vehicleSelect) {
            projectSelect.addEventListener('change', function() {
                var pid = projectSelect.value;
                var did = districtSelect ? districtSelect.value : '';
                smoothLoading(vehicleSelect);
                onCascadeReset();
                fetchVehicleLastEntry();
                if (pid && pid !== '0') {
                    var _vKey = 'veh_p' + pid + '_d' + (did || '0');
                    var coldV = vehiclesFromColdCache(pid, did);
                    if (coldV !== null) {
                        coldV.forEach(rememberVehicleMeta);
                        smoothFill(vehicleSelect, coldV, function(v) { return { value: String(v.id), text: v.vehicle_no }; });
                    } else if (window._cascadeCache[_vKey]) {
                        window._cascadeCache[_vKey].forEach(rememberVehicleMeta);
                        smoothFill(vehicleSelect, window._cascadeCache[_vKey], function(v) { return { value: String(v.id), text: v.vehicle_no }; });
                    } else {
                        smoothLoading(vehicleSelect);
                        var url = '/get_vehicles_by_project_district?project_id=' + pid;
                        if (did && did !== '0') url += '&district_id=' + did;
                        fetch(url).then(function(r) { return r.json(); }).then(function(arr) {
                            window._cascadeCache[_vKey] = arr;
                            arr.forEach(rememberVehicleMeta);
                            smoothFill(vehicleSelect, arr, function(v) { return { value: String(v.id), text: v.vehicle_no }; });
                        }).catch(function() { smoothFill(vehicleSelect, [], function(v) { return v; }); });
                    }
                } else {
                    smoothFill(vehicleSelect, [], function(v) { return { value: String(v.id), text: v.vehicle_no }; });
                }
            });
        }

        /* ── Fuel-type select: price refresh on change (optional) ── */
        if (deps.fuelTypeSelect && typeof deps.onFuelTypeChange === 'function') {
            deps.fuelTypeSelect.addEventListener('change', deps.onFuelTypeChange);
        }

        /* ── Pump: guarded TS re-init + price refresh on change (optional) ── */
        if (deps.fuelPumpSelect) {
            if (!deps.fuelPumpSelect.tomselect && typeof window.initSearchableDropdowns === 'function') {
                window.initSearchableDropdowns(deps.fuelPumpSelect.parentNode);
            }
            if (typeof deps.onPumpChange === 'function') {
                deps.fuelPumpSelect.addEventListener('change', deps.onPumpChange);
            }
        }
    };
})();
