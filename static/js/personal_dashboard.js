/* Personal (Crescent) dashboard: refresh, auto-poll, filter, search */
(function () {
    'use strict';
    const CSRF = (window.FleetConfig && window.FleetConfig.csrfToken) ||
        (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

    const refreshBtn = document.getElementById('psRefreshBtn');
    const searchBox = document.getElementById('psSearch');
    const cardsWrap = document.getElementById('psCards');
    const statEls = {
        total: document.getElementById('psTotal'), Moving: document.getElementById('psMoving'),
        Idle: document.getElementById('psIdle'), Parked: document.getElementById('psParked'),
        Offline: document.getElementById('psOffline'),
    };
    let currentFilter = 'all';
    let pollSeconds = 30;
    let timer = null;

    function setStatus(el, msg, ok) {
        el.disabled = true;
        const old = el.innerHTML;
        el.innerHTML = msg;
        setTimeout(() => { el.innerHTML = old; el.disabled = false; }, 1200);
        void ok;
    }

    function refresh() {
        if (!refreshBtn) return Promise.resolve();
        setStatus(refreshBtn, '<span class="spinner-border spinner-border-sm"></span>', false);
        return fetch('/api/personal/refresh', {
            method: 'POST', headers: { 'X-CSRFToken': CSRF },
        }).then(r => r.json()).then(res => {
            if (res.ok) {
                window.location.reload();
            } else {
                alert(res.error || 'Refresh failed');
            }
        }).catch(e => alert('Network error: ' + e));
    }

    function poll() {
        fetch('/api/personal/positions').then(r => r.json()).then(res => {
            if (!res.ok) return;
            pollSeconds = res.poll_seconds || 30;
            Object.keys(statEls).forEach(k => {
                if (statEls[k] && res.stats[k] !== undefined) statEls[k].textContent = res.stats[k];
            });
            applyFilter();
        }).catch(() => {});
    }

    function applyFilter() {
        if (!cardsWrap) return;
        cardsWrap.querySelectorAll('.ps-card').forEach(card => {
            const st = card.dataset.status;
            const q = (searchBox && searchBox.value || '').toLowerCase();
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

    function schedule() {
        clearTimeout(timer);
        timer = setTimeout(() => { poll(); schedule(); }, (pollSeconds || 30) * 1000);
    }
    if (cardsWrap) schedule();
})();
