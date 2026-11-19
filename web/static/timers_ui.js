// web/static/timers_ui.js
let _snoozeRemainSec = 0;
let _snoozeTickInt = null;

async function initTimersUi() {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
    await Promise.all([refreshFreezeBadge(), refreshSnoozeBadge()]);
    setInterval(() => {
        if (!document.hidden && CURRENT_ROLE === 'admin') {
            refreshFreezeBadge();
            refreshSnoozeBadge();
        }
    }, 15000);
}

async function refreshFreezeBadge() {
    const btn = document.getElementById('btn-smart-freeze');
    if (!btn) return;
    try {
        const res = await api('/api/freeze/status');
        if (!res.ok) return;
        const d = await res.json();
        btn.textContent = d.frozen ? `▶️ Разморозить (${d.count})` : '❄️ Заморозка';
        btn.className = d.frozen ? 'btn admin-only' : 'btn btn-secondary admin-only';
    } catch (e) {}
}

async function toggleSmartFreeze() {
    const res = await api('/api/freeze/toggle', 'POST');
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || d.message || 'Ошибка');
    alert(d.message);
    refreshFreezeBadge();
    if (typeof loadTorrents === 'function') loadTorrents(true);
}

function _fmtCountdown(sec) {
    const s = Math.max(0, parseInt(sec) || 0);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const r = s % 60;
    return h > 0
        ? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
        : `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
}

function _renderSnoozeButtons() {
    const btn = document.getElementById('btn-snooze-timer');
    const box = document.getElementById('snooze-active-box');
    const cd = document.getElementById('snooze-modal-countdown');
    if (_snoozeRemainSec > 0) {
        const str = _fmtCountdown(_snoozeRemainSec);
        if (btn) { btn.textContent = `⏰ ${str}`; btn.className = 'btn admin-only'; }
        if (box) box.classList.remove('hidden');
        if (cd) cd.textContent = str;
    } else {
        if (btn) { btn.textContent = '😴 Сон'; btn.className = 'btn btn-secondary admin-only'; }
        if (box) box.classList.add('hidden');
    }
}

async function refreshSnoozeBadge() {
    try {
        const res = await api('/api/snooze/status');
        if (!res.ok) return;
        const d = await res.json();
        _snoozeRemainSec = d.active ? (d.remaining_sec || 0) : 0;
        _renderSnoozeButtons();
        if (_snoozeTickInt) clearInterval(_snoozeTickInt);
        if (_snoozeRemainSec > 0) {
            _snoozeTickInt = setInterval(() => {
                _snoozeRemainSec = Math.max(0, _snoozeRemainSec - 1);
                _renderSnoozeButtons();
                if (_snoozeRemainSec <= 0) {
                    clearInterval(_snoozeTickInt);
                    refreshFreezeBadge();
                }
            }, 1000);
        }
    } catch (e) {}
}

function openSnoozeModal() {
    refreshSnoozeBadge();
    document.getElementById('snooze-modal').style.display = 'flex';
}
function closeSnoozeModal() { document.getElementById('snooze-modal').style.display = 'none'; }

async function startSnoozeQuick(minutes) {
    const mode = document.getElementById('snooze-mode')?.value || 'pause';
    const res = await api('/api/snooze/start', 'POST', { minutes, mode });
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || d.message || 'Ошибка');
    closeSnoozeModal();
    refreshSnoozeBadge();
    refreshFreezeBadge();
    if (typeof loadTorrents === 'function') loadTorrents(true);
}

function startSnoozeCustom() {
    const mins = parseInt(document.getElementById('snooze-custom-min')?.value) || 0;
    if (mins < 1 || mins > 1440) return alert('Укажите от 1 до 1440 минут');
    startSnoozeQuick(mins);
}

async function cancelSnoozeTimer() {
    const res = await api('/api/snooze/cancel', 'POST');
    const d = await res.json();
    if (d.success) {
        _snoozeRemainSec = 0;
        _renderSnoozeButtons();
        refreshFreezeBadge();
        if (typeof loadTorrents === 'function') loadTorrents(true);
    }
}

async function openExpirationModal() {
    if (typeof selectedHash === 'undefined' || !selectedHash) return alert(t('err_select_torrent'));
    const item = (typeof torrentsData !== 'undefined' ? torrentsData : []).find(x => x.hash === selectedHash);
    document.getElementById('exp-torrent-name').textContent = item ? item.name : selectedHash;
    document.getElementById('exp-time-val').value = '';
    document.getElementById('exp-target-gib').value = '';
    document.getElementById('exp-delete-files').checked = false;
    const remBtn = document.getElementById('btn-exp-remove');
    remBtn.classList.add('hidden');

    try {
        const res = await api('/api/expirations');
        if (res.ok) {
            const d = await res.json();
            const ex = (d.items || []).find(r => r.hash_id.toLowerCase() === selectedHash.toLowerCase());
            if (ex) {
                remBtn.classList.remove('hidden');
                if (ex.expires_at) {
                    const leftH = Math.max(0.5, (ex.expires_at - Date.now() / 1000) / 3600).toFixed(1);
                    document.getElementById('exp-time-val').value = leftH;
                    document.getElementById('exp-time-unit').value = 'hours';
                }
                if (ex.target_uploaded) {
                    document.getElementById('exp-target-gib').value = Math.round(ex.target_uploaded / (1024 ** 3));
                }
                document.getElementById('exp-delete-files').checked = Boolean(ex.delete_files);
            }
        }
    } catch (e) {}
    document.getElementById('expiration-modal').style.display = 'flex';
}
function closeExpirationModal() { document.getElementById('expiration-modal').style.display = 'none'; }

async function saveExpirationForSelected() {
    const val = parseFloat(document.getElementById('exp-time-val').value) || 0;
    const unit = document.getElementById('exp-time-unit').value;
    const hours = unit === 'days' ? val * 24 : val;
    const gib = parseFloat(document.getElementById('exp-target-gib').value) || 0;
    const delFiles = document.getElementById('exp-delete-files').checked;

    if (delFiles && !confirm('⚠️ Подтвердите: по истечении срока файлы раздачи будут УДАЛЕНЫ С ДИСКА!')) return;

    const res = await api('/api/expirations/set', 'POST', {
        hash: selectedHash, hours, target_uploaded_bytes: gib > 0 ? Math.round(gib * (1024 ** 3)) : 0, delete_files: delFiles
    });
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || d.message || 'Ошибка');
    closeExpirationModal();
    alert('✅ ' + d.message);
}

async function removeExpirationForSelected() {
    const res = await api('/api/expirations/delete', 'POST', { hash: selectedHash });
    if (res.ok) { closeExpirationModal(); alert('Таймер снят.'); }
}

async function loadDndDigestAndTagging() {
    try {
        const [schRes, tagRes] = await Promise.all([api('/api/notifications/schedule'), api('/api/tagging/rules')]);
        if (schRes.ok) {
            const s = await schRes.json();
            const dnd = s.dnd || {}, dig = s.digest || {};
            const en = document.getElementById('dnd-enabled');
            if (en) en.checked = Boolean(dnd.enabled);
            if (document.getElementById('dnd-start')) document.getElementById('dnd-start').value = dnd.start || '23:00';
            if (document.getElementById('dnd-end')) document.getElementById('dnd-end').value = dnd.end || '08:00';
            document.querySelectorAll('.dnd-day-chk').forEach(chk => {
                chk.checked = (dnd.days || []).includes(parseInt(chk.value));
            });
            if (document.getElementById('digest-mode')) document.getElementById('digest-mode').value = dig.mode || 'off';
            if (document.getElementById('digest-hour')) document.getElementById('digest-hour').value = dig.hour ?? 21;
            if (document.getElementById('digest-weekday')) document.getElementById('digest-weekday').value = dig.weekday ?? 6;
        }
        if (tagRes.ok) renderTaggingRules((await tagRes.json()).rules || []);
    } catch (e) {}
}

function renderTaggingRules(rules) {
    const tbody = document.getElementById('tagging-rules-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    if (!rules.length) { tbody.innerHTML = '<tr><td colspan="5" class="center-msg">Правил тегирования нет</td></tr>'; return; }
    rules.forEach(r => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><b>${escapeHtml(r.name)}</b></td>
            <td>${r.match_field === 'tracker' ? '🌐 Трекер' : '📁 Путь'} содержит <code>${escapeHtml(r.pattern)}</code></td>
            <td><span class="badge badge-up">+${escapeHtml(r.target_tag)}</span></td>
            <td><span class="badge ${r.enabled ? 'badge-up' : 'badge-pause'}">${r.enabled ? 'Вкл' : 'Выкл'}</span></td>
            <td class="row-gap">
                <button class="btn btn-secondary btn-xs" onclick="toggleTaggingRule(${r.id})">${r.enabled ? 'Выкл' : 'Вкл'}</button>
                <button class="btn btn-danger btn-xs" onclick="deleteTaggingRule(${r.id})">🗑️</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

async function saveDndDigestSchedule() {
    const days = [...document.querySelectorAll('.dnd-day-chk:checked')].map(c => parseInt(c.value));
    const payload = {
        dnd: {
            enabled: document.getElementById('dnd-enabled')?.checked || false,
            start: document.getElementById('dnd-start')?.value || '23:00',
            end: document.getElementById('dnd-end')?.value || '08:00',
            days
        },
        digest: {
            mode: document.getElementById('digest-mode')?.value || 'off',
            hour: parseInt(document.getElementById('digest-hour')?.value) || 21,
            weekday: parseInt(document.getElementById('digest-weekday')?.value) ?? 6
        }
    };
    const res = await api('/api/notifications/schedule', 'POST', payload);
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка');
    document.getElementById('auto-status-msg').textContent = d.message;
}

async function addTaggingRule() {
    const payload = {
        name: document.getElementById('tag-rule-name').value.trim(),
        match_field: document.getElementById('tag-rule-field').value,
        pattern: document.getElementById('tag-rule-pattern').value.trim(),
        target_tag: document.getElementById('tag-rule-target').value.trim()
    };
    const res = await api('/api/tagging/rules/add', 'POST', payload);
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка');
    document.getElementById('tag-rule-name').value = '';
    document.getElementById('tag-rule-pattern').value = '';
    document.getElementById('tag-rule-target').value = '';
    loadDndDigestAndTagging();
}

async function toggleTaggingRule(id) {
    await api('/api/tagging/rules/toggle', 'POST', { id });
    loadDndDigestAndTagging();
}
async function deleteTaggingRule(id) {
    if (!confirm('Удалить правило тегирования?')) return;
    await api('/api/tagging/rules/delete', 'POST', { id });
    loadDndDigestAndTagging();
}