// web/static/settings.js
async function checkQbStatus() {
    try {
        const res = await api('/api/qb/status');
        const d = await res.json();
        const badge = document.getElementById('qb-status-badge');
        badge.className = d.running ? 'badge badge-up pointer' : 'badge badge-stop pointer';
        badge.textContent = d.running ? t('qb_running') : t('qb_stopped');
    } catch (e) {}
}

async function toggleQbPower() {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE === 'viewer') return;
    const res = await api('/api/qb/status');
    const d = await res.json();
    if (confirm(d.running ? t('confirm_qb_stop') : t('confirm_qb_start'))) {
        await api(`/api/qb/${d.running ? 'stop' : 'start'}`, 'POST');
        setTimeout(checkQbStatus, 1500);
    }
}

async function restartQb() {
    if (confirm(t('confirm_qb_restart'))) {
        await api('/api/qb/restart', 'POST');
        setTimeout(checkQbStatus, 2000);
    }
}

async function checkAutostart() {
    const res = await api('/api/autostart/status');
    const d = await res.json();
    const btn = document.getElementById('autostart-toggle-btn');
    btn.className = d.enabled ? 'btn btn-danger' : 'btn';
    btn.textContent = d.enabled ? t('disable') : t('enable');
}

async function toggleAutostart() {
    const res = await api('/api/autostart/toggle', 'POST');
    const d = await res.json();
    alert(d.message);
    checkAutostart();
}

async function openSettingsModal() {
    checkAutostart();
    if (typeof loadProfilesList === 'function') loadProfilesList();
    const res = await api('/api/settings');
    const d = await res.json();
    document.getElementById('setting-web-host').value = d.web_host;
    document.getElementById('setting-web-port').value = d.web_port;
    document.getElementById('setting-web-password').value = '';
    document.getElementById('setting-web-password').placeholder = d.has_password ? t('pwd_set_ph') : t('pwd_req_ph');
    document.getElementById('setting-qb-ip').value = d.qb_ip;
    document.getElementById('setting-qb-port').value = d.qb_port;
    document.getElementById('setting-qb-user').value = d.qb_user || 'admin';
    document.getElementById('setting-qb-password').value = '';
    document.getElementById('setting-qb-password').placeholder = d.has_qb_password ? t('qb_pwd_set_ph') : t('qb_pass_ph');
    document.getElementById('setting-snapshot-interval').value = d.snapshot_interval || 60;
    document.getElementById('setting-w1').value = d.w1;
    document.getElementById('setting-w2').value = d.w2;
    document.getElementById('setting-w3').value = d.w3;
    document.getElementById('settings-modal').style.display = 'flex';
}

function closeSettingsModal() {
    document.getElementById('settings-modal').style.display = 'none';
}

async function saveSettings() {
    const payload = {
        web_host: document.getElementById('setting-web-host').value.trim(),
        web_port: parseInt(document.getElementById('setting-web-port').value),
        web_password: document.getElementById('setting-web-password').value,
        qb_ip: document.getElementById('setting-qb-ip').value.trim(),
        qb_port: document.getElementById('setting-qb-port').value.trim(),
        qb_user: document.getElementById('setting-qb-user').value.trim() || 'admin',
        qb_password: document.getElementById('setting-qb-password').value,
        snapshot_interval: parseInt(document.getElementById('setting-snapshot-interval').value) || 60,
        w1: parseInt(document.getElementById('setting-w1').value) || 0,
        w2: parseInt(document.getElementById('setting-w2').value) || 0,
        w3: parseInt(document.getElementById('setting-w3').value) || 0
    };
    const res = await api('/api/settings', 'POST', payload);
    const d = await res.json();
    if (!res.ok) return alert(d.error || t('save_err'));
    alert(d.message);
    closeSettingsModal();
    if (d.port_changed) setTimeout(() => { window.location.port = payload.web_port; }, 1500);
    else loadTorrents(true);
}

function downloadBackupZip() {
    const noHist = document.getElementById('backup-no-history').checked ? '1' : '0';
    const noSec = document.getElementById('backup-no-secrets').checked ? '1' : '0';
    window.location.href = `/api/backup/export?exclude_history=${noHist}&strip_secrets=${noSec}`;
}

async function uploadRestoreZip(file) {
    if (!file) return;
    if (!confirm(`⚠️ ВНИМАНИЕ: Восстановление из архива "${file.name}" заменит текущие базы данных и настройки!\n\nПродолжить?`)) {
        document.getElementById('restore-file-input').value = '';
        return;
    }
    const fd = new FormData();
    fd.append('file', file);
    try {
        const res = await fetch('/api/backup/restore', {
            method: 'POST',
            headers: { 'X-CSRF-Token': CSRF_TOKEN },
            body: fd
        });
        const d = await res.json();
        alert(d.message || d.error);
        if (d.success) {
            closeSettingsModal();
        }
    } catch (e) {
        alert('Ошибка загрузки: ' + e.message);
    } finally {
        document.getElementById('restore-file-input').value = '';
    }
}