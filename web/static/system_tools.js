// web/static/system_tools.js
let _cachedUpdateInfo = null;
let _panicHoldTimer = null;
let _panicHoldTriggered = false;

async function initSystemStatusAndUpdates() {
    try {
        const res = await api('/api/version');
        if (res.ok) {
            const d = await res.json();
            const freezeBadge = document.getElementById('autopilot-freeze-badge');
            if (freezeBadge) {
                const frozen = (d.autopilot_frozen_until || 0) > Math.floor(Date.now() / 1000);
                freezeBadge.classList.toggle('hidden', !frozen);
            }
        }
    } catch (e) {}

    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE === 'admin') {
        checkAppUpdates(false);
    }
    _bindPanicTouchHold();
}

async function checkAppUpdates(force = false) {
    try {
        const res = await api(`/api/update/check?force=${force ? '1' : '0'}`);
        if (!res.ok) return null;
        const d = await res.json();
        _cachedUpdateInfo = d;
        const badge = document.getElementById('update-available-badge');
        if (badge) {
            badge.classList.toggle('hidden', !d.update_available);
            if (d.update_available) {
                badge.textContent = `⬆️ Доступно v${d.latest_version}`;
            }
        }
        return d;
    } catch (e) {
        return null;
    }
}

async function openUpdateModal(force = true) {
    const modal = document.getElementById('update-modal');
    const statusEl = document.getElementById('upd-status-text');
    const logEl = document.getElementById('upd-changelog-box');
    const applyBtn = document.getElementById('btn-apply-update');
    const dockerHint = document.getElementById('upd-docker-hint');
    const verBadge = document.getElementById('upd-ver-badge');
    const ghLink = document.getElementById('upd-github-link');

    modal.style.display = 'flex';
    statusEl.textContent = 'Проверяем GitHub Releases...';
    logEl.textContent = 'Загрузка...';
    applyBtn.classList.add('hidden');
    dockerHint.classList.add('hidden');

    const d = (force || !_cachedUpdateInfo) ? await checkAppUpdates(true) : _cachedUpdateInfo;
    if (!d || !d.success) {
        statusEl.textContent = `⚠️ Не удалось проверить обновления: ${d?.error || 'ошибка сети'}`;
        logEl.textContent = 'Проверьте подключение к интернету.';
        return;
    }

    if (ghLink && d.html_url) ghLink.href = d.html_url;
    if (verBadge) verBadge.textContent = `v${d.current_version} → v${d.latest_version}`;

    if (d.update_available) {
        statusEl.textContent = `🔥 Доступна новая версия v${d.latest_version} (${d.release_name || ''})`;
        if (d.can_auto_update) applyBtn.classList.remove('hidden');
        else dockerHint.classList.remove('hidden');
    } else {
        statusEl.textContent = `✅ У вас установлена актуальная версия v${d.current_version}`;
    }
    logEl.textContent = d.changelog || 'Описание релиза отсутствует.';
}

function closeUpdateModal() {
    document.getElementById('update-modal').style.display = 'none';
}

async function applyAppUpdate() {
    const btn = document.getElementById('btn-apply-update');
    const statusEl = document.getElementById('upd-status-text');
    btn.disabled = true;
    statusEl.textContent = '⏳ Скачивание tbr_new.exe и проверка SHA-256...';
    try {
        const res = await api('/api/update/apply', 'POST');
        const d = await res.json();
        if (!res.ok || !d.success) {
            statusEl.textContent = `❌ ${d.message || d.error || 'Ошибка обновления'}`;
            btn.disabled = false;
            return;
        }
        statusEl.textContent = `🚀 ${d.message} Ожидаем перезапуск сервера...`;
        const poll = setInterval(async () => {
            try {
                const r = await fetch('/api/version');
                if (r.ok) {
                    clearInterval(poll);
                    window.location.reload();
                }
            } catch (e) {}
        }, 2000);
    } catch (e) {
        statusEl.textContent = `❌ Ошибка: ${e.message}`;
        btn.disabled = false;
    }
}

function _bindPanicTouchHold() {
    const btn = document.getElementById('btn-panic-killswitch');
    if (!btn) return;
    btn.addEventListener('touchstart', () => {
        _panicHoldTriggered = false;
        btn.classList.add('holding');
        _panicHoldTimer = setTimeout(() => {
            _panicHoldTriggered = true;
            btn.classList.remove('holding');
            openPanicModal();
        }, 2000);
    }, { passive: true });
    const cancel = () => {
        if (_panicHoldTimer) clearTimeout(_panicHoldTimer);
        btn.classList.remove('holding');
    };
    btn.addEventListener('touchend', cancel);
    btn.addEventListener('touchcancel', cancel);
}

function onPanicBtnClick() {
    if (_panicHoldTriggered) {
        _panicHoldTriggered = false;
        return;
    }
    openPanicModal();
}

function openPanicModal() {
    document.getElementById('panic-kill-qb').checked = false;
    document.getElementById('panic-modal').style.display = 'flex';
}

function closePanicModal() {
    document.getElementById('panic-modal').style.display = 'none';
}

async function confirmPanicKillswitch() {
    const killQb = document.getElementById('panic-kill-qb').checked;
    const res = await api('/api/panic', 'POST', { kill_qb: killQb });
    const d = await res.json();
    closePanicModal();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка активации Panic Killswitch');
    alert('🚨 PANIC KILLSWITCH:\n' + (d.details || []).join('\n'));
    initSystemStatusAndUpdates();
    if (typeof loadTorrents === 'function') loadTorrents(true);
}

async function loadToolsTab() {
    if (typeof loadAchievements === 'function') loadAchievements();
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
    if (typeof loadAuditLog === 'function') loadAuditLog();

    const listBox = document.getElementById('tools-manifest-list');
    const weeklyChk = document.getElementById('tools-manifest-weekly');
    if (!listBox) return;
    try {
        const res = await api('/api/manifest/list');
        if (!res.ok) return;
        const d = await res.json();
        if (weeklyChk) weeklyChk.checked = Boolean(d.weekly);
        const files = d.manifests || [];
        if (!files.length) {
            listBox.innerHTML = '<span class="muted-text">Копий пока нет. Нажмите «Выгрузить сейчас».</span>';
            return;
        }
        listBox.innerHTML = files.map(f => `
            <div class="row-between" style="background:var(--bg-input); padding:6px 8px; border-radius:6px;">
                <span>📄 <b>${escapeHtml(f.filename)}</b> <span class="muted-text">(${escapeHtml(f.size_fmt)}, ${escapeHtml(f.date)})</span></span>
                <a class="btn btn-secondary btn-xs" href="/api/manifest/download?file=${encodeURIComponent(f.filename)}">⬇️ Скачать</a>
            </div>
        `).join('');
    } catch (e) {}
}

async function createManifestNow() {
    const res = await api('/api/manifest/create', 'POST');
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка создания манифеста');
    loadToolsTab();
}

async function toggleManifestWeeklyFromTools() {
    const chk = document.getElementById('tools-manifest-weekly');
    const res = await api('/api/manifest/weekly', 'POST', { weekly: Boolean(chk?.checked) });
    if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        alert(d.error || 'Ошибка сохранения');
    }
}