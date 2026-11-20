// web/static/safety_ui.js
let _lastDoctorReportMd = '';
let _qbVaultList = [];
let _onbStep = 1;

async function loadSafetyToolsTab() {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
    loadTrashItems();
    loadQbVault();
    loadActiveSessions();
}

async function loadTrashItems() {
    const tbody = document.getElementById('trash-tbody');
    if (!tbody) return;
    try {
        const res = await api('/api/trash');
        if (!res.ok) return;
        const d = await res.json();
        const items = d.items || [];
        if (!items.length) {
            tbody.innerHTML = '<tr><td colspan="4" class="center-msg muted-text">Корзина _tbr_trash пуста</td></tr>';
            return;
        }
        tbody.innerHTML = '';
        items.forEach(it => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="white-space:normal;"><b>${escapeHtml(it.name)}</b><div class="lbl-xs muted-text">${escapeHtml(it.original_path)}</div></td>
                <td><b>${escapeHtml(it.size_fmt)}</b></td>
                <td class="muted-text">${escapeHtml(it.expires_fmt)}</td>
                <td class="row-gap">
                    <button class="btn btn-xs" onclick="restoreTrashItem('${escapeHtml(it.id)}')">♻️ Вернуть</button>
                    <button class="btn btn-danger btn-xs" onclick="purgeTrashItem('${escapeHtml(it.id)}')">🗑️</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {}
}

async function restoreTrashItem(id) {
    const res = await api('/api/trash/restore', 'POST', { id });
    const d = await res.json();
    alert(d.message || d.error);
    loadTrashItems();
}

async function purgeTrashItem(id) {
    if (!confirm('Удалить объект из корзины НАВСЕГДА без возможности восстановления?')) return;
    const res = await api('/api/trash/purge', 'POST', { id });
    const d = await res.json();
    if (!res.ok) alert(d.message || d.error);
    loadTrashItems();
}

async function loadQbVault() {
    const box = document.getElementById('qb-vault-list');
    const dirInp = document.getElementById('qb-vault-dir');
    if (!box) return;
    try {
        const res = await api('/api/qb_vault');
        if (!res.ok) return;
        const d = await res.json();
        if (dirInp && !dirInp.value) dirInp.placeholder = d.config_dir || 'Путь к конфигам qB';
        _qbVaultList = d.backups || [];
        if (!_qbVaultList.length) {
            box.innerHTML = '<span class="muted-text">Снимков конфигов пока нет</span>';
            return;
        }
        box.innerHTML = _qbVaultList.map(b => `
            <div class="row-between" style="background:var(--bg-input); padding:6px 8px; border-radius:6px;">
                <div><b>${escapeHtml(b.name)}</b> <span class="lbl-xs muted-text">(${escapeHtml(b.date)}, ${escapeHtml(b.size_fmt)})</span></div>
                <div class="row-gap">
                    <button class="btn btn-secondary btn-xs" onclick="openQbDiffModal('${escapeHtml(b.name)}')">🔍 Diff</button>
                    <button class="btn btn-danger btn-xs" onclick="restoreQbVault('${escapeHtml(b.name)}')">♻️ Восст.</button>
                </div>
            </div>
        `).join('');
    } catch (e) {}
}

async function createQbVaultBackup() {
    const res = await api('/api/qb_vault/backup', 'POST');
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка бэкапа');
    loadQbVault();
}

async function saveQbVaultDir() {
    const dir = document.getElementById('qb-vault-dir')?.value.trim() || '';
    const res = await api('/api/qb_vault/set_dir', 'POST', { config_dir: dir });
    const d = await res.json();
    alert('Папка конфигов: ' + (d.config_dir || 'не найдена'));
    loadQbVault();
}

async function restoreQbVault(name) {
    if (!confirm(`Восстановить конфиг qBittorrent из снимка "${name}"?\nqBittorrent должен быть предварительно остановлен!`)) return;
    const res = await api('/api/qb_vault/restore', 'POST', { name });
    const d = await res.json();
    alert(d.message || d.error);
}

function openQbDiffModal(snapName) {
    const selA = document.getElementById('qb-diff-a');
    const selB = document.getElementById('qb-diff-b');
    if (!selA || !selB) return;
    selA.innerHTML = ''; selB.innerHTML = '';
    _qbVaultList.forEach(b => {
        selA.add(new Option(b.name, b.name));
        selB.add(new Option(b.name, b.name));
    });
    if (_qbVaultList.length > 1) selA.selectedIndex = 1;
    selB.value = snapName;
    document.getElementById('qb-diff-modal').style.display = 'flex';
    runQbConfigDiff();
}

async function runQbConfigDiff() {
    const snap_a = document.getElementById('qb-diff-a')?.value;
    const snap_b = document.getElementById('qb-diff-b')?.value;
    const filename = document.getElementById('qb-diff-file')?.value || 'qBittorrent.ini';
    const out = document.getElementById('qb-diff-out');
    if (!out) return;
    out.textContent = '⏳ Сравнение...';
    const res = await api('/api/qb_vault/diff', 'POST', { snap_a, snap_b, filename });
    const d = await res.json();
    out.textContent = d.success ? d.diff : (d.error || 'Ошибка');
}

async function runEnvDoctor() {
    const box = document.getElementById('doctor-results-box');
    const copyBtn = document.getElementById('btn-doctor-copy-md');
    if (!box) return;
    box.innerHTML = '<span class="muted-text">⏳ Диагностика системы...</span>';
    const res = await api('/api/doctor/check');
    if (!res.ok) return;
    const { diag, report_md } = await res.json();
    _lastDoctorReportMd = report_md || '';
    if (copyBtn) copyBtn.classList.remove('hidden');

    const dbHtml = (diag.databases || []).map(x => `<span class="badge ${x.quick_check === 'ok' ? 'badge-up' : 'badge-err'}">${escapeHtml(x.name)}: ${escapeHtml(x.quick_check)}</span>`).join(' ');
    box.innerHTML = `
        <div class="row-wrap" style="gap:6px;">
            <span class="badge ${diag.qb.api_ok ? 'badge-up' : 'badge-err'}">qB API: ${escapeHtml(diag.qb.version)}</span>
            <span class="badge ${diag.bt_backup.rw ? 'badge-up' : 'badge-err'}">BT_backup r/w: ${diag.bt_backup.rw ? 'OK' : 'FAIL'}</span>
            <span class="badge ${diag.time_skew.ok === false ? 'badge-stall' : 'badge-up'}">Время: ${diag.time_skew.skew_sec !== null ? diag.time_skew.skew_sec + 'с' : '—'}</span>
        </div>
        <div class="row-wrap mt-10" style="gap:6px;">${dbHtml}</div>
    `;
}

function copyDoctorReport() {
    if (!_lastDoctorReportMd) return;
    if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(_lastDoctorReportMd).then(() => alert('✅ Санитизированный отчёт скопирован в буфер (без токенов, пасскеев и имён)!'));
    } else prompt('Отчёт для GitHub Issue:', _lastDoctorReportMd);
}

async function loadActiveSessions() {
    const box = document.getElementById('sessions-list-box');
    if (!box) return;
    try {
        const res = await api('/api/sessions');
        if (!res.ok) return;
        const list = (await res.json()).sessions || [];
        if (!list.length) { box.innerHTML = '<span class="muted-text">Нет активных сессий</span>'; return; }
        box.innerHTML = list.map(s => `
            <div class="row-between" style="background:var(--bg-input); padding:6px 8px; border-radius:6px;">
                <div style="min-width:0; flex:1;">
                    <b>${escapeHtml(s.profile_login)}</b> <span class="badge ${s.is_current ? 'badge-up' : 'badge-pause'}">${s.is_current ? 'Текущая' : escapeHtml(s.ip)}</span>
                    <div class="lbl-xs muted-text" style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(s.last_seen_fmt)} • ${escapeHtml(s.user_agent)}</div>
                </div>
                ${s.is_current ? '' : `<button class="btn btn-danger btn-xs" onclick="revokeSingleSession('${escapeHtml(s.sid)}')">✕</button>`}
            </div>
        `).join('');
    } catch (e) {}
}

async function revokeOtherSessions() {
    if (!confirm('Завершить все остальные активные сессии?')) return;
    const res = await api('/api/sessions/revoke_others', 'POST');
    const d = await res.json();
    alert(d.message || 'Готово');
    loadActiveSessions();
}

async function revokeSingleSession(sid) {
    await api('/api/sessions/revoke', 'POST', { sid });
    loadActiveSessions();
}

async function runAutopilotDryRun(ruleId = null) {
    const modal = document.getElementById('dry-run-modal');
    const tbody = document.getElementById('dry-run-tbody');
    const sum = document.getElementById('dry-run-summary');
    if (!modal || !tbody) return;
    modal.style.display = 'flex';
    sum.textContent = '⏳ Прогон правил без изменений...';
    tbody.innerHTML = '<tr><td colspan="4" class="center-msg">Оценка условий...</td></tr>';
    const res = await api('/api/automation/dry_run', 'POST', ruleId ? { rule_id: ruleId } : {});
    const d = await res.json();
    if (!d.success) { sum.textContent = d.error || 'Ошибка'; tbody.innerHTML = ''; return; }
    sum.textContent = `Проверено правил: ${d.rules_checked} • Раздач: ${d.torrents_scanned} • Попало под правила: ${(d.matches || []).length}`;
    if (!d.matches?.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="center-msg">Ни одна раздача сейчас не попадает под условия</td></tr>';
        return;
    }
    tbody.innerHTML = d.matches.map(m => `
        <tr>
            <td style="white-space:normal;"><b>${escapeHtml(m.name)}</b><div class="lbl-xs muted-text">${escapeHtml(m.rule_name)}${m.already_triggered ? ' (уже срабатывало)' : ''}</div></td>
            <td>${m.ratio.toFixed(2)}x</td>
            <td>${escapeHtml(m.uploaded_fmt)}</td>
            <td>${escapeHtml((m.planned || []).join(', ') || 'Уведомление')}</td>
        </tr>
    `).join('');
}

async function checkOnboardingWizard() {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
    try {
        const res = await api('/api/onboarding/status');
        if (!res.ok) return;
        const d = await res.json();
        if (d.completed) return;
        document.getElementById('onb-qb-ip').value = d.detected_ip || '127.0.0.1';
        document.getElementById('onb-qb-port').value = d.detected_port || '8080';
        document.getElementById('onb-mbps').value = d.max_channel_mbps || 1000;
        const dSel = document.getElementById('onb-disk');
        if (dSel) {
            dSel.innerHTML = '<option value="">Авто (по максимуму раздач)</option>';
            (d.disks || []).forEach(dk => dSel.add(new Option(`${dk.path} (${dk.free_fmt} своб.)`, dk.path)));
        }
        document.getElementById('onb-probe-status').textContent = d.qb_api_ok
            ? `🟢 Найден qBittorrent ${d.qb_version} • BT_backup: ${d.bt_backup_ok ? 'OK' : 'проверьте права'}`
            : '🟡 qBittorrent не ответил на автопорту — укажите вручную или пропустите';
        _setOnbStep(1);
        document.getElementById('onboarding-modal').style.display = 'flex';
    } catch (e) {}
}

function _setOnbStep(n) {
    _onbStep = Math.max(1, Math.min(4, n));
    for (let i = 1; i <= 4; i++) document.getElementById(`onb-step-${i}`)?.classList.toggle('hidden', i !== _onbStep);
}

async function finishOnboarding(skipped = false) {
    const payload = skipped ? { skipped: true } : {
        qb_ip: document.getElementById('onb-qb-ip').value.trim(),
        qb_port: document.getElementById('onb-qb-port').value.trim(),
        qb_user: document.getElementById('onb-qb-user').value.trim(),
        qb_password: document.getElementById('onb-qb-pass').value,
        max_channel_mbps: parseInt(document.getElementById('onb-mbps').value) || 1000,
        monitored_disk: document.getElementById('onb-disk').value
    };
    await api('/api/onboarding/complete', 'POST', payload);
    document.getElementById('onboarding-modal').style.display = 'none';
    if (!skipped && typeof loadTorrents === 'function') loadTorrents(true);
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelector('[data-tab="tools"]')?.addEventListener('click', () => setTimeout(loadSafetyToolsTab, 50));
    setTimeout(checkOnboardingWizard, 1200);
});