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
})();
