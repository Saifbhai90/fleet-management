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
    let replayMarker = null;
    let trailLayer = null;        // traveled part during replay
    let chart = null;
    let replayTimer = null;
    let replayIdx = 0;
    let replaySpeed = 4;
    let currentPoints = [];
    let currentStops = [];

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
        }).catch(e => showAlert('Network error: ' + e))
          .finally(() => { btn.disabled = false; });
    });

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
        // start/end pins
        const first = points[0], last = points[points.length - 1];
        L.marker([first.lat, first.lon], {
            icon: L.divIcon({ className: '', html: '<div style="background:#059669;color:#fff;font-weight:800;font-size:10px;padding:3px 8px;border-radius:999px;border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.35);">START</div>', iconAnchor: [26, 12] }),
        }).addTo(map).bindTooltip('Start');
        L.marker([last.lat, last.lon], {
            icon: L.divIcon({ className: '', html: '<div style="background:#dc2626;color:#fff;font-weight:800;font-size:10px;padding:3px 8px;border-radius:999px;border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.35);">END</div>', iconAnchor: [26, 12] }),
        }).addTo(map).bindTooltip('End');
        map.fitBounds(L.polyline(points.map(p => [p.lat, p.lon])).getBounds().pad(0.2));

        // stops
        stopLayer = L.featureGroup().addTo(map);
        stops.forEach((st, i) => {
            if (st.lat == null) return;
            L.marker([st.lat, st.lon], {
                icon: L.divIcon({ className: '', html: `<div style="background:#475569;color:#fff;font-weight:700;font-size:10px;padding:3px 8px;border-radius:999px;border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.35);white-space:nowrap;">⏸ ${st.duration_min} min</div>`, iconAnchor: [30, 12] }),
            }).addTo(stopLayer).bindPopup(
                `<b>Stop ${i + 1}</b> (${st.status || 'Stopped'})<br>${new Date(st.start).toLocaleTimeString()} → ${new Date(st.end).toLocaleTimeString()}<br>${st.address || ''}`);
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
    }

    function clearLayers() {
        [routeLayer, stopLayer, replayMarker, trailLayer].forEach(l => { if (l) map.removeLayer(l); });
        routeLayer = stopLayer = trailLayer = replayMarker = null;
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
        if (!replayMarker) {
            replayMarker = L.marker([p.lat, p.lon]).addTo(map);
        } else {
            replayMarker.setLatLng([p.lat, p.lon]);
        }
        replayMarker.bindPopup(
            `<b>${p.speed ?? 0} km/h</b> · ${p.status || ''}<br>${String(p.time).replace('T', ' ').slice(0, 19)}<br>${p.address || ''}`);
        if (trailLayer) map.removeLayer(trailLayer);
        const trail = currentPoints.slice(0, i + 1).map(q => [q.lat, q.lon]);
        if (trail.length > 1) {
            trailLayer = L.polyline(trail, { color: '#0f172a', weight: 3, opacity: .55, dashArray: '1' }).addTo(map);
        }
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
})();
