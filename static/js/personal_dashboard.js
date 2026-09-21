/* Personal (Crescent) dashboard: refresh, today summaries, fleet KPI charts, filters */
(function () {
    'use strict';
    const CSRF = (window.FleetConfig && window.FleetConfig.csrfToken) ||
        (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

    const refreshBtn = document.getElementById('psRefreshBtn');
    const searchBox = document.getElementById('psSearch');
    const cardsWrap = document.getElementById('psCards');
    const todayWrap = document.getElementById('psToday');
    const statEls = {
        total: document.getElementById('psTotal'), Moving: document.getElementById('psMoving'),
        Idle: document.getElementById('psIdle'), Parked: document.getElementById('psParked'),
        Offline: document.getElementById('psOffline'),
    };
    let currentFilter = 'all';
    let pollSeconds = 30;
    let timer = null;
    let lastVehicles = [];

    function refresh() {
        if (!refreshBtn) return Promise.resolve();
        refreshBtn.disabled = true;
        refreshBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
        return fetch('/api/personal/refresh', {
            method: 'POST', headers: { 'X-CSRFToken': CSRF },
        }).then(r => r.json()).then(res => {
            if (res.ok) window.location.reload();
            else alert(res.error || 'Refresh failed');
        }).catch(e => alert('Network error: ' + e))
          .finally(() => { refreshBtn.disabled = false; refreshBtn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Refresh'; });
    }

    function poll() {
        fetch('/api/personal/positions').then(r => r.json()).then(res => {
            if (!res.ok) return;
            pollSeconds = res.poll_seconds || 30;
            lastVehicles = res.vehicles;
            Object.keys(statEls).forEach(k => {
                if (statEls[k] && res.stats[k] !== undefined) statEls[k].textContent = res.stats[k];
            });
            applyFilter();
        }).catch(() => {});
    }

    function applyFilter() {
        if (!cardsWrap) return;
        const q = (searchBox && searchBox.value || '').toLowerCase();
        cardsWrap.querySelectorAll('.ps-card').forEach(card => {
            const st = card.dataset.status;
            const matchStatus = currentFilter === 'all' || st === currentFilter;
            const matchSearch = !q || (card.dataset.search || '').toLowerCase().includes(q);
            card.style.display = (matchStatus && matchSearch) ? '' : 'none';
        });
    }

    document.querySelectorAll('.ps-stat[data-filter]').forEach(el => {
        el.addEventListener('click', () => {
            document.querySelectorAll('.ps-stat').forEach(x => x.classList.remove('selected'));
            el.classList.add('selected');
            currentFilter = el.dataset.filter;
            applyFilter();
        });
    });
    if (searchBox) searchBox.addEventListener('input', applyFilter);
    if (refreshBtn) refreshBtn.addEventListener('click', refresh);

    const accSel = document.getElementById('psAccount');
    if (accSel) accSel.addEventListener('change', () => {
        window.location = '/personal?account=' + accSel.value;
    });

    // ── Aaj ka summary (per-vehicle daily aggregates) ─────────────
    function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }

    function loadToday() {
        if (!todayWrap) return;
        fetch('/api/personal/daily-summary').then(r => r.json()).then(res => {
            if (!res.ok) { todayWrap.innerHTML = '<div class="text-muted small p-2">' + esc(res.error || 'Summary load failed') + '</div>'; return; }
            if (!res.rows.length) { todayWrap.innerHTML = '<div class="text-muted small p-2">Aaj ka data abhi compute nahi hua — Refresh dabayein.</div>'; return; }
            todayWrap.innerHTML = res.rows.map(r => {
                const noMovement = (r.distance_km || 0) === 0 && (r.moving_min || 0) === 0;
                if (noMovement) {
                    return `<div class="ps-card status-parked" style="--ribbon:#64748b;">
                        <div class="ps-card-head">
                            <i class="bi bi-p-square text-muted"></i>
                            <a class="ps-regno" href="/personal/history?vehicle=${esc(r.device_id)}">${esc(r.regno || '—')}</a>
                            <span class="ps-badge parked">Parked</span>
                        </div>
                        <div class="ps-card-body">
                            <div class="ps-row"><i class="bi bi-moon"></i> Aaj koi movement nahi — vehicle parked rahi.</div>
                        </div>
                    </div>`;
                }
                return `<div class="ps-card status-moving" style="--ribbon:#10b981;">
                    <div class="ps-card-head">
                        <i class="bi bi-sun text-warning"></i>
                        <a class="ps-regno" href="/personal/history?vehicle=${esc(r.device_id)}">${esc(r.regno || '—')}</a>
                        <span class="ps-badge moving">${r.trips || 0} trips</span>
                    </div>
                    <div class="ps-card-body">
                        <div class="ps-grid2">
                            <div class="ps-row"><i class="bi bi-road"></i><b>${r.distance_km ?? 0}</b>&nbsp;km aaj</div>
                            <div class="ps-row"><i class="bi bi-stopwatch"></i><b>${r.moving_min ?? 0}</b>&nbsp;min moving</div>
                            <div class="ps-row"><i class="bi bi-hourglass"></i><b>${r.idle_min ?? 0}</b>&nbsp;min idle</div>
                            <div class="ps-row"><i class="bi bi-speedometer2"></i><b>${r.max_speed ?? 0}</b>&nbsp;max km/h</div>
                        </div>
                        <div class="ps-chips">
                            <span class="ps-chip text-danger"><i class="bi bi-exclamation-triangle"></i> ${r.harsh_brake || 0} brake</span>
                            <span class="ps-chip text-warning"><i class="bi bi-gauge"></i> ${r.harsh_accel || 0} accel</span>
                            <span class="ps-chip"><i class="bi bi-coin"></i> ${r.overspeed || 0} overspeed</span>
                        </div>
                    </div>
                </div>`;
            }).join('');
        }).catch(() => { todayWrap.innerHTML = '<div class="text-muted small p-2">Summary load nahi hui.</div>'; });
    }

    // ── Fleet KPI charts (last 14 days) ───────────────────────────
    let distChart = null, utilChart = null, scoreChart = null;

    function loadKPIs() {
        const meta = document.getElementById('psKpiMeta');
        const hasCanvas = document.getElementById('psKpiDist');
        if (!hasCanvas) return;
        if (typeof Chart === 'undefined') {
            if (meta) meta.textContent = 'Chart library load nahi hui (refresh karein).';
            return;
        }
        if (meta) meta.textContent = 'KPIs compute ho rahe hain (pehli baar 15-40 sec lagta hai, uske baad cached)…';
        fetch('/api/personal/fleet-kpis?days=14').then(r => r.json()).then(res => {
            if (!res.ok) { if (meta) meta.textContent = 'KPI error: ' + (res.error || 'load failed'); return; }
            const s = res.series || [];
            if (!s.length) {
                if (meta) meta.textContent = 'KPI data abhi empty hai — pehle Refresh / History load karein.';
                return;
            }
            const labels = s.map(x => (x.date || '').slice(5) || x.date);
            const mk = (id, data, color, type, suffix) => {
                const el = document.getElementById(id);
                if (!el) return null;
                return new Chart(el, {
                    type: type,
                    data: {
                        labels,
                        datasets: [{
                            data,
                            borderColor: color,
                            backgroundColor: color + '33',
                            fill: type === 'line',
                            tension: .3,
                            pointRadius: 2,
                            borderWidth: 2,
                        }],
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            y: { beginAtZero: true, ticks: { callback: v => v + (suffix || '') } },
                        },
                        animation: false,
                    },
                });
            };
            if (distChart) distChart.destroy();
            if (utilChart) utilChart.destroy();
            if (scoreChart) scoreChart.destroy();
            distChart = mk('psKpiDist', s.map(x => Number(x.distance_km) || 0), '#10b981', 'line');
            utilChart = mk('psKpiUtil', s.map(x => Number(x.utilization) || 0), '#3b82f6', 'bar', '%');
            scoreChart = mk('psKpiScore', s.map(x => (x.score == null ? null : Number(x.score))), '#f59e0b', 'line');
            const tot = s.reduce((a, x) => a + (Number(x.distance_km) || 0), 0);
            if (meta) {
                meta.textContent = `14 din mein total: ${tot.toFixed(0)} km · overspeed events: ${s.reduce((a, x) => a + (Number(x.overspeed) || 0), 0)}`;
            }
        }).catch(e => { if (meta) meta.textContent = 'KPI network error: ' + e; });
    }

    function schedule() {
        clearTimeout(timer);
        timer = setTimeout(() => { poll(); schedule(); }, (pollSeconds || 30) * 1000);
    }
    if (cardsWrap) schedule();
    poll();
    loadToday();
    loadKPIs();
})();
