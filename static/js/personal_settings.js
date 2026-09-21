/* Personal (Crescent) settings: save credentials, test connection, clear log */
(function () {
    'use strict';
    const CSRF = (window.FleetConfig && window.FleetConfig.csrfToken) ||
        (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

    const saveMsg = document.getElementById('psSaveMsg');
    const testResult = document.getElementById('psTestResult');

    document.getElementById('psPwToggle').addEventListener('click', function () {
        const pw = document.getElementById('psPassword');
        pw.type = pw.type === 'password' ? 'text' : 'password';
    });

    document.getElementById('psSettingsForm').addEventListener('submit', function (ev) {
        ev.preventDefault();
        saveMsg.textContent = '';
        const payload = {
            api_base: document.getElementById('psApiBase').value.trim(),
            alt_api_base: document.getElementById('psAltBase').value.trim(),
            username: document.getElementById('psUsername').value.trim(),
            password: document.getElementById('psPassword').value.trim(),
            poll_seconds: document.getElementById('psPoll').value,
            fcm_token: (document.getElementById('psFcm') || {}).value || '',
            commands_enabled: (document.getElementById('psCmdToggle') || {}).checked || false,
        };
        fetch('/api/personal/settings/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
            body: JSON.stringify(payload),
        }).then(r => r.json()).then(res => {
            saveMsg.innerHTML = res.ok
                ? '<span class="text-success"><i class="bi bi-check-circle"></i> ' + (res.message || 'Saved.') + '</span>'
                : '<span class="text-danger">' + (res.error || 'Save failed') + '</span>';
        }).catch(e => { saveMsg.innerHTML = '<span class="text-danger">Network error: ' + e + '</span>'; });
    });

    document.getElementById('psTestBtn').addEventListener('click', function () {
        const btn = this;
        btn.disabled = true;
        testResult.innerHTML = '<div class="small text-muted">Testing&hellip;</div>';
        fetch('/api/personal/test-connection', {
            method: 'POST', headers: { 'X-CSRFToken': CSRF },
        }).then(r => r.json()).then(res => {
            const rows = (res.steps || []).map(s => `
                <tr class="${s.ok ? 'table-success' : 'table-danger'}">
                    <td>${s.step}</td>
                    <td>${s.ok ? '✔' : '✘'}</td>
                    <td class="small">${s.detail || ''}</td>
                </tr>`).join('');
            testResult.innerHTML = `
                <div class="alert ${res.ok ? 'alert-success' : 'alert-danger'} py-2 mb-1">
                    ${res.ok ? '<i class="bi bi-check-circle"></i> Connection OK' :
                               '<i class="bi bi-x-octagon"></i> ' + (res.error || 'Connection failed')}
                </div>
                <table class="table table-sm"><thead><tr><th>Check</th><th></th><th>Detail</th></tr></thead><tbody>${rows}</tbody></table>`;
        }).catch(e => { testResult.innerHTML = '<div class="text-danger small">Network error: ' + e + '</div>'; })
          .finally(() => { btn.disabled = false; });
    });

    const clearBtn = document.getElementById('psClearLogBtn');
    if (clearBtn) {
        clearBtn.addEventListener('click', function () {
            if (!confirm('API log clear kar dein?')) return;
            fetch('/api/personal/log/clear', {
                method: 'POST', headers: { 'X-CSRFToken': CSRF },
            }).then(() => window.location.reload());
        });
    }

    // ── Multi-account management ──────────────────────────────────
    const accList = document.getElementById('psAccountsList');

    function loadAccounts() {
        if (!accList) return;
        fetch('/api/personal/accounts').then(r => r.json()).then(res => {
            if (!res.ok) return;
            if (!res.accounts.length) { accList.innerHTML = '<div class="text-muted small">Koi account nahi.</div>'; return; }
            accList.innerHTML = res.accounts.map(a => `
                <div class="ps-account-row d-flex align-items-center gap-2 border rounded p-2 mb-1 ${a.is_active ? 'active' : ''}">
                    <div class="flex-fill small">
                        <b>${a.label}</b> ${a.is_active ? '<span class="badge bg-success">active ★</span>' : ''}
                        <div class="text-muted">${a.username} · ${a.vehicles} vehicles</div>
                    </div>
                    ${a.is_active ? '' : `<button class="btn btn-sm btn-outline-success" data-act="${a.id}">Activate</button>`}
                    ${a.is_active ? '' : `<button class="btn btn-sm btn-outline-danger" data-del="${a.id}">×</button>`}
                </div>`).join('');
            accList.querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', () => {
                fetch(`/api/personal/accounts/${b.dataset.act}/activate`, { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
                    .then(r => r.json()).then(res => { if (res.ok) window.location.reload(); });
            }));
            accList.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', () => {
                if (!confirm('Account delete karein? Uska vehicle cache bhi jayega.')) return;
                fetch(`/api/personal/accounts/${b.dataset.del}/delete`, { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
                    .then(r => r.json()).then(res => { if (res.ok) loadAccounts(); });
            }));
        }).catch(() => {});
    }

    const accForm = document.getElementById('psAccForm');
    if (accForm) accForm.addEventListener('submit', ev => {
        ev.preventDefault();
        fetch('/api/personal/accounts/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
            body: JSON.stringify({
                label: document.getElementById('psAccLabel').value.trim(),
                username: document.getElementById('psAccUser').value.trim(),
                password: document.getElementById('psAccPass').value.trim(),
            }),
        }).then(r => r.json()).then(res => {
            const msg = document.getElementById('psAccMsg');
            msg.innerHTML = res.ok ? `<span class="text-success">${res.message}</span>` : `<span class="text-danger">${res.error}</span>`;
            if (res.ok) { accForm.reset(); loadAccounts(); }
        }).catch(e => { alert('Network error: ' + e); });
    });

    loadAccounts();
})();