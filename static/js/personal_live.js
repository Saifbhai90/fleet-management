/* Personal (Crescent) live map — pro edition:
   direction-rotated arrow markers, satellite layer, follow mode, fullscreen,
   rich telemetry popups, searchable vehicle list, freshness + countdown. */
(function () {
    'use strict';
    const CSRF = (window.FleetConfig && window.FleetConfig.csrfToken) ||
        (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

    const STATUS_COLORS = { Moving: '#10b981', Idle: '#f59e0b', Parked: '#64748b', Offline: '#ef4444' };
    const STATUS_TEXT = { Moving: 'Moving', Idle: 'Idle', Parked: 'Parked', Offline: 'Offline' };

    // ── Map styles (Google default) ──────────────────────────────
    const gOpts = { subdomains: ['mt0', 'mt1', 'mt2', 'mt3'], maxZoom: 20, attribution: '&copy; Google' };
    const googleStreet = L.tileLayer('https://{s}.google.com/vt/lyrs=m&x={x}&y={y}&z={z}', gOpts);
    const googleSatellite = L.tileLayer('https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', gOpts);
    const googleHybrid = L.tileLayer('https://{s}.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', gOpts);
    const googleTerrain = L.tileLayer('https://{s}.google.com/vt/lyrs=p&x={x}&y={y}&z={z}', gOpts);
    const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, attribution: '&copy; OpenStreetMap',
    });
    const esriSat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        maxZoom: 19, attribution: 'Tiles &copy; Esri',
    });

    const map = L.map('psMap', { layers: [googleStreet], zoomControl: true }).setView([30.3753, 69.3451], 6);
    L.control.layers({
        'Google Street': googleStreet, 'Google Satellite': googleSatellite,
        'Google Hybrid': googleHybrid, 'Google Terrain': googleTerrain,
        'OpenStreetMap': osm, 'Esri Satellite': esriSat,
    }, null, { position: 'topright' }).addTo(map);
    L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);

    // ── Crescent-style vehicle icons (from the app itself) ───────
    function vehicleIcon(v, selected) {
        const stMap = { Moving: 'moving', Idle: 'idle', Parked: 'parked', Offline: 'offline' };
        const st = stMap[v.status] || 'offline';
        const tMap = { car: 'car', truck: 'truck', bus: 'bus', bike: 'bike', motorcycle: 'bike', atm: 'atm', van: 'car', pickup: 'truck' };
        const vt = tMap[(v.vehicle_type || 'car').toLowerCase()] || 'car';
        const url = `/static/img/personal/vehicles/${st}_${vt}.png`;
        const w = selected ? 26 : 20;
        const h = Math.round(w * 223 / 114); // keep the vendor aspect ratio
        const dir = parseFloat(v.dir);
        const rot = (v.status === 'Moving' && isFinite(dir)) ? dir : 0;
        const ring = selected
            ? `<div style="position:absolute;inset:-5px;border:2px solid ${STATUS_COLORS[v.status] || '#10b981'};border-radius:50%;animation:psPulse 1.6s infinite;"></div>`
            : '';
        const speedTag = v.status === 'Moving'
            ? `<div style="position:absolute;top:100%;left:50%;transform:translateX(-50%);background:${STATUS_COLORS[v.status]};color:#fff;font-size:8px;font-weight:700;padding:0 4px;border-radius:999px;white-space:nowrap;line-height:14px;">${v.speed ?? 0} km/h</div>`
            : '';
        return L.divIcon({
            className: '',
            html: `<div style="position:relative;width:${w}px;height:${h}px;">
                     <img src="${url}" style="width:100%;height:100%;object-fit:contain;transform:rotate(${rot}deg);transform-origin:50% 50%;transition:transform .8s linear;filter:drop-shadow(0 1px 2px rgba(0,0,0,.4));">
                     ${ring}${speedTag}
                   </div>`,
            iconSize: [w, h], iconAnchor: [w / 2, h / 2],
        });
    }

    // Glide across the 5 second gap so the vehicle moves smoothly instead of
    // jumping from the last point to the new one.
    function moveMarker(marker, latlng, durationMs) {
        const target = L.latLng(latlng[0], latlng[1]);
        const from = marker.getLatLng();
        marker._target = target;
        marker._ll = latlng;
        if (!from) {
            marker.setLatLng(target);
            return;
        }
        const same = Math.abs(from.lat - target.lat) < 1e-7 && Math.abs(from.lng - target.lng) < 1e-7;
        if (same) return;
        let meters = 0;
        try { meters = map.distance(from, target); } catch (e) { meters = 0; }
        if (map._psInteracting || meters > 2500) {
            if (marker._raf) cancelAnimationFrame(marker._raf);
            marker._raf = null;
            marker.setLatLng(target);
            return;
        }
        const startLat = from.lat;
        const startLng = from.lng;
        const start = performance.now();
        const dur = Math.max(1000, Math.min(durationMs || 5000, 5000));
        if (marker._raf) cancelAnimationFrame(marker._raf);
        function step(now) {
            if (marker._target !== target) return;
            const t = Math.min(1, (now - start) / dur);
            marker.setLatLng([
                startLat + (target.lat - startLat) * t,
                startLng + (target.lng - startLng) * t,
            ]);
            if (t < 1) marker._raf = requestAnimationFrame(step);
            else marker._raf = null;
        }
        marker._raf = requestAnimationFrame(step);
    }

    map.on('zoomstart movestart', () => { map._psInteracting = true; });
    map.on('zoomend moveend', () => { map._psInteracting = false; });

    // legend
    const legend = L.control({ position: 'bottomright' });
    legend.onAdd = function () {
        const d = L.DomUtil.create('div', 'ps-legend');
        d.innerHTML = Object.entries(STATUS_COLORS).map(([k, c]) =>
            `<div><span class="sw" style="background:${c}"></span>${k}</div>`).join('');
        return d;
    };
    legend.addTo(map);

    const markers = {};
    const listEl = document.getElementById('psList');
    const followChk = document.getElementById('psFollow');
    const freshText = document.getElementById('tbFreshText');
    let selectedId = null;
    let fitDone = false;
    let pollSeconds = parseInt((document.getElementById('psPollInfo') || { dataset: {} }).dataset.poll || '5', 10);
    if (!isFinite(pollSeconds) || pollSeconds < 5) pollSeconds = 5;
    let secondsLeft = pollSeconds;
    let lastVehicles = [];

    // fullscreen toggle
    const fsBtn = document.getElementById('psFsBtn');
    if (fsBtn) fsBtn.addEventListener('click', () => {
        const mapEl = document.getElementById('psMap');
        mapEl.classList.toggle('ps-map-fs');
        setTimeout(() => map.invalidateSize(), 60);
    });

    function popupHtml(v) {
        const batI = v.int_bat != null ? `${Math.round(v.int_bat)}%` : '—';
        const batE = v.ext_bat != null ? `${v.ext_bat.toFixed(1)}V` : '—';
        const gsm = v.gsm != null ? `${v.gsm}/5` : '—';
        const gps = v.gps_sat != null ? `${v.gps_sat}` : '—';
        const fence = v.fence ? `<span style="background:${v.fence === 'In' ? '#dcfce7' : '#fee2e2'};color:${v.fence === 'In' ? '#166534' : '#991b1b'};padding:1px 7px;border-radius:999px;font-size:.68rem;font-weight:700;">Fence: ${v.fence}</span>` : '';
        const gmaps = v.lat != null ? `<a href="https://www.google.com/maps?q=${v.lat},${v.lon}" target="_blank" style="font-size:.72rem;color:#2563eb;">Google Maps ↗</a>` : '';
        return `<div style="min-width:260px;font-size:.82rem;">
            <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
                <a href="/personal/vehicle/${v.id}" style="font-weight:800;font-size:.95rem;">${v.regno}</a>
                <span style="margin-left:auto;background:${STATUS_COLORS[v.status]}22;color:${STATUS_COLORS[v.status]};padding:2px 8px;border-radius:999px;font-weight:700;font-size:.68rem;">${v.status.toUpperCase()}</span>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:2px 10px;color:#334155;">
                <div>🚀 <b>${v.speed ?? 0}</b> km/h</div>
                <div>🔑 ${v.ignition || '—'}</div>
                <div>🛣️ ${v.mileage ?? 0} km</div>
                <div>📡 ${gsm} · 🛰️ ${gps}</div>
                <div>🔋 ${batE} · ${batI}</div>
                <div>🚚 ${v.vehicle_type || '—'} ${fence}</div>
            </div>
            <div style="margin-top:4px;color:#475569;">📍 ${v.address || '—'} ${gmaps}</div>
            <div style="color:#94a3b8;font-size:.72rem;margin-top:2px;">${v.device_time ? new Date(v.device_time).toLocaleString() : ''}</div>
            <div style="margin-top:6px;text-align:right;">
                <a href="/personal/vehicle/${v.id}" style="font-weight:700;color:#059669;font-size:.76rem;">Details</a> ·
                <a href="/personal/history?vehicle=${v.device_id}" style="font-weight:700;color:#059669;font-size:.76rem;">History →</a>
            </div>
        </div>`;
    }

    function render(vehicles) {
        lastVehicles = vehicles;
        const seen = new Set();
        vehicles.forEach(v => {
            seen.add(v.id);
            if (v.lat == null || v.lon == null) return;
            const latlng = [v.lat, v.lon];
            const isSel = selectedId === v.id;
            const sig = `${v.status}|${v.dir}|${isSel}|${v.vehicle_type}`;
            if (!markers[v.id]) {
                markers[v.id] = L.marker(latlng, { icon: vehicleIcon(v, isSel) }).addTo(map)
                    .bindPopup(popupHtml(v), { maxWidth: 340 });
                markers[v.id]._ll = latlng;
                markers[v.id]._sig = sig;
            } else {
                moveMarker(markers[v.id], latlng, 5000);
                if (markers[v.id]._sig !== sig) {             // visuals only when something changed
                    markers[v.id].setIcon(vehicleIcon(v, isSel));
                    markers[v.id]._sig = sig;
                }
                markers[v.id].setPopupContent(popupHtml(v));
            }
            if (isSel && followChk && followChk.checked) map.panTo(latlng);
        });
        Object.keys(markers).forEach(id => {
            if (!seen.has(Number(id))) { map.removeLayer(markers[id]); delete markers[id]; }
        });
        if (!fitDone && vehicles.length) {
            const pts = vehicles.filter(v => v.lat != null).map(v => [v.lat, v.lon]);
            if (pts.length === 1) map.setView(pts[0], 15);
            else if (pts.length > 1) map.fitBounds(L.latLngBounds(pts).pad(0.25));
            fitDone = true;
        }

        const q = (document.getElementById('psSearch') || {}).value || '';
        const ffilter = window._psStatusFilter || '';
        const rows = vehicles.filter(v =>
            (!q || `${v.regno} ${v.group || ''} ${v.address || ''}`.toLowerCase().includes(q.toLowerCase())) &&
            (!ffilter || v.status === ffilter));
        listEl.innerHTML = rows.map(v => `
            <div class="ps-live-item ${selectedId === v.id ? 'selected' : ''}" data-id="${v.id}">
                <span class="ps-dot ${(v.status || 'offline').toLowerCase()}"></span>
                <span class="flex-fill"><b>${v.regno}</b><br><small class="text-muted">${(v.address || '—').slice(0, 42)}</small></span>
                <span class="spd">${v.speed ?? 0}<small class="text-muted"> km/h</small></span>
            </div>`).join('') || '<div class="text-muted small p-2">Koi vehicle match nahi hui — Refresh dabayein.</div>';
        listEl.querySelectorAll('.ps-live-item').forEach(el => {
            el.addEventListener('click', () => {
                selectedId = Number(el.dataset.id);
                const v = vehicles.find(x => x.id === selectedId);
                if (v && v.lat != null) {
                    map.setView([v.lat, v.lon], Math.max(map.getZoom(), 16));
                    if (markers[selectedId]) markers[selectedId].openPopup();
                }
                render(lastVehicles);
            });
        });
    }

    function updateCountdown() {
        if (freshText) {
            freshText.textContent = `next update in ${secondsLeft}s`;
            secondsLeft -= 1;
            if (secondsLeft < 0) secondsLeft = pollSeconds;
        }
    }

    function pollNow() {
        fetch('/api/personal/positions').then(r => r.json()).then(res => {
            if (res.ok) {
                const next = parseInt(res.poll_seconds, 10);
                if (isFinite(next) && next >= 5) pollSeconds = next;
                secondsLeft = pollSeconds;
                render(res.vehicles);
            }
        }).catch(() => {});
    }

    // ── SSE live stream (server pushes; falls back to polling) ────
    let sse = null;
    function startStream() {
        if (typeof EventSource === 'undefined') return; // keep polling
        try {
            sse = new EventSource('/api/personal/stream');
            sse.onmessage = ev => {
                try {
                    const res = JSON.parse(ev.data);
                    if (!res.ok) return;
                    secondsLeft = pollSeconds;
                    render(res.vehicles);
                } catch (e) { /* ignore bad frame */ }
            };
            sse.onerror = () => {
                // stream dropped — EventSource retries itself; polling stays as backup
            };
        } catch (e) { /* no SSE support — polling continues */ }
    }
    startStream();

    function fullRefresh() {
        const btn = document.getElementById('psRefreshBtn');
        if (btn) { btn.disabled = true; }
        fetch('/api/personal/refresh', { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
            .then(r => r.json())
            .then(res => { if (!res.ok && res.error) alert(res.error); pollNow(); })
            .catch(e => alert('Network error: ' + e))
            .finally(() => { if (btn) btn.disabled = false; });
    }

    const refreshBtn = document.getElementById('psRefreshBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', fullRefresh);
    const searchBox = document.getElementById('psSearch');
    if (searchBox) searchBox.addEventListener('input', () => render(lastVehicles));
    document.querySelectorAll('.ps-stat[data-filter]').forEach(el => {
        el.addEventListener('click', () => {
            document.querySelectorAll('.ps-stat').forEach(x => x.classList.remove('selected'));
            el.classList.add('selected');
            window._psStatusFilter = el.dataset.filter === 'all' ? '' : el.dataset.filter;
            render(lastVehicles);
        });
    });

    setInterval(updateCountdown, 1000);
    setInterval(pollNow, pollSeconds * 1000);
    pollNow();

    // Mobile / WebView: keep map tiles aligned after rotate / bottom-sheet layout
    function relayoutMap() {
        try { map.invalidateSize({ animate: false }); } catch (e) { /* ignore */ }
    }
    window.addEventListener('resize', relayoutMap);
    window.addEventListener('orientationchange', function () {
        setTimeout(relayoutMap, 280);
    });
    setTimeout(relayoutMap, 120);
    setTimeout(relayoutMap, 600);
})();
