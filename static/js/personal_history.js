/* Personal (Crescent) History Playback — pro edition:
   speed-colored route, stop markers, animated replay with timeline scrubber,
   prev/next day navigation, synced speed chart, clickable point table. */
(function () {
    'use strict';
    // surface any unexpected JS error on the page itself (silent fails are hard to debug)
    window.addEventListener('error', function (e) {
        const ab = document.getElementById('psHistoryAlert');
        if (ab) { ab.textContent = 'Error: ' + e.message; ab.style.display = ''; }
    });
    const CSRF = (window.FleetConfig && window.FleetConfig.csrfToken) ||
        (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

    const map = L.map('psMap').setView([30.3753, 69.3451], 6);
    const gOpts = { subdomains: ['mt0', 'mt1', 'mt2', 'mt3'], maxZoom: 20, attribution: '&copy; Google' };
    const googleStreet = L.tileLayer('https://{s}.google.com/vt/lyrs=m&x={x}&y={y}&z={z}', gOpts).addTo(map);
    const googleSatellite = L.tileLayer('https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', gOpts);
    const googleHybrid = L.tileLayer('https://{s}.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', gOpts);
    const googleTerrain = L.tileLayer('https://{s}.google.com/vt/lyrs=p&x={x}&y={y}&z={z}', gOpts);
    const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, attribution: '&copy; OpenStreetMap',
    });
    const esriSat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        maxZoom: 19, attribution: 'Tiles &copy; Esri',
    });
    L.control.layers({
        'Google Street': googleStreet, 'Google Satellite': googleSatellite,
        'Google Hybrid': googleHybrid, 'Google Terrain': googleTerrain,
        'OpenStreetMap': osm, 'Esri Satellite': esriSat,
    }, null, { position: 'topright' }).addTo(map);
    L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);

    let routeLayer = null;        // L.featureGroup with colored segments
    let stopLayer = null;         // stop markers
    let startEndLayer = null;     // START / END badges
    let replayMarker = null;
    let trailLayer = null;        // traveled part during replay
    let chart = null;
    let replayTimer = null;
    let replayIdx = 0;
    let replaySpeed = 4;
    let currentPoints = [];
    let currentStops = [];

    // Same Crescent vehicle icons as Live Map (status × type, DirAngle rotate).
    function historyVehicleIcon(p) {
        const STATUS_COLORS = { Moving: '#10b981', Idle: '#f59e0b', Parked: '#64748b', Offline: '#ef4444' };
        const stMap = { Moving: 'moving', Idle: 'idle', Parked: 'parked', Offline: 'offline' };
        const sl = String(p.status || '').toLowerCase();
        let stKey = 'Idle';
        if (sl.includes('mov')) stKey = 'Moving';
        else if (sl.includes('idle')) stKey = 'Idle';
        else if (sl.includes('park') || sl.includes('stop')) stKey = 'Parked';
        else if (sl.includes('off')) stKey = 'Offline';
        else if ((p.speed || 0) > 3) stKey = 'Moving';
        const st = stMap[stKey] || 'idle';
        const vehSel = document.getElementById('psVehicle');
        const opt = vehSel && vehSel.options[vehSel.selectedIndex];
        const tMap = { car: 'car', truck: 'truck', bus: 'bus', bike: 'bike', motorcycle: 'bike', atm: 'atm', van: 'car', pickup: 'truck' };
        const vt = tMap[String((opt && opt.dataset.vtype) || 'car').toLowerCase()] || 'car';
        const url = `/static/img/personal/vehicles/${st}_${vt}.png`;
        const w = 22;
        const h = Math.round(w * 223 / 114);
        const dir = parseFloat(p.dir);
        const rot = (stKey === 'Moving' && isFinite(dir)) ? dir : 0;
        const speedTag = stKey === 'Moving'
            ? `<div style="position:absolute;top:100%;left:50%;transform:translateX(-50%);background:${STATUS_COLORS[stKey]};color:#fff;font-size:8px;font-weight:700;padding:0 4px;border-radius:999px;white-space:nowrap;line-height:14px;">${p.speed ?? 0} km/h</div>`
            : '';
        const ring = `<div style="position:absolute;inset:-4px;border:2px solid ${STATUS_COLORS[stKey] || '#10b981'};border-radius:50%;"></div>`;
        return L.divIcon({
            className: '',
            html: `<div style="position:relative;width:${w}px;height:${h}px;">
                     <img src="${url}" alt="" style="width:100%;height:100%;object-fit:contain;transform:rotate(${rot}deg);transform-origin:50% 50%;filter:drop-shadow(0 1px 2px rgba(0,0,0,.4));">
                     ${ring}${speedTag}
                   </div>`,
            iconSize: [w, h],
            iconAnchor: [w / 2, h / 2],
        });
    }

    const form = document.getElementById('psHistoryForm');
    const alertBox = document.getElementById('psHistoryAlert');
    const statsBox = document.getElementById('psHistoryStats');

    function fmtDate(d) { return d.toISOString().slice(0, 10); }

    function shiftDay(delta) {
        const f = document.getElementById('psFrom'), t = document.getElementById('psTo');
        const d1 = new Date(f.value + 'T00:00:00'), d2 = new Date(t.value + 'T00:00:00');
        d1.setDate(d1.getDate() + delta); d2.setDate(d2.getDate() + delta);
        f.value = fmtDate(d1); t.value = fmtDate(d2);
        form.requestSubmit();
    }
    document.getElementById('psPrevDay').addEventListener('click', () => shiftDay(-1));
    document.getElementById('psNextDay').addEventListener('click', () => shiftDay(1));

    function showAlert(msg) {
        if (!msg) { alertBox.style.display = 'none'; return; }
        alertBox.textContent = msg;
        alertBox.style.display = '';
    }

    // speed → color
    function speedColor(s) {
        if (s < 1) return '#94a3b8';
        if (s < 20) return '#10b981';
        if (s < 40) return '#84cc16';
        if (s < 60) return '#f59e0b';
        if (s < 80) return '#f97316';
        return '#ef4444';
    }

    form.addEventListener('submit', function (ev) {
        ev.preventDefault();
        showAlert('');
        stopTimer();
        const vehicleSel = document.getElementById('psVehicle');
        const device_id = vehicleSel.value;
        if (!device_id) { showAlert('Vehicle select karein.'); return; }
        const body = {
            device_id: device_id,
            date_from: document.getElementById('psFrom').value,
            date_to: document.getElementById('psTo').value,
            time_from: document.getElementById('psTimeFrom').value || '00:00',
            time_to: document.getElementById('psTimeTo').value || '23:59',
        };
        const btn = document.getElementById('psRunBtn');
        btn.disabled = true;
        fetch('/api/personal/history', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
            body: JSON.stringify(body),
        }).then(r => r.json()).then(res => {
            if (!res.ok) { showAlert(res.error + (res.hint ? ' — ' + res.hint : '')); return; }
            renderAll(res.points || [], res.stops || [], res.stats || {});
            drawCompare(res.points || []);
        }).catch(e => showAlert('Network error: ' + e))
          .finally(() => { btn.disabled = false; });
    });


    // ── multi-day compare overlay (blue = compare date) ───────────
    let compareLayer = null;
    function drawCompare(primaryPoints) {
        if (compareLayer) { map.removeLayer(compareLayer); compareLayer = null; }
        const cmp = document.getElementById('psCompare');
        const cmpDate = cmp && cmp.value;
        const vehicleSel = document.getElementById('psVehicle');
        const device_id = vehicleSel.value;
        if (!cmpDate || !device_id) return;
        fetch('/api/personal/history', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
            body: JSON.stringify({ device_id, date_from: cmpDate, date_to: cmpDate,
                                   time_from: '00:00', time_to: '23:59' }),
        }).then(r => r.json()).then(res => {
            if (!res.ok || !res.points.length) return;
            compareLayer = L.featureGroup().addTo(map);
            for (let i = 1; i < res.points.length; i++) {
                L.polyline([[res.points[i-1].lat, res.points[i-1].lon], [res.points[i].lat, res.points[i].lon]],
                    { color: '#3b82f6', weight: 3.5, opacity: .8 }).addTo(compareLayer);
            }
            const km = res.stats.distance ?? 0;
            L.control({ position: 'bottomleft' }).onAdd = function () {
                const d = L.DomUtil.create('div', 'ps-legend');
                d.innerHTML = `<span class="sw" style="background:#059669"></span>${document.getElementById('psFrom').value} (${primaryPoints.length} pts)
                    <br><span class="sw" style="background:#3b82f6"></span>${cmpDate} — ${km} km (${res.points.length} pts)`;
                return d;
            };
            // remove previous compare legend: simpler — append legend to compareLayer container
        }).catch(() => {});
    }

    function renderAll(points, stops, stats) {
        currentPoints = points;
        currentStops = stops;
        clearLayers();
        document.getElementById('psPlayBtn').disabled = points.length < 2;
        document.getElementById('psPlayBar').style.display = '';
        if (!points.length) { showAlert('Is vehicle/date range ke liye koi point nahi mila.'); return; }

        // speed-colored route segments
        routeLayer = L.featureGroup().addTo(map);
        for (let i = 1; i < points.length; i++) {
            const a = points[i - 1], b = points[i];
            L.polyline([[a.lat, a.lon], [b.lat, b.lon]], {
                color: speedColor(a.speed || 0), weight: 4, opacity: .92,
            }).addTo(routeLayer);
        }
        // Start / End — compact circular badges (fixed size so text never clips)
        const first = points[0], last = points[points.length - 1];
        startEndLayer = L.featureGroup().addTo(map);
        function endpointIcon(letter, bg) {
            const size = 22;
            return L.divIcon({
                className: 'ps-endpoint-icon',
                html: `<div style="width:${size}px;height:${size}px;line-height:${size - 4}px;text-align:center;background:${bg};color:#fff;font-weight:800;font-size:11px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);">${letter}</div>`,
                iconSize: [size, size],
                iconAnchor: [size / 2, size / 2],
            });
        }
        L.marker([first.lat, first.lon], {
            icon: endpointIcon('S', '#059669'),
            zIndexOffset: 200,
        }).addTo(startEndLayer).bindTooltip('Start', { direction: 'top', offset: [0, -12] });
        L.marker([last.lat, last.lon], {
            icon: endpointIcon('E', '#dc2626'),
            zIndexOffset: 200,
        }).addTo(startEndLayer).bindTooltip('End', { direction: 'top', offset: [0, -12] });
        map.fitBounds(L.polyline(points.map(p => [p.lat, p.lon])).getBounds().pad(0.2));

        // Stops — numbered dots; duration only in tooltip/popup (no long overlapping labels)
        stopLayer = L.featureGroup().addTo(map);
        stops.forEach((st, i) => {
            if (st.lat == null || st.lon == null) return;
            const size = 20;
            const n = i + 1;
            L.marker([st.lat, st.lon], {
                icon: L.divIcon({
                    className: 'ps-stop-icon',
                    html: `<div style="width:${size}px;height:${size}px;line-height:${size - 4}px;text-align:center;background:#475569;color:#fff;font-weight:700;font-size:10px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);">${n}</div>`,
                    iconSize: [size, size],
                    iconAnchor: [size / 2, size / 2],
                }),
                zIndexOffset: 150,
            }).addTo(stopLayer)
                .bindTooltip(`Stop ${n}: ${st.duration_min} min`, { direction: 'top', offset: [0, -12] })
                .bindPopup(
                    `<b>Stop ${n}</b> (${st.status || 'Stopped'})<br>` +
                    `${st.duration_min} min<br>` +
                    `${new Date(st.start).toLocaleTimeString()} → ${new Date(st.end).toLocaleTimeString()}<br>` +
                    `${st.address || ''}`);
        });

        // stops side list
        const stopsEl = document.getElementById('psStopsList');
        stopsEl.innerHTML = stops.map((st, i) => `
            <div class="ps-stop-item" data-i="${i}">
                <span class="ps-stop-badge">${st.duration_min}m</span>
                <span>${new Date(st.start).toLocaleTimeString().slice(0, 5)} — ${new Date(st.end).toLocaleTimeString().slice(0, 5)}<br>
                <span class="text-muted">${(st.address || '—').slice(0, 60)}</span></span>
            </div>`).join('') || '<div class="text-muted small">Koi stop nahi.</div>';
        stopsEl.querySelectorAll('.ps-stop-item').forEach(el => {
            el.addEventListener('click', () => {
                const st = stops[Number(el.dataset.i)];
                if (st.lat != null) map.setView([st.lat, st.lon], 16);
            });
        });

        renderStats(stats);
        renderTable(points);
        renderChart(points);
        setupTimeline(points);
        // Crescent car icon at playback position (Live Map style)
        showPointAt(0);
    }

    function clearLayers() {
        [routeLayer, stopLayer, startEndLayer, replayMarker, trailLayer].forEach(l => { if (l) map.removeLayer(l); });
        routeLayer = stopLayer = startEndLayer = trailLayer = replayMarker = null;
        if (replayTimer) { clearInterval(replayTimer); replayTimer = null; }
    }

    function renderStats(stats) {
        statsBox.style.display = '';
        document.getElementById('psHPoints').textContent = stats.points ?? 0;
        document.getElementById('psHDist').textContent = stats.distance ?? 0;
        document.getElementById('psHMax').textContent = stats.max_speed ?? 0;
        document.getElementById('psHAvg').textContent = stats.avg_speed ?? 0;
        const el = document.getElementById('psHMove');
        if (el) el.textContent = (stats.moving_time_min ?? 0) + 'm';
    }

    function renderTable(points) {
        const rows = points.slice(-500).reverse().map(p => `
            <tr data-lat="${p.lat}" data-lon="${p.lon}">
                <td class="text-nowrap">${p.time ? String(p.time).replace('T', ' ').slice(11, 19) : '—'}</td>
                <td>${p.speed ?? 0}</td>
                <td>${p.status || '—'}</td>
                <td class="ps-td-addr" title="${p.address || ''}">${p.address || '—'}</td>
            </tr>`).join('');
        document.getElementById('psPointsBody').innerHTML = rows;
        document.querySelectorAll('#psPointsBody tr').forEach(tr => {
            tr.addEventListener('click', () => {
                map.setView([parseFloat(tr.dataset.lat), parseFloat(tr.dataset.lon)], 17);
            });
        });
    }

    function renderChart(points) {
        const labels = points.map(p => p.time ? String(p.time).slice(11, 19) : '');
        const speeds = points.map(p => p.speed || 0);
        if (chart) chart.destroy();
        const ctx = document.getElementById('psSpeedChart');
        chart = new Chart(ctx, {
            type: 'line',
            data: { labels, datasets: [{ data: speeds, borderColor: '#059669', pointRadius: 0, borderWidth: 2, tension: .25, fill: true, backgroundColor: 'rgba(16,185,129,.10)' }] },
            options: {
                plugins: { legend: { display: false }, tooltip: { enabled: true } },
                scales: { y: { beginAtZero: true, title: { display: true, text: 'km/h' } } },
                animation: false,
            },
        });
    }

    // ── timeline + animated replay ────────────────────────────────
    const tl = document.getElementById('psTimeline');
    const tlTime = document.getElementById('psTlTime');

    function setupTimeline(points) {
        tl.min = 0;
        tl.max = points.length - 1;
        tl.value = 0;
        tl.disabled = false;
        updateTlLabel();
    }
    function updateTlLabel() {
        const p = currentPoints[Number(tl.value)];
        tlTime.textContent = p && p.time ? String(p.time).replace('T', ' ').slice(11, 19) : '--:--:--';
    }
    tl.addEventListener('input', () => {
        stopTimer();
        showPointAt(Number(tl.value));
    });

    function showPointAt(i) {
        if (!currentPoints.length) return;
        const p = currentPoints[i];
        if (p.lat == null || p.lon == null) return;
        const icon = historyVehicleIcon(p);
        const vehSel = document.getElementById('psVehicle');
        const opt = vehSel && vehSel.options[vehSel.selectedIndex];
        const regno = (opt && opt.dataset.regno) || 'Vehicle';
        if (!replayMarker) {
            replayMarker = L.marker([p.lat, p.lon], { icon, zIndexOffset: 1000 }).addTo(map);
        } else {
            replayMarker.setLatLng([p.lat, p.lon]);
            replayMarker.setIcon(icon);
        }
        replayMarker.bindPopup(
            `<b>${regno}</b><br>${p.speed ?? 0} km/h · ${p.status || ''}<br>${String(p.time || '').replace('T', ' ').slice(0, 19)}<br>${p.address || ''}`);
        if (trailLayer) map.removeLayer(trailLayer);
        const trail = currentPoints.slice(0, i + 1).filter(q => q.lat != null && q.lon != null).map(q => [q.lat, q.lon]);
        if (trail.length > 1) {
            trailLayer = L.polyline(trail, { color: '#0f172a', weight: 3, opacity: .55, dashArray: '1' }).addTo(map);
        }
        replayIdx = i;
        updateTlLabel();
    }

    function stopTimer() {
        if (replayTimer) { clearInterval(replayTimer); replayTimer = null; }
        const b = document.getElementById('psPlayBtn');
        b.innerHTML = '<i class="bi bi-play-fill"></i>';
    }

    document.getElementById('psPlayBtn').addEventListener('click', function () {
        if (replayTimer) { stopTimer(); return; }
        if (currentPoints.length < 2) return;
        this.innerHTML = '<i class="bi bi-pause-fill"></i>';
        if (replayIdx >= currentPoints.length - 1) { replayIdx = 0; }
        // step ~5 points per tick scaled by speed multiplier (points every ~5-15s)
        replayTimer = setInterval(() => {
            replayIdx += replaySpeed;
            if (replayIdx >= currentPoints.length - 1) {
                replayIdx = currentPoints.length - 1;
                showPointAt(replayIdx);
                stopTimer();
                return;
            }
            tl.value = replayIdx;
            showPointAt(replayIdx);
        }, 220);
    });

    document.querySelectorAll('.ps-speed-btn').forEach(b => {
        b.addEventListener('click', () => {
            document.querySelectorAll('.ps-speed-btn').forEach(x => x.classList.remove('active'));
            b.classList.add('active');
            replaySpeed = Number(b.dataset.speed);
        });
    });

    // default today; auto-select first vehicle if none preselected; auto-run
    document.getElementById('psFrom').value = new Date().toISOString().slice(0, 10);
    document.getElementById('psTo').value = new Date().toISOString().slice(0, 10);
    const vehSel = document.getElementById('psVehicle');
    if (!vehSel.value && vehSel.options.length > 1) {
        vehSel.selectedIndex = 1; // first real vehicle (index 0 = placeholder)
    }
    if (vehSel.value) {
        form.requestSubmit();
    } else {
        showAlert('Koi vehicle cache mein nahi — pehle Live Map/Dashboard par Refresh karein.');
    }

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
