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
    const alarmCards = document.getElementById('psAlarmCards');
    const mode = (document.currentScript && document.currentScript.dataset.mode) || 'table';
    let lastRows = [];
    const isMobile = () => window.matchMedia('(max-width: 767.98px)').matches;

    function today() { return new Date().toISOString().slice(0, 10); }
    const fromEl = document.getElementById('psFrom');
    const toEl = document.getElementById('psTo');
    if (fromEl) fromEl.value = today();
    if (toEl) toEl.value = today();

    function showAlert(msg) {
        if (!alertBox) return;
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

    function pick(row, keys) {
        for (const k of keys) {
            if (row[k] != null && String(row[k]).trim() !== '') return row[k];
        }
        return '—';
    }

    function renderTripCards(rows) {
        if (!cardsWrap) return;
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

    function renderAlarmCards(rows) {
        if (!alarmCards) return;
        if (!rows.length) {
            alarmCards.innerHTML = '<div class="text-muted py-3 text-center">Koi alarm nahi mila.</div>';
            return;
        }
        alarmCards.innerHTML = rows.map(r => {
            const flat = flattenRow(r);
            const title = pick(flat, ['Alarm', 'Type', 'Event', 'alarm', 'type', 'Name']);
            const when = pick(flat, ['Time', 'Date', 'Created', 'time', 'date', 'DeviceTime']);
            const loc = pick(flat, ['Address', 'Location', 'address', 'location']);
            const speed = pick(flat, ['Speed', 'speed', 'Speed (km/h)']);
            return `<div class="ps-alarm-card">
                <div class="ps-alarm-head">
                    <span class="ps-alarm-title"><i class="bi bi-bell-fill text-danger"></i> ${title}</span>
                    <span class="ps-alarm-when">${when}</span>
                </div>
                <div class="ps-alarm-loc"><i class="bi bi-geo-alt"></i> ${loc}</div>
                <div class="ps-alarm-meta">Speed: <strong>${speed}</strong></div>
            </div>`;
        }).join('');
    }

    function renderRows(rows) {
        lastRows = rows;
        const tableCard = headRow ? headRow.closest('.ps-table-card') : null;
        if (mode === 'trips') {
            renderTripCards(rows);
            if (tableCard) tableCard.style.display = 'none';
        }
        if (!rows.length) {
            if (mode !== 'trips') {
                if (headRow) headRow.innerHTML = '<th class="text-muted">Koi record nahi mila.</th>';
                if (body) body.innerHTML = '';
                if (alarmCards) alarmCards.innerHTML = '';
            }
            if (countEl) countEl.textContent = '';
            if (csvBtn) csvBtn.disabled = true;
            return;
        }
        if (mode === 'trips') {
            if (countEl) {
                countEl.textContent = `${rows.length} trips · total ${rows.reduce((a, t) => a + (Number(t['Distance (km)']) || 0), 0).toFixed(1)} km`;
            }
            if (csvBtn) csvBtn.disabled = false;
            return;
        }
        // Alarms / notifications: card list on phone, table on desktop
        if (isMobile() && alarmCards) {
            renderAlarmCards(rows);
            if (tableCard) tableCard.style.display = 'none';
            if (countEl) countEl.textContent = `${rows.length} records`;
            if (csvBtn) csvBtn.disabled = false;
            return;
        }
        if (alarmCards) alarmCards.innerHTML = '';
        if (tableCard) tableCard.style.display = '';
        const flat = rows.map(flattenRow);
        const cols = Array.from(flat.reduce((set, r) => { Object.keys(r).forEach(k => set.add(k)); return set; }, new Set()));
        cols.sort();
        if (headRow) headRow.innerHTML = cols.map(c => `<th>${c}</th>`).join('');
        if (body) body.innerHTML = flat.map(r => `<tr>${cols.map(c => `<td>${(r[c] ?? '') == '' ? '—' : r[c]}</td>`).join('')}</tr>`).join('');
        if (countEl) countEl.textContent = `${rows.length} records`;
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

    if (!form) return;

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
        if (runBtn) runBtn.disabled = true;
        fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
            body: JSON.stringify(payload),
        }).then(r => r.json()).then(res => {
            if (!res.ok) { showAlert((res.error || 'Report failed') + (res.hint ? ' — ' + res.hint : '')); return; }
            renderRows(res.rows || []);
        }).catch(e => showAlert('Network error: ' + e))
          .finally(() => { if (runBtn) runBtn.disabled = false; });
    });

    if (csvBtn) csvBtn.addEventListener('click', function () {
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
