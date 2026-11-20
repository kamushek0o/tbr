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
    if (typeof loadVaultSettings === 'function') loadVaultSettings();
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

    const chMbps = document.getElementById('setting-max-channel-mbps');
    if (chMbps) chMbps.value = d.max_channel_mbps ?? 1000;

    const diskSel = document.getElementById('setting-monitored-disk');
    if (diskSel) {
        diskSel.innerHTML = '<option value="">Авто (диск с макс. числом раздач)</option>';
        (d.disks || []).forEach(dk => {
            const opt = document.createElement('option');
            opt.value = dk.path;
            opt.textContent = `${dk.path} — ${dk.free_fmt} своб. (${dk.torrents_count} раздач)`;
            diskSel.appendChild(opt);
        });
        diskSel.value = d.monitored_disk || '';
    }

    const kaBlock = document.getElementById('settings-keepawake-block');
    if (kaBlock) kaBlock.classList.toggle('hidden', !d.is_windows);
    const kaChk = document.getElementById('setting-keepawake-enabled');
    if (kaChk) kaChk.checked = Boolean(d.keep_awake_enabled);
    const kaKb = document.getElementById('setting-keepawake-kb');
    if (kaKb) kaKb.value = d.keep_awake_min_kb ?? 500;
    const kaDisp = document.getElementById('setting-keepawake-display');
    if (kaDisp) kaDisp.checked = Boolean(d.keep_awake_display);

    const wdChk = document.getElementById('setting-watchdog-enabled');
    if (wdChk) wdChk.checked = Boolean(d.watchdog_enabled);
    const wdTo = document.getElementById('setting-watchdog-timeout');
    if (wdTo) wdTo.value = d.watchdog_timeout_min ?? 3;
    const wdExe = document.getElementById('setting-watchdog-exe');
    if (wdExe) {
        wdExe.value = d.watchdog_exe_path || '';
        wdExe.placeholder = d.watchdog_exe_detected || 'автоопределение';
    }

    document.getElementById('settings-modal').style.display = 'flex';
}

function closeSettingsModal() { document.getElementById('settings-modal').style.display = 'none'; }

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
        w3: parseInt(document.getElementById('setting-w3').value) || 0,
        max_channel_mbps: parseInt(document.getElementById('setting-max-channel-mbps')?.value) || 1000,
        monitored_disk: document.getElementById('setting-monitored-disk')?.value || '',
        keep_awake_enabled: document.getElementById('setting-keepawake-enabled')?.checked || false,
        keep_awake_min_kb: parseInt(document.getElementById('setting-keepawake-kb')?.value) || 0,
        keep_awake_display: document.getElementById('setting-keepawake-display')?.checked || false,
        watchdog_enabled: document.getElementById('setting-watchdog-enabled')?.checked || false,
        watchdog_timeout_min: parseInt(document.getElementById('setting-watchdog-timeout')?.value) || 3,
        watchdog_exe_path: document.getElementById('setting-watchdog-exe')?.value.trim() || ''
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
        const res = await fetch('/api/backup/restore', { method: 'POST', headers: { 'X-CSRF-Token': CSRF_TOKEN }, body: fd });
        const d = await res.json();
        alert(d.message || d.error);
        if (d.success) closeSettingsModal();
    } catch (e) {
        alert('Ошибка загрузки: ' + e.message);
    } finally {
        document.getElementById('restore-file-input').value = '';
    }
}