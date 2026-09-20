/* Personal (Crescent) vehicles list: search/filter/CSV + refresh */
(function () {
    'use strict';
    const CSRF = (window.FleetConfig && window.FleetConfig.csrfToken) ||
        (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

    const searchBox = document.getElementById('psSearch');
    const groupFilter = document.getElementById('psGroupFilter');
    const statusFilter = document.getElementById('psStatusFilter');
    const csvBtn = document.getElementById('psCsvBtn');
    const refreshBtn = document.getElementById('psRefreshBtn');
    const rows = Array.from(document.querySelectorAll('#psTable tbody tr[data-search]'));

    function applyFilters() {
        const q = (searchBox.value || '').toLowerCase();
        const g = groupFilter.value;
        const s = statusFilter.value;
        rows.forEach(tr => {
            const matchQ = !q || (tr.dataset.search || '').toLowerCase().includes(q);
            const matchG = !g || tr.dataset.group === g;
            const matchS = !s || tr.dataset.status === s;
            tr.style.display = (matchQ && matchG && matchS) ? '' : 'none';
        });
    }

    if (searchBox) searchBox.addEventListener('input', applyFilters);
    if (groupFilter) groupFilter.addEventListener('change', applyFilters);
    if (statusFilter) statusFilter.addEventListener('change', applyFilters);

    if (csvBtn) csvBtn.addEventListener('click', function () {
        const visible = rows.filter(tr => tr.style.display !== 'none');
        const header = ['RegNo', 'Status', 'Speed', 'Ignition', 'Mileage', 'Group', 'Type', 'Driver', 'Address', 'LastUpdate'];
        const esc = v => '"' + String(v ?? '').replace(/"/g, '""') + '"';
        const lines = [header.map(esc).join(',')];
        visible.forEach(tr => {
            const cells = Array.from(tr.querySelectorAll('td')).slice(0, 10).map(td => td.textContent.trim());
            lines.push(cells.map(esc).join(','));
        });
        const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'crescent_vehicles.csv';
        a.click();
        URL.revokeObjectURL(a.href);
    });

    if (refreshBtn) refreshBtn.addEventListener('click', function () {
        refreshBtn.disabled = true;
        fetch('/api/personal/refresh', { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
            .then(r => r.json())
            .then(res => { if (!res.ok) alert(res.error || 'Refresh failed'); window.location.reload(); })
            .catch(e => { alert('Network error: ' + e); refreshBtn.disabled = false; });
    });
})();
