// web/static/profiles.js
let CURRENT_ROLE = 'admin';
let CURRENT_UI_SETTINGS = null;

async function loadMeAndApplyRole() {
    try {
        const res = await api('/api/me');
        const d = await res.json();
        CURRENT_ROLE = d.role || 'viewer';
        CURRENT_UI_SETTINGS = d.ui_settings || null;
        if (typeof applyUiSettings === 'function' && d.ui_settings) {
            applyUiSettings(d.ui_settings);
        }
        if (CURRENT_ROLE === 'viewer') {
            document.querySelectorAll('[data-tab="merger"], [data-tab="automation"]').forEach(el => el.classList.add('hidden'));
            document.querySelectorAll('button[onclick*="openSettingsModal"], button[onclick*="restartQb"], button[onclick*="scanDeadTorrents"], button[onclick*="torrentAction"], button[onclick*="globalTorrentAction"]').forEach(el => el.classList.add('hidden'));
        }
    } catch (e) {}
}

async function loadProfilesList() {
    const box = document.getElementById('profiles-list');
    if (!box || CURRENT_ROLE !== 'admin') return;
    const res = await api('/api/profiles');
    if (!res.ok) return;
    const d = await res.json();
    box.innerHTML = '';
    (d.profiles || []).forEach(p => {
        const row = document.createElement('div');
        row.className = 'row-between mb-8';
        row.style.cssText = 'background:var(--bg-input); padding:5px 8px; border-radius:5px;';
        row.innerHTML = `
            <span><b>${escapeHtml(p.name)}</b> <span class="badge ${p.role === 'admin' ? 'badge-up' : 'badge-pause'}">${p.role}</span> <span class="muted-text">${escapeHtml(p.token_prefix)}</span></span>
            <span class="row-gap">
                <button class="btn btn-secondary btn-xs" title="Скопировать ссылку для входа" onclick="copyProfileLinkByHash('${escapeHtml(p.token_hash || '')}')">🔗</button>
                <button class="btn btn-secondary btn-xs" title="Сменить пароль" onclick="changeProfilePassword(${p.id}, '${escapeHtml(p.name)}')">🔑</button>
                <button class="btn btn-danger btn-xs" title="Удалить" onclick="deleteProfile(${p.id})">🗑️</button>
            </span>
        `;
        box.appendChild(row);
    });
}

function copyProfileLinkByHash(tokenHash) {
    if (!tokenHash) return alert('Хэш токена отсутствует.');
    const link = `${window.location.origin}/login?hash=${encodeURIComponent(tokenHash)}`;
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(link).then(() => {
            alert('Ссылка для входа в 1 клик скопирована в буфер обмена!\n\n' + link);
        }).catch(() => prompt('Ссылка для входа в 1 клик:', link));
    } else {
        prompt('Ссылка для входа в 1 клик:', link);
    }
}

async function changeProfilePassword(id, name) {
    const newPwd = prompt(`Смена пароля для "${name}":\n\nВведите новый пароль (или оставьте пустым для авто-токена):`);
    if (newPwd === null) return;
    const res = await api('/api/profiles/change_password', 'POST', { id, password: newPwd.trim() });
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка смены пароля');
    const link = `${window.location.origin}/login?hash=${encodeURIComponent(d.hash)}`;
    prompt(`Пароль успешно обновлён!\nНовый токен: ${d.token}\n\nМагическая ссылка для входа по хэшу:`, link);
    loadProfilesList();
}

async function createProfile() {
    const name = document.getElementById('new-profile-name').value.trim();
    const token = document.getElementById('new-profile-token').value.trim();
    const role = document.getElementById('new-profile-role').value;
    const res = await api('/api/profiles/create', 'POST', { name, role, token });
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка');
    document.getElementById('new-profile-name').value = '';
    document.getElementById('new-profile-token').value = '';
    const link = `${window.location.origin}/login?hash=${encodeURIComponent(d.hash)}`;
    prompt(`Готово! Пароль/токен: ${d.token}\n\nМагическая ссылка для входа по хэшу:`, link);
    loadProfilesList();
}

async function deleteProfile(id) {
    if (!confirm('Удалить профиль?')) return;
    const res = await api('/api/profiles/delete', 'POST', { id });
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка');
    loadProfilesList();
}