/* Personal (Crescent) reports: trips (card view) / alarms / notifications */
(function () {
    'use strict';
    const CSRF = (window.FleetConfig && window.FleetConfig.csrfToken) ||
        (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

    const form = document.getElementById('psReportForm');
    const alertBox = document.getElementById('psAlert');
    const headRow = document.getElementById('psHeadRow');
    const body = document.getElementById('psBody');
    const countEl = document.getElementById('psCount');
    const csvBtn = document.getElementById('psCsvBtn');
    const refreshBtn = document.getElementById('psRefreshBtn');
    const cardsWrap = document.getElementById('psTripCards');
    const mode = (document.currentScript && document.currentScript.dataset.mode) || 'table';
    let lastRows = [];

    function today() { return new Date().toISOString().slice(0, 10); }
    const fromEl = document.getElementById('psFrom');
    const toEl = document.getElementById('psTo');
    if (fromEl) fromEl.value = today();
    if (toEl) toEl.value = today();

    function showAlert(msg) {
        if (!msg) { alertBox.style.display = 'none'; return; }
        alertBox.textContent = msg;
        alertBox.style.display = '';
    }

    function flattenRow(obj) {
        const out = {};
        Object.keys(obj).forEach(k => {
            let v = obj[k];
            if (v && typeof v === 'object') v = JSON.stringify(v);
            out[k] = v;
        });
        return out;
    }

    function renderTripCards(rows) {
        cardsWrap.innerHTML = rows.map(t => `
            <div class="ps-trip-card">
                <div class="ps-trip-time">
                    <i class="bi bi-calendar-event text-success"></i> ${t['Start Time'] || ''}<br>
                    <span class="text-muted small">→ ${t['End Time'] || ''}</span>
                </div>
                <div class="ps-trip-route">
                    <div class="loc"><i class="bi bi-play-circle text-success"></i> ${t['Start Location'] || '—'}</div>
                    <div class="loc"><i class="bi bi-flag-fill text-danger"></i> ${t['End Location'] || '—'}</div>
                </div>
                <div class="ps-trip-kpis">
                    <div class="ps-trip-kpi"><b>${t['Distance (km)'] ?? '—'}</b><span>km</span></div>
                    <div class="ps-trip-kpi"><b>${t['Duration (min)'] ?? '—'}</b><span>min</span></div>
                    <div class="ps-trip-kpi"><b>${t['Max Speed (km/h)'] ?? '—'}</b><span>max km/h</span></div>
                    <div class="ps-trip-kpi"><b>${t['Points'] ?? '—'}</b><span>points</span></div>
                </div>
            </div>`).join('') || '<div class="text-muted py-3 text-center">Is range ke liye koi trip nahi mili.</div>';
    }

    function renderRows(rows) {
        lastRows = rows;
        const tableCard = headRow.closest('.ps-table-card');
        if (mode === 'trips') {
            renderTripCards(rows);
            if (tableCard) tableCard.style.display = 'none';
        }
        if (!rows.length) {
            if (mode !== 'trips') {
                headRow.innerHTML = '<th class="text-muted">Koi record nahi mila.</th>';
                body.innerHTML = '';
            }
            countEl.textContent = '';
            if (csvBtn) csvBtn.disabled = true;
            return;
        }
        if (mode === 'trips') {
            countEl.textContent = `${rows.length} trips · total ${rows.reduce((a, t) => a + (Number(t['Distance (km)']) || 0), 0).toFixed(1)} km`;
            if (csvBtn) csvBtn.disabled = false;
            return;
        }
        const flat = rows.map(flattenRow);
        const cols = Array.from(flat.reduce((set, r) => { Object.keys(r).forEach(k => set.add(k)); return set; }, new Set()));
        cols.sort();
        headRow.innerHTML = cols.map(c => `<th>${c}</th>`).join('');
        body.innerHTML = flat.map(r => `<tr>${cols.map(c => `<td>${(r[c] ?? '') == '' ? '—' : r[c]}</td>`).join('')}</tr>`).join('');
        countEl.textContent = `${rows.length} records`;
        if (csvBtn) csvBtn.disabled = false;
    }

    function fetchNotifications() {
        showAlert('');
        if (refreshBtn) refreshBtn.disabled = true;
        fetch('/api/personal/notifications', { headers: { 'X-CSRFToken': CSRF } })
            .then(r => r.json()).then(res => {
                if (!res.ok) { showAlert(res.error + (res.hint ? ' — ' + res.hint : '')); return; }
                renderRows(res.rows || []);
            }).catch(e => showAlert('Network error: ' + e))
            .finally(() => { if (refreshBtn) refreshBtn.disabled = false; });
    }

    if (mode === 'notifications') {
        if (refreshBtn) refreshBtn.addEventListener('click', fetchNotifications);
        return;
    }

    form.addEventListener('submit', function (ev) {
        ev.preventDefault();
        showAlert('');
        const endpoint = form.dataset.endpoint;
        const vehicleSel = document.getElementById('psVehicle');
        const opt = vehicleSel.selectedOptions[0];
        const payload = {
            device_id: vehicleSel.value || '',
            regno: opt ? (opt.dataset.regno || '') : '',
            date_from: fromEl.value, date_to: toEl.value,
            time_from: '00:00', time_to: '23:59',
        };
        const runBtn = document.getElementById('psRunBtn');
        runBtn.disabled = true;
        fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
            body: JSON.stringify(payload),
        }).then(r => r.json()).then(res => {
            if (!res.ok) { showAlert((res.error || 'Report failed') + (res.hint ? ' — ' + res.hint : '')); return; }
            renderRows(res.rows || []);
        }).catch(e => showAlert('Network error: ' + e))
          .finally(() => { runBtn.disabled = false; });
    });

    csvBtn.addEventListener('click', function () {
        if (!lastRows.length) return;
        const flat = lastRows.map(flattenRow);
        const cols = Array.from(flat.reduce((set, r) => { Object.keys(r).forEach(k => set.add(k)); return set; }, new Set()));
        const esc = v => '"' + String(v ?? '').replace(/"/g, '""') + '"';
        const csv = [cols.map(esc).join(',')].concat(flat.map(r => cols.map(c => esc(r[c])).join(','))).join('\r\n');
        const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'crescent_report_' + new Date().toISOString().slice(0, 10) + '.csv';
        a.click();
        URL.revokeObjectURL(a.href);
    });
})();
