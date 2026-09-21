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
            syncEngineButtons(v.device_status);
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

    // ── Engine Kill / Release (inline confirm — no modal lock) ────
    const CSRF = (window.FleetConfig && window.FleetConfig.csrfToken) ||
        (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
    const killBtn = document.getElementById('psKillBtn');
    const releaseBtn = document.getElementById('psReleaseBtn');
    const confirmBox = document.getElementById('psCmdConfirmBox');
    const confirmInput = document.getElementById('psCmdConfirm');
    const confirmText = document.getElementById('psCmdConfirmText');
    const sendBtn = document.getElementById('psCmdSendBtn');
    const cancelBtn = document.getElementById('psCmdCancelBtn');
    let pendingAction = null;

    function immState(statusText) {
        const s = String(statusText || '').toLowerCase().replace(/\s+/g, '');
        if (s.indexOf('immobilizeron') >= 0 || s.indexOf('imoblizeron') >= 0) return true;
        if (s.indexOf('immobilizeroff') >= 0 || s.indexOf('imoblizeroff') >= 0) return false;
        return null;
    }

    function syncEngineButtons(statusText) {
        const on = immState(statusText);
        if (killBtn) {
            killBtn.disabled = on === true;
            killBtn.title = on === true ? 'Immobilizer pehle se ON hai' : '';
        }
        if (releaseBtn) {
            releaseBtn.disabled = on !== true;
            releaseBtn.title = on === true ? '' : 'Immobilizer Off — Release ki zaroorat nahi';
        }
    }

    const initialStatus = (document.getElementById('psDevStatus') || {}).textContent || '';
    syncEngineButtons(initialStatus);

    function hideConfirm() {
        pendingAction = null;
        if (confirmBox) confirmBox.hidden = true;
        if (confirmInput) confirmInput.value = '';
        if (sendBtn) sendBtn.disabled = true;
    }

    function askCommand(action) {
        const on = immState((document.getElementById('psDevStatus') || {}).textContent || '');
        if (action === 'engine_off' && on === true) {
            const msg = document.getElementById('psCmdMsg');
            if (msg) msg.innerHTML = '<div class="alert alert-warning py-1 mb-0 small">Immobilizer pehle se ON hai.</div>';
            return;
        }
        if (action === 'engine_on' && on !== true) {
            const msg = document.getElementById('psCmdMsg');
            if (msg) msg.innerHTML = '<div class="alert alert-warning py-1 mb-0 small">Immobilizer Off hai — Release ki zaroorat nahi.</div>';
            return;
        }
        pendingAction = action;
        const isKill = action === 'engine_off';
        if (confirmText) {
            confirmText.innerHTML = isKill
                ? '<span class="text-danger"><b>Engine Kill</b> — immobilizer ON. Chalte hue vehicle par mat bhejein.</span>'
                : '<span class="text-success"><b>Engine Release</b> — immobilizer khulega, vehicle normal chalegi.</span>';
        }
        if (sendBtn) {
            sendBtn.className = 'btn btn-sm ' + (isKill ? 'btn-danger' : 'btn-success');
            sendBtn.textContent = isKill ? 'Send Kill' : 'Send Release';
            sendBtn.disabled = true;
        }
        if (confirmInput) confirmInput.value = '';
        if (confirmBox) confirmBox.hidden = false;
        if (confirmInput) confirmInput.focus();
    }

    if (killBtn) killBtn.addEventListener('click', () => askCommand('engine_off'));
    if (releaseBtn) releaseBtn.addEventListener('click', () => askCommand('engine_on'));
    if (cancelBtn) cancelBtn.addEventListener('click', hideConfirm);

    if (confirmInput) confirmInput.addEventListener('input', () => {
        if (sendBtn) sendBtn.disabled =
            confirmInput.value.trim().toUpperCase() !== regno.toUpperCase();
    });

    if (sendBtn) sendBtn.addEventListener('click', () => {
        if (!pendingAction || !confirmInput) return;
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
          .finally(() => { hideConfirm(); });
    });
})();
