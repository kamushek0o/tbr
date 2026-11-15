let currentRules = [];
let editingRuleId = null;

async function loadAutomation() {
    const res = await api('/api/automation');
    const d = await res.json();
    const s = d.settings || {};

    document.getElementById('auto-enabled').checked = Boolean(s.enabled);
    document.getElementById('auto-interval').value = s.interval || 5;
    document.getElementById('auto-tg-token').value = '';
    document.getElementById('auto-tg-token').placeholder = s.has_tg_token ? 'Токен задан (пусто = не менять)' : '123456:ABC-DEF...';
    document.getElementById('auto-tg-chat').value = s.tg_chat_id || '';
    document.getElementById('auto-discord').value = '';
    document.getElementById('auto-discord').placeholder = s.has_discord ? 'Webhook задан (пусто = не менять)' : 'https://discord.com/api/webhooks/...';

    currentRules = d.rules || [];
    renderRules(currentRules);
}

function renderRules(rules) {
    const tbody = document.getElementById('rules-tbody');
    tbody.innerHTML = '';
    if (!rules.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="center-msg">Правила пока не добавлены</td></tr>';
        return;
    }
    const frag = document.createDocumentFragment();
    rules.forEach(r => {
        const conds = [];
        if (r.min_ratio > 0) conds.push(`Ratio >= ${r.min_ratio}x`);
        if (r.min_seed_days > 0) conds.push(`Сид >= ${r.min_seed_days} дн.`);

        const acts = [];
        if (r.action_pause) acts.push('⏸️ Пауза');
        if (r.action_tag) acts.push(`🏷️ ${r.action_tag}`);
        if (r.notify) acts.push('📣 Бот');

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${escapeHtml(r.name)}</strong></td>
            <td>${escapeHtml(conds.join(' И '))}</td>
            <td>${escapeHtml(acts.join(', ') || '—')}</td>
            <td><span class="badge ${r.enabled ? 'badge-up' : 'badge-pause'}">${r.enabled ? 'Вкл' : 'Выкл'}</span></td>
            <td class="row-gap">
                <button class="btn btn-secondary btn-xs" title="Редактировать" onclick="editRule(${r.id})">✏️</button>
                <button class="btn btn-secondary btn-xs" onclick="toggleRule(${r.id})">${r.enabled ? 'Выкл' : 'Вкл'}</button>
                <button class="btn btn-danger btn-xs" title="Удалить" onclick="deleteRule(${r.id})">🗑️</button>
            </td>
        `;
        frag.appendChild(tr);
    });
    tbody.appendChild(frag);
}

function editRule(id) {
    const r = currentRules.find(x => x.id === id);
    if (!r) return;

    editingRuleId = id;
    document.getElementById('rule-name').value = r.name || '';
    document.getElementById('rule-ratio').value = r.min_ratio > 0 ? r.min_ratio : '';
    document.getElementById('rule-days').value = r.min_seed_days > 0 ? r.min_seed_days : '';
    document.getElementById('rule-tag').value = r.action_tag || '';
    document.getElementById('rule-pause').checked = Boolean(r.action_pause);
    document.getElementById('rule-notify').checked = Boolean(r.notify);

    const titleEl = document.getElementById('rule-form-title');
    const subBtn = document.getElementById('btn-rule-submit');
    const canBtn = document.getElementById('btn-rule-cancel');
    const cardEl = document.getElementById('rule-form-card');

    if (titleEl) titleEl.textContent = `✏️ РЕДАКТИРОВАНИЕ ПРАВИЛА #${id}`;
    if (subBtn) subBtn.textContent = '💾 Сохранить';
    if (canBtn) canBtn.classList.remove('hidden');
    if (cardEl) cardEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function cancelEditRule() {
    editingRuleId = null;
    document.getElementById('rule-name').value = '';
    document.getElementById('rule-ratio').value = '';
    document.getElementById('rule-days').value = '';
    document.getElementById('rule-tag').value = '';
    document.getElementById('rule-pause').checked = false;
    document.getElementById('rule-notify').checked = true;

    const titleEl = document.getElementById('rule-form-title');
    const subBtn = document.getElementById('btn-rule-submit');
    const canBtn = document.getElementById('btn-rule-cancel');

    if (titleEl) titleEl.textContent = '➕ ДОБАВИТЬ ПРАВИЛО';
    if (subBtn) subBtn.textContent = '➕ Добавить';
    if (canBtn) canBtn.classList.add('hidden');
}

async function saveAutomationSettings() {
    const payload = {
        enabled: document.getElementById('auto-enabled').checked,
        interval: parseInt(document.getElementById('auto-interval').value) || 5,
        tg_token: document.getElementById('auto-tg-token').value.trim(),
        tg_chat_id: document.getElementById('auto-tg-chat').value.trim(),
        discord_webhook: document.getElementById('auto-discord').value.trim()
    };
    const res = await api('/api/automation/settings', 'POST', payload);
    const d = await res.json();
    if (!res.ok) return alert(d.error || 'Ошибка сохранения');
    document.getElementById('auto-status-msg').textContent = d.message;
    loadAutomation();
}

async function testNotifications() {
    const msgEl = document.getElementById('auto-status-msg');
    msgEl.textContent = '⏳ Отправка теста...';
    const res = await api('/api/automation/test', 'POST');
    const d = await res.json();
    msgEl.textContent = d.message;
    if (!d.success) alert(d.message);
}

async function runAutomationNow() {
    const msgEl = document.getElementById('auto-status-msg');
    msgEl.textContent = '⏳ Проверка правил...';
    const res = await api('/api/automation/run_now', 'POST');
    const d = await res.json();
    msgEl.textContent = d.message;
}

async function submitAutomationRule() {
    const payload = {
        name: document.getElementById('rule-name').value.trim(),
        min_ratio: parseFloat(document.getElementById('rule-ratio').value) || 0,
        min_seed_days: parseFloat(document.getElementById('rule-days').value) || 0,
        action_tag: document.getElementById('rule-tag').value.trim(),
        action_pause: document.getElementById('rule-pause').checked,
        notify: document.getElementById('rule-notify').checked
    };

    let url = '/api/automation/rules';
    if (editingRuleId !== null) {
        url = '/api/automation/rules/update';
        payload.id = editingRuleId;
    }

    try {
        const res = await api(url, 'POST', payload);
        let d = {};
        try { d = await res.json(); } catch (_) {}
        if (!res.ok || d.success === false) {
            return alert(d.error || `Ошибка HTTP ${res.status} при сохранении правила`);
        }
        cancelEditRule();
        loadAutomation();
    } catch (e) {
        alert('Ошибка сети: ' + e.message);
    }
}

function addAutomationRule() {
    return submitAutomationRule();
}

async function toggleRule(id) {
    await api('/api/automation/rules/toggle', 'POST', { id });
    loadAutomation();
}

async function deleteRule(id) {
    if (!confirm('Удалить правило?')) return;
    if (editingRuleId === id) cancelEditRule();
    await api('/api/automation/rules/delete', 'POST', { id });
    loadAutomation();
}