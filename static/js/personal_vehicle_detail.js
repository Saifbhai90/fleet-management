/* Personal (Crescent) vehicle detail: mini map + live telemetry refresh */
(function () {
    'use strict';
    const mapEl = document.getElementById('psMap');
    if (!mapEl) return;

    const lat = parseFloat(mapEl.dataset.lat || '');
    const lon = parseFloat(mapEl.dataset.lon || '');
    const regno = mapEl.dataset.regno || 'Vehicle';
    const hasFix = isFinite(lat) && isFinite(lon);

    const map = L.map('psMap', { scrollWheelZoom: false })
        .setView(hasFix ? [lat, lon] : [30.3753, 69.3451], hasFix ? 15 : 5);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, attribution: '&copy; OpenStreetMap',
    }).addTo(map);

    let marker = null;
    if (hasFix) {
        marker = L.marker([lat, lon]).addTo(map).bindPopup(regno + ' — last known position').openPopup();
    }

    // live refresh of this vehicle's position/telemetry
    function refresh() {
        fetch('/api/personal/positions').then(r => r.json()).then(res => {
            if (!res.ok) return;
            const v = (res.vehicles || []).find(x => x.regno === regno || x.id === Number(mapEl.dataset.vid));
            if (!v) return;
            if (v.lat != null && v.lon != null) {
                if (!marker) marker = L.marker([v.lat, v.lon]).addTo(map);
                else marker.setLatLng([v.lat, v.lon]);
                if (!hasFix) map.setView([v.lat, v.lon], 15);
            }
            const set = (id, val) => { const el = document.getElementById(id); if (el && val != null) el.textContent = val; };
            set('psExtBat', v.ext_bat != null ? v.ext_bat.toFixed(1) + ' V' : null);
            set('psIntBat', v.int_bat != null ? Math.round(v.int_bat) + '%' : null);
            set('psGsm', v.gsm != null ? v.gsm + '/5' : null);
            set('psGps', v.gps_sat);
            set('psFence', v.fence);
            set('psDevStatus', v.device_status);
            const info = document.getElementById('psLiveInfo');
            if (info) info.textContent = '· auto-refreshing every ' + (res.poll_seconds || 30) + 's';
        }).catch(() => {});
    }
    setInterval(refresh, 30000);
    refresh();

    function relayoutMap() {
        try { map.invalidateSize({ animate: false }); } catch (e) { /* ignore */ }
    }
    window.addEventListener('resize', relayoutMap);
    window.addEventListener('orientationchange', function () {
        setTimeout(relayoutMap, 280);
    });
    setTimeout(relayoutMap, 120);

    // ── Engine Kill / Release (typed confirmation + CSRF) ──────────
    const CSRF = (window.FleetConfig && window.FleetConfig.csrfToken) ||
        (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
    const killBtn = document.getElementById('psKillBtn');
    const releaseBtn = document.getElementById('psReleaseBtn');
    let pendingAction = null;

    function askCommand(action) {
        if (typeof bootstrap === 'undefined' || !bootstrap.Modal) return;
        pendingAction = action;
        const isKill = action === 'engine_off';
        document.getElementById('psCmdModalTitle').textContent = isKill ? 'Engine Kill — Confirm' : 'Engine Release — Confirm';
        document.getElementById('psCmdModalHead').className = 'modal-header py-2 ' + (isKill ? 'bg-danger' : 'bg-success');
        document.getElementById('psCmdModalHead').querySelector('.modal-title').style.color = '#fff';
        document.getElementById('psCmdModalText').innerHTML = isKill
            ? 'Engine <b>OFF</b> command bheja jayega (immobilizer ON). Vehicle ka engine agla start hone par band ho jayega ya foran band ho sakta hai. <b>Chalte hue vehicle par mat bhejein.</b>'
            : 'Engine <b>ON</b> (Release) command bheja jayega — immobilizer khul jayega aur vehicle normal chalegi.';
        document.getElementById('psCmdRegno').textContent = regno;
        document.getElementById('psCmdConfirm').value = '';
        document.getElementById('psCmdSendBtn').disabled = true;
        bootstrap.Modal.getOrCreateInstance(document.getElementById('psCmdModal')).show();
    }

    if (killBtn) killBtn.addEventListener('click', () => askCommand('engine_off'));
    if (releaseBtn) releaseBtn.addEventListener('click', () => askCommand('engine_on'));

    const confirmInput = document.getElementById('psCmdConfirm');
    if (confirmInput) confirmInput.addEventListener('input', () => {
        document.getElementById('psCmdSendBtn').disabled =
            confirmInput.value.trim().toUpperCase() !== regno.toUpperCase();
    });

    const sendBtn = document.getElementById('psCmdSendBtn');
    if (sendBtn) sendBtn.addEventListener('click', () => {
        if (!pendingAction) return;
        sendBtn.disabled = true;
        const msg = document.getElementById('psCmdMsg');
        fetch(`/api/personal/vehicle/${mapEl.dataset.vid}/command`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
            body: JSON.stringify({ action: pendingAction, confirm: confirmInput.value.trim() }),
        }).then(r => r.json()).then(res => {
            if (res.dry_run) {
                msg.innerHTML = `<div class="alert alert-warning py-1 mb-0 small"><b>DRY-RUN:</b> ${res.message}<br>
                    <code style="font-size:.65rem;">${res.request_url}</code></div>`;
            } else if (res.ok) {
                msg.innerHTML = `<div class="alert alert-success py-1 mb-0 small">Command sent — vendor response: ${res.message || 'OK'}</div>`;
            } else {
                msg.innerHTML = `<div class="alert alert-danger py-1 mb-0 small">${res.error || 'Command failed'}<br>
                    ${res.vendor_body ? '<code style="font-size:.65rem;">' + res.vendor_body + '</code>' : ''}</div>`;
            }
        }).catch(e => { msg.innerHTML = '<div class="alert alert-danger py-1 mb-0 small">Network error: ' + e + '</div>'; })
          .finally(() => {
            sendBtn.disabled = false;
            const m = bootstrap.Modal.getInstance(document.getElementById('psCmdModal'));
            if (m) m.hide();
          });
    });

    // ── Fuel chart (last 24h from live snapshots) ─────────────────
    function loadFuel() {
        const el = document.getElementById('psFuelChart');
        if (!el || typeof Chart === 'undefined') return;
        fetch(`/api/personal/vehicle/${mapEl.dataset.vid}/fuel?hours=24`)
            .then(r => r.json()).then(res => {
                if (!res.ok) return;
                const s = res.series || [];
                const labels = s.map(x => x.ts.slice(11, 16));
                const info = document.getElementById('psFuelInfo');
                if (info) info.textContent = s.length ? `(${s.length} samples)` : '(snapshots collect ho rahe hain — thori dair mein data aayega)';
                new Chart(el, {
                    type: 'line',
                    data: {
                        labels,
                        datasets: [
                            { label: 'Fuel delta', data: s.map(x => x.fuel_delta), borderColor: '#f59e0b', yAxisID: 'y1', pointRadius: 0, borderWidth: 2, tension: .3 },
                            { label: 'Speed', data: s.map(x => x.speed), borderColor: '#10b981', pointRadius: 0, borderWidth: 1.5, tension: .3 },
                        ],
                    },
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
    loadFuel();

    // ── Maintenance rules ─────────────────────────────────────────
    const maintList = document.getElementById('psMaintList');

    function loadMaint() {
        if (!maintList) return;
        fetch(`/api/personal/vehicle/${mapEl.dataset.vid}/maintenance`)
            .then(r => r.json()).then(res => {
                if (!res.ok) return;
                if (!res.rules.length) { maintList.innerHTML = '<div class="text-muted small">Koi rule nahi — neeche se add karein.</div>'; return; }
                maintList.innerHTML = res.rules.map(r => {
                    const cls = r.due ? 'text-danger fw-bold' : (r.due_soon ? 'text-warning fw-bold' : 'text-success');
                    return `<div class="ps-row justify-content-between">
                        <span><b>${esc(r.label)}</b> — every ${r.interval_km} km (last @ ${r.last_service_km} km)</span>
                        <span class="${cls}">${r.due ? 'OVERDUE' : r.remaining_km + ' km left'}
                            <button class="btn btn-sm btn-outline-danger py-0 px-1 ms-1" data-del="${r.id}">×</button></span>
                    </div>`;
                }).join('');
                maintList.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', () => {
                    fetch(`/api/personal/vehicle/${mapEl.dataset.vid}/maintenance`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
                        body: JSON.stringify({ action: 'delete', id: Number(b.dataset.del) }),
                    }).then(() => loadMaint());
                }));
            }).catch(() => {});
    }

    function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }

    const maintForm = document.getElementById('psMaintForm');
    if (maintForm) maintForm.addEventListener('submit', ev => {
        ev.preventDefault();
        fetch(`/api/personal/vehicle/${mapEl.dataset.vid}/maintenance`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
            body: JSON.stringify({
                label: document.getElementById('psMaintLabel').value.trim(),
                interval_km: document.getElementById('psMaintInterval').value,
                last_service_km: document.getElementById('psMaintLast').value || 0,
            }),
        }).then(r => r.json()).then(res => {
            const msg = document.getElementById('psMaintMsg');
            msg.innerHTML = res.ok ? '<span class="text-success">Rule saved.</span>'
                                   : '<span class="text-danger">' + (res.error || 'Save failed') + '</span>';
            if (res.ok) { maintForm.reset(); loadMaint(); }
        }).catch(e => { alert('Network error: ' + e); });
    });

    loadMaint();
})();
