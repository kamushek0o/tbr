// web/static/profiles.js
let CURRENT_ROLE = 'admin';
let CURRENT_UI_SETTINGS = null;
let _qrActiveProfile = null;

async function loadMeAndApplyRole() {
    try {
        const res = await api('/api/me');
        const d = await res.json();
        CURRENT_ROLE = d.role || 'viewer';
        CURRENT_UI_SETTINGS = d.ui_settings || null;
        if (typeof applyUiSettings === 'function' && d.ui_settings) applyUiSettings(d.ui_settings);
        if (CURRENT_ROLE === 'viewer') {
            document.querySelectorAll('[data-tab="merger"], [data-tab="automation"]').forEach(el => el.classList.add('hidden'));
            document.querySelectorAll('button[onclick*="openSettingsModal"], button[onclick*="restartQb"], button[onclick*="scanDeadTorrents"], button[onclick*="torrentAction"], button[onclick*="globalTorrentAction"]').forEach(el => el.classList.add('hidden'));
        }
    } catch (e) {}
}

async function changeSelfPassword() {
    const pwd = prompt('Введите новый пароль для вашего профиля (мин. 3 символа):');
    if (pwd === null) return;
    const res = await api('/api/profile/password', 'POST', { password: pwd.trim() });
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка смены пароля');
    alert('✅ Пароль успешно обновлён!');
}

async function loadProfilesList() {
    const box = document.getElementById('profiles-list');
    if (!box || CURRENT_ROLE !== 'admin') return;
    loadQrHosts();
    const res = await api('/api/profiles');
    if (!res.ok) return;
    const d = await res.json();
    box.innerHTML = '';
    (d.profiles || []).forEach(p => {
        const row = document.createElement('div');
        row.className = 'row-between mb-8';
        row.style.cssText = 'background:var(--bg-input); padding:5px 8px; border-radius:5px;';
        row.innerHTML = `
            <span><b>${escapeHtml(p.name)}</b> <span class="muted-text">(@${escapeHtml(p.login || '')})</span> <span class="badge ${p.role === 'admin' ? 'badge-up' : 'badge-pause'}">${p.role}</span></span>
            <span class="row-gap" style="gap:4px;">
                <button class="btn btn-secondary btn-xs" title="Одноразовый инвайт" onclick="createInviteLink(${p.id}, '${escapeHtml(p.name)}')">✉️</button>
                <button class="btn btn-secondary btn-xs" title="QR-код подключения" onclick="openQrForProfile('${escapeHtml(p.api_token || '')}', '${escapeHtml(p.name)}', '${p.role}')">📱</button>
                <button class="btn btn-secondary btn-xs" title="Скопировать API-токен" onclick="copyTextPrompt('API-токен для ${escapeHtml(p.name)}:', '${escapeHtml(p.api_token || '')}')">📋</button>
                <button class="btn btn-secondary btn-xs" title="Перевыпустить API-токен" onclick="reissueApiToken(${p.id})">🔄</button>
                <button class="btn btn-secondary btn-xs" title="Сменить пароль" onclick="changeProfilePassword(${p.id}, '${escapeHtml(p.name)}')">🔑</button>
                <button class="btn btn-danger btn-xs" title="Удалить" onclick="deleteProfile(${p.id})">🗑️</button>
            </span>
        `;
        box.appendChild(row);
    });
}

function copyTextPrompt(label, val) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(val).then(() => alert(`${label}\n\n${val}`)).catch(() => prompt(label, val));
    } else {
        prompt(label, val);
    }
}

async function createInviteLink(id, name) {
    const res = await api('/api/profiles/invite', 'POST', { id });
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка создания инвайта');
    const link = `${window.location.origin}/invite/${encodeURIComponent(d.invite_token)}`;
    copyTextPrompt(`Одноразовый инвайт для "${name}" (сгорит после 1-го входа):`, link);
}

async function reissueApiToken(id) {
    if (!confirm('Перевыпустить API-токен? Старый перестанет работать в виджете и скриптах.')) return;
    const res = await api('/api/profiles/reissue_api', 'POST', { id });
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка');
    copyTextPrompt('Новый API-токен:', d.api_token);
    loadProfilesList();
}

async function changeProfilePassword(id, name) {
    const newPwd = prompt(`Новый пароль для "${name}" (или пусто для авто):`);
    if (newPwd === null) return;
    const res = await api('/api/profiles/change_password', 'POST', { id, password: newPwd.trim() });
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка смены пароля');
    prompt('Пароль обновлён! Новый пароль:', d.password);
    loadProfilesList();
}

async function createProfile() {
    const name = document.getElementById('new-profile-name').value.trim();
    const login = document.getElementById('new-profile-login').value.trim();
    const password = document.getElementById('new-profile-token').value.trim();
    const role = document.getElementById('new-profile-role').value;
    const res = await api('/api/profiles/create', 'POST', { name, login, password, role });
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка');
    document.getElementById('new-profile-name').value = '';
    document.getElementById('new-profile-login').value = '';
    document.getElementById('new-profile-token').value = '';
    prompt(`Профиль создан!\nПароль: ${d.password}\nAPI-токен:`, d.api_token);
    loadProfilesList();
}

async function deleteProfile(id) {
    if (!confirm('Удалить профиль?')) return;
    const res = await api('/api/profiles/delete', 'POST', { id });
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка');
    loadProfilesList();
}

async function loadQrHosts() {
    const sel = document.getElementById('qr-host-select');
    if (!sel) return;
    const port = window.location.port || (window.location.protocol === 'https:' ? '' : '5000');
    const opts = [];
    if (window.location.hostname && !['localhost', '127.0.0.1'].includes(window.location.hostname)) {
        opts.push(window.location.origin);
    }
    try {
        const res = await api('/api/network/hosts');
        if (res.ok) {
            const d = await res.json();
            (d.ips || []).forEach(ip => {
                const u = `http://${ip}${port ? ':' + port : ''}`;
                if (!opts.includes(u)) opts.push(u);
            });
        }
    } catch (e) {}
    sel.innerHTML = '';
    opts.forEach(u => {
        const o = document.createElement('option');
        o.value = u; o.textContent = u;
        sel.appendChild(o);
    });
}

function openQrForProfile(apiToken, name, role) {
    _qrActiveProfile = { apiToken, name, role };
    document.getElementById('qr-title').textContent = `📱 QR-код: ${name}`;
    document.getElementById('qr-panel').classList.remove('hidden');
    refreshActiveQr();
}

function refreshActiveQr() {
    if (!_qrActiveProfile || typeof qrcode === 'undefined') return;
    const custom = document.getElementById('qr-custom-url').value.trim().replace(/\/+$/, '');
    const selected = document.getElementById('qr-host-select').value;
    const baseUrl = custom || selected || window.location.origin;
    const mode = document.getElementById('qr-mode-select').value;

    document.getElementById('qr-admin-warn').classList.toggle('hidden', !(mode === 'widget' && _qrActiveProfile.role === 'admin'));
    const payload = mode === 'widget' ? JSON.stringify({ url: baseUrl, token: _qrActiveProfile.apiToken }) : baseUrl;

    const qr = qrcode(0, 'M');
    qr.addData(payload);
    qr.make();
    document.getElementById('qr-preview-box').innerHTML = qr.createSvgTag(4, 2);
}