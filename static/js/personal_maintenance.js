/* Personal — Fuel chart + Maintenance rules (user-set intervals) */
(function () {
    'use strict';
    const CSRF = (window.FleetConfig && window.FleetConfig.csrfToken) ||
        (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

    const vehicleSel = document.getElementById('psMaintVehicle');
    const metaEl = document.getElementById('psMaintVehicleMeta');
    const listEl = document.getElementById('psMaintList');
    const msgEl = document.getElementById('psMaintMsg');
    const form = document.getElementById('psMaintForm');
    const hoursSel = document.getElementById('psFuelHours');
    const fleetList = document.getElementById('psFleetDueList');
    let fuelChart = null;
    let currentKm = 0;

    function esc(s) {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : s;
        return d.innerHTML;
    }

    function selectedVid() {
        return vehicleSel && vehicleSel.value ? Number(vehicleSel.value) : null;
    }

    function syncMeta() {
        if (!vehicleSel || !metaEl) return;
        const opt = vehicleSel.selectedOptions[0];
        if (!opt || !opt.value) {
            metaEl.textContent = '';
            currentKm = 0;
            return;
        }
        currentKm = Number(opt.dataset.mileage || 0);
        metaEl.textContent = `${opt.dataset.regno || ''} · current mileage ${currentKm} km`;
    }

    function loadFleet() {
        if (!fleetList) return;
        fetch('/api/personal/maintenance')
            .then(r => r.json()).then(res => {
                if (!res.ok) {
                    fleetList.textContent = res.error || 'Load failed';
                    return;
                }
                const dueEl = document.getElementById('psKpiDue');
                const soonEl = document.getElementById('psKpiSoon');
                const totEl = document.getElementById('psKpiTotal');
                if (dueEl) dueEl.textContent = res.due || 0;
                if (soonEl) soonEl.textContent = res.due_soon || 0;
                if (totEl) totEl.textContent = (res.rules || []).length;
                const hot = (res.rules || []).filter(r => r.due || r.due_soon);
                if (!hot.length) {
                    fleetList.innerHTML = '<span class="text-success">Koi due / due-soon rule nahi.</span>';
                    return;
                }
                fleetList.innerHTML = hot.map(r => {
                    const cls = r.due ? 'text-danger fw-bold' : 'text-warning fw-bold';
                    const label = r.due ? 'OVERDUE' : `${r.remaining_km} km left`;
                    return `<div class="ps-row justify-content-between py-1 border-bottom">
                        <a href="?vid=${r.vid}" class="text-decoration-none">${esc(r.regno)} — ${esc(r.label)}</a>
                        <span class="${cls}">${label}</span>
                    </div>`;
                }).join('');
            }).catch(() => { fleetList.textContent = 'Network error'; });
    }

    function loadMaint() {
        const vid = selectedVid();
        if (!listEl) return;
        if (!vid) {
            listEl.innerHTML = '<div class="text-muted small">Vehicle select karein.</div>';
            return;
        }
        listEl.innerHTML = '<div class="text-muted small">Loading&hellip;</div>';
        fetch(`/api/personal/vehicle/${vid}/maintenance`)
            .then(r => r.json()).then(res => {
                if (!res.ok) {
                    listEl.innerHTML = `<div class="text-danger small">${esc(res.error || 'Failed')}</div>`;
                    return;
                }
                currentKm = Number(res.current_km || 0);
                syncMeta();
                if (!res.rules.length) {
                    listEl.innerHTML = '<div class="text-muted small">Koi rule nahi — neeche form se add karein (interval khud likhein).</div>';
                    return;
                }
                listEl.innerHTML = res.rules.map(r => {
                    const cls = r.due ? 'text-danger fw-bold' : (r.due_soon ? 'text-warning fw-bold' : 'text-success');
                    const status = r.due ? 'OVERDUE' : `${r.remaining_km} km left`;
                    return `<div class="ps-maint-row d-flex flex-wrap align-items-center justify-content-between gap-2 py-2 border-bottom">
                        <div>
                            <b>${esc(r.label)}</b>
                            <div class="small text-muted">every ${esc(r.interval_km)} km · last @ ${esc(r.last_service_km)} km · now ${esc(r.current_km)} km</div>
                        </div>
                        <div class="d-flex align-items-center gap-1">
                            <span class="${cls} small">${status}</span>
                            <button type="button" class="btn btn-sm btn-outline-success py-0 px-2" data-done="${r.id}" title="Mark done at current mileage">Done</button>
                            <button type="button" class="btn btn-sm btn-outline-danger py-0 px-2" data-del="${r.id}" title="Delete">×</button>
                        </div>
                    </div>`;
                }).join('');
                listEl.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', () => {
                    if (!confirm('Rule delete karein?')) return;
                    fetch(`/api/personal/vehicle/${vid}/maintenance`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
                        body: JSON.stringify({ action: 'delete', id: Number(b.dataset.del) }),
                    }).then(() => { loadMaint(); loadFleet(); });
                }));
                listEl.querySelectorAll('[data-done]').forEach(b => b.addEventListener('click', () => {
                    if (!confirm(`Mark done @ current ${currentKm} km?`)) return;
                    fetch(`/api/personal/vehicle/${vid}/maintenance`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
                        body: JSON.stringify({ action: 'mark_done', id: Number(b.dataset.done) }),
                    }).then(r => r.json()).then(res2 => {
                        if (msgEl) {
                            msgEl.innerHTML = res2.ok
                                ? `<span class="text-success">${esc(res2.message || 'Done')}</span>`
                                : `<span class="text-danger">${esc(res2.error || 'Failed')}</span>`;
                        }
                        loadMaint();
                        loadFleet();
                    });
                }));
            }).catch(() => { listEl.innerHTML = '<div class="text-danger small">Network error</div>'; });
    }

    function loadFuel() {
        const el = document.getElementById('psFuelChart');
        const info = document.getElementById('psFuelInfo');
        const vid = selectedVid();
        if (!el || typeof Chart === 'undefined') return;
        if (!vid) {
            if (fuelChart) { fuelChart.destroy(); fuelChart = null; }
            if (info) info.textContent = '';
            return;
        }
        const hours = (hoursSel && hoursSel.value) || 24;
        fetch(`/api/personal/vehicle/${vid}/fuel?hours=${hours}`)
            .then(r => r.json()).then(res => {
                if (!res.ok) return;
                const s = res.series || [];
                if (info) {
                    info.textContent = s.length
                        ? `(${s.length} samples · ${hours}h)`
                        : '(snapshots collect ho rahe hain — Live Map refresh ke baad data aayega)';
                }
                const labels = s.map(x => (x.ts || '').slice(11, 16));
                const data = {
                    labels,
                    datasets: [
                        { label: 'Fuel delta', data: s.map(x => x.fuel_delta), borderColor: '#f59e0b', yAxisID: 'y1', pointRadius: 0, borderWidth: 2, tension: .3 },
                        { label: 'Speed', data: s.map(x => x.speed), borderColor: '#10b981', pointRadius: 0, borderWidth: 1.5, tension: .3 },
                    ],
                };
                if (fuelChart) {
                    fuelChart.data = data;
                    fuelChart.update('none');
                    return;
                }
                fuelChart = new Chart(el, {
                    type: 'line',
                    data,
                    options: {
                        plugins: { legend: { labels: { boxWidth: 10, font: { size: 10 } } } },
                        scales: {
                            y: { beginAtZero: true, title: { display: true, text: 'km/h' } },
                            y1: { position: 'right', beginAtZero: true, grid: { drawOnChartArea: false }, title: { display: true, text: 'fuel' } },
                        },
                        animation: false,
                    },
                });
            }).catch(() => {});
    }

    function onVehicleChange() {
        syncMeta();
        const vid = selectedVid();
        if (vid) {
            const url = new URL(window.location.href);
            url.searchParams.set('vid', String(vid));
            window.history.replaceState({}, '', url);
        }
        loadMaint();
        loadFuel();
    }

    if (vehicleSel) vehicleSel.addEventListener('change', onVehicleChange);
    if (hoursSel) hoursSel.addEventListener('change', loadFuel);

    const useMileageBtn = document.getElementById('psMaintUseMileage');
    if (useMileageBtn) useMileageBtn.addEventListener('click', () => {
        const last = document.getElementById('psMaintLast');
        if (last) last.value = String(Math.round(currentKm) || 0);
    });

    if (form) form.addEventListener('submit', ev => {
        ev.preventDefault();
        const vid = selectedVid();
        if (!vid) {
            if (msgEl) msgEl.innerHTML = '<span class="text-danger">Pehle vehicle select karein.</span>';
            return;
        }
        const intervalVal = document.getElementById('psMaintInterval').value;
        if (intervalVal === '' || intervalVal == null) {
            if (msgEl) msgEl.innerHTML = '<span class="text-danger">Interval km aap set karein — empty nahi chhor sakte.</span>';
            return;
        }
        fetch(`/api/personal/vehicle/${vid}/maintenance`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
            body: JSON.stringify({
                label: document.getElementById('psMaintLabel').value.trim(),
                interval_km: intervalVal,
                last_service_km: document.getElementById('psMaintLast').value || 0,
            }),
        }).then(r => r.json()).then(res => {
            if (msgEl) {
                msgEl.innerHTML = res.ok
                    ? '<span class="text-success">Rule saved.</span>'
                    : `<span class="text-danger">${esc(res.error || 'Save failed')}</span>`;
            }
            if (res.ok) {
                form.reset();
                loadMaint();
                loadFleet();
            }
        }).catch(e => {
            if (msgEl) msgEl.innerHTML = '<span class="text-danger">Network error: ' + esc(String(e)) + '</span>';
        });
    });

    syncMeta();
    loadFleet();
    if (selectedVid()) {
        loadMaint();
        loadFuel();
    }
})();
