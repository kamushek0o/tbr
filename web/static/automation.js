// web/static/automation.js
let currentRules = [];
let editingRuleId = null;

function openBotGuide(type) {
    const modal = document.getElementById('bot-guide-modal');
    const title = document.getElementById('bot-guide-title');
    const body = document.getElementById('bot-guide-body');
    const isEn = (typeof currentLang !== 'undefined' && currentLang === 'en');

    if (type === 'tg') {
        title.textContent = isEn ? '📱 How to set up Telegram Bot' : '📱 Как подключить Telegram-бота';
        body.innerHTML = isEn ? `
            <ol style="padding-left:18px; line-height:1.6;">
                <li>Open <b>@BotFather</b> in Telegram, send <code>/newbot</code>, choose a name and copy the <b>Bot Token</b>.</li>
                <li>Open your new bot and press <b>Start</b> (or send any message).</li>
                <li>Open <b>@userinfobot</b> (or <b>@getmyid_bot</b>) to get your numeric <b>Chat ID</b>.</li>
                <li>Paste Token &amp; Chat ID here, click <b>Save</b> and press <b>Test</b>.</li>
            </ol>
        ` : `
            <ol style="padding-left:18px; line-height:1.6;">
                <li>Найди в Telegram <b>@BotFather</b>, отправь <code>/newbot</code>, задай имя и скопируй <b>Bot Token</b>.</li>
                <li>Зайди в своего нового бота и нажми <b>Запустить (Start)</b>.</li>
                <li>Напиши боту <b>@userinfobot</b> (или <b>@getmyid_bot</b>), чтобы узнать свой цифровой <b>Chat ID</b>.</li>
                <li>Вставь Token и Chat ID сюда, нажми <b>Сохранить</b> и проверь кнопкой <b>Тест</b>.</li>
            </ol>
        `;
    } else {
        title.textContent = isEn ? '💬 How to create a Discord Webhook' : '💬 Как создать Discord Webhook';
        body.innerHTML = isEn ? `
            <ol style="padding-left:18px; line-height:1.6;">
                <li>Open your Discord server → <b>Channel Settings</b> (gear icon on any text channel).</li>
                <li>Go to <b>Integrations</b> → <b>Webhooks</b> → <b>New Webhook</b>.</li>
                <li>Click <b>Copy Webhook URL</b>.</li>
                <li>Paste the URL here, click <b>Save</b> and press <b>Test</b>.</li>
            </ol>
        ` : `
            <ol style="padding-left:18px; line-height:1.6;">
                <li>Открой свой сервер Discord → <b>Настройки канала</b> (шестерёнка рядом с нужным каналом).</li>
                <li>Перейди в <b>Интеграции</b> → <b>Вебхуки</b> → <b>Новый вебхук</b>.</li>
                <li>Нажми <b>Копировать URL вебхука</b>.</li>
                <li>Вставь ссылку сюда, нажми <b>Сохранить</b> и проверь кнопкой <b>Тест</b>.</li>
            </ol>
        `;
    }
    modal.style.display = 'flex';
}

function closeBotGuide() {
    document.getElementById('bot-guide-modal').style.display = 'none';
}

async function loadAutomation() {
    const res = await api('/api/automation');
    const d = await res.json();
    const s = d.settings || {};

    document.getElementById('auto-enabled').checked = Boolean(s.enabled);
    document.getElementById('auto-interval').value = s.interval || 5;
    document.getElementById('auto-tg-token').value = '';
    document.getElementById('auto-tg-token').placeholder = s.has_tg_token ? t('token_set_ph') : '123456:ABC-DEF...';
    document.getElementById('auto-tg-chat').value = s.tg_chat_id || '';
    document.getElementById('auto-discord').value = '';
    document.getElementById('auto-discord').placeholder = s.has_discord ? t('webhook_set_ph') : 'https://discord.com/api/webhooks/...';

    const diskInp = document.getElementById('auto-alert-disk');
    if (diskInp) diskInp.value = s.alert_disk_gib || '';
    const qbChk = document.getElementById('auto-alert-qb');
    if (qbChk) qbChk.checked = Boolean(s.alert_qb_down);

    currentRules = d.rules || [];
    renderRules(currentRules);
}

function _fmtBytesBinary(b) {
    if (!b || b <= 0) return '';
    if (b >= 1024 ** 4) return `${(b / (1024 ** 4)).toFixed(2).replace(/\.00$/, '')} TiB`;
    if (b >= 1024 ** 3) return `${(b / (1024 ** 3)).toFixed(2).replace(/\.00$/, '')} GiB`;
    return `${(b / (1024 ** 2)).toFixed(2).replace(/\.00$/, '')} MiB`;
}

function _fmtSpeedBinary(bps) {
    if (!bps || bps <= 0) return '';
    if (bps >= 1024 ** 2) return `${(bps / (1024 ** 2)).toFixed(2).replace(/\.00$/, '')} MiB/s`;
    return `${(bps / 1024).toFixed(1).replace(/\.0$/, '')} KiB/s`;
}

function renderRules(rules) {
    const tbody = document.getElementById('rules-tbody');
    tbody.innerHTML = '';
    if (!rules.length) {
        tbody.innerHTML = `<tr><td colspan="5" class="center-msg">${t('no_rules')}</td></tr>`;
        return;
    }
    const isEn = (typeof currentLang !== 'undefined' && currentLang === 'en');
    const frag = document.createDocumentFragment();
    rules.forEach(r => {
        const conds = [];
        if (r.min_ratio > 0) conds.push(`Ratio >= ${r.min_ratio}x`);
        if (r.min_seed_days > 0) {
            const tmLbl = r.time_mode === 'time_active' ? (isEn ? 'Active' : 'Актив') : (isEn ? 'Seed' : 'Сид');
            conds.push(`${tmLbl} >= ${r.min_seed_days} ${t('rule_days_unit')}`);
        }
        if (r.min_uploaded_bytes > 0) conds.push(`${isEn ? 'Up' : 'Отдано'} >= ${_fmtBytesBinary(r.min_uploaded_bytes)}`);
        if (r.speed_op && r.speed_bytes > 0) {
            conds.push(`${isEn ? 'AvgSpd' : 'СрСкор'} ${r.speed_op} ${_fmtSpeedBinary(r.speed_bytes)} (${r.speed_window_min || 60}m)`);
        }

        const acts = [];
        if (r.action_pause) acts.push(t('chk_pause'));
        if (r.action_tag) acts.push(`🏷️ +${r.action_tag}`);
        if (r.action_remove_tag) acts.push(`✂️ -${r.action_remove_tag}`);
        if (r.notify) acts.push(t('rule_bot'));

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${escapeHtml(r.name)}</strong></td>
            <td style="white-space:normal;">${escapeHtml(conds.join(t('rule_and')))}</td>
            <td style="white-space:normal;">${escapeHtml(acts.join(', ') || '—')}</td>
            <td><span class="badge ${r.enabled ? 'badge-up' : 'badge-pause'}">${r.enabled ? t('rule_on') : t('rule_off')}</span></td>
            <td class="row-gap">
                <button class="btn btn-secondary btn-xs" onclick="editRule(${r.id})">✏️</button>
                <button class="btn btn-secondary btn-xs" onclick="toggleRule(${r.id})">${r.enabled ? t('rule_off') : t('rule_on')}</button>
                <button class="btn btn-danger btn-xs" onclick="deleteRule(${r.id})">🗑️</button>
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
    document.getElementById('rule-time-mode').value = r.time_mode || 'seeding_time';
    document.getElementById('rule-ratio').value = r.min_ratio > 0 ? r.min_ratio : '';
    document.getElementById('rule-days').value = r.min_seed_days > 0 ? r.min_seed_days : '';

    const upBytes = r.min_uploaded_bytes || 0;
    if (upBytes >= 1024 ** 4) {
        document.getElementById('rule-up-val').value = +(upBytes / (1024 ** 4)).toFixed(3);
        document.getElementById('rule-up-unit').value = 'TiB';
    } else if (upBytes >= 1024 ** 3) {
        document.getElementById('rule-up-val').value = +(upBytes / (1024 ** 3)).toFixed(3);
        document.getElementById('rule-up-unit').value = 'GiB';
    } else if (upBytes > 0) {
        document.getElementById('rule-up-val').value = +(upBytes / (1024 ** 2)).toFixed(2);
        document.getElementById('rule-up-unit').value = 'MiB';
    } else {
        document.getElementById('rule-up-val').value = '';
        document.getElementById('rule-up-unit').value = 'GiB';
    }

    document.getElementById('rule-speed-op').value = r.speed_op || '';
    const spBytes = r.speed_bytes || 0;
    if (spBytes >= 1024 ** 2) {
        document.getElementById('rule-speed-val').value = +(spBytes / (1024 ** 2)).toFixed(3);
        document.getElementById('rule-speed-unit').value = 'MiB';
    } else if (spBytes > 0) {
        document.getElementById('rule-speed-val').value = +(spBytes / 1024).toFixed(2);
        document.getElementById('rule-speed-unit').value = 'KiB';
    } else {
        document.getElementById('rule-speed-val').value = '';
        document.getElementById('rule-speed-unit').value = 'KiB';
    }
    document.getElementById('rule-speed-win').value = r.speed_window_min || 60;

    document.getElementById('rule-tag').value = r.action_tag || '';
    document.getElementById('rule-remove-tag').value = r.action_remove_tag || '';
    document.getElementById('rule-pause').checked = Boolean(r.action_pause);
    document.getElementById('rule-notify').checked = Boolean(r.notify);

    document.getElementById('rule-form-title').textContent = t('card_edit_rule', { id });
    document.getElementById('btn-rule-submit').textContent = t('btn_save');
    document.getElementById('btn-rule-cancel').classList.remove('hidden');
    document.getElementById('rule-form-card').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function cancelEditRule() {
    editingRuleId = null;
    document.getElementById('rule-name').value = '';
    document.getElementById('rule-time-mode').value = 'seeding_time';
    document.getElementById('rule-ratio').value = '';
    document.getElementById('rule-days').value = '';
    document.getElementById('rule-up-val').value = '';
    document.getElementById('rule-up-unit').value = 'GiB';
    document.getElementById('rule-speed-op').value = '';
    document.getElementById('rule-speed-val').value = '';
    document.getElementById('rule-speed-unit').value = 'KiB';
    document.getElementById('rule-speed-win').value = 60;
    document.getElementById('rule-tag').value = '';
    document.getElementById('rule-remove-tag').value = '';
    document.getElementById('rule-pause').checked = false;
    document.getElementById('rule-notify').checked = true;

    document.getElementById('rule-form-title').textContent = t('card_add_rule');
    document.getElementById('btn-rule-submit').textContent = t('btn_add');
    document.getElementById('btn-rule-cancel').classList.add('hidden');
}

async function saveAutomationSettings() {
    const payload = {
        enabled: document.getElementById('auto-enabled').checked,
        interval: parseInt(document.getElementById('auto-interval').value) || 5,
        alert_disk_gib: parseInt(document.getElementById('auto-alert-disk')?.value || 0) || 0,
        alert_qb_down: document.getElementById('auto-alert-qb')?.checked || false,
        tg_token: document.getElementById('auto-tg-token').value.trim(),
        tg_chat_id: document.getElementById('auto-tg-chat').value.trim(),
        discord_webhook: document.getElementById('auto-discord').value.trim()
    };
    const res = await api('/api/automation/settings', 'POST', payload);
    const d = await res.json();
    if (!res.ok) return alert(d.error || t('save_err'));
    document.getElementById('auto-status-msg').textContent = d.message;
    loadAutomation();
}

async function testNotifications() {
    const msgEl = document.getElementById('auto-status-msg');
    msgEl.textContent = t('auto_testing');
    const res = await api('/api/automation/test', 'POST');
    const d = await res.json();
    msgEl.textContent = d.message;
    if (!d.success) alert(d.message);
}

async function runAutomationNow() {
    const msgEl = document.getElementById('auto-status-msg');
    msgEl.textContent = t('auto_checking');
    const res = await api('/api/automation/run_now', 'POST');
    const d = await res.json();
    msgEl.textContent = d.message;
}

async function submitAutomationRule() {
    const upVal = parseFloat(document.getElementById('rule-up-val').value) || 0;
    const upUnit = document.getElementById('rule-up-unit').value;
    const upMult = upUnit === 'TiB' ? (1024 ** 4) : (upUnit === 'GiB' ? (1024 ** 3) : (1024 ** 2));

    const spVal = parseFloat(document.getElementById('rule-speed-val').value) || 0;
    const spUnit = document.getElementById('rule-speed-unit').value;
    const spMult = spUnit === 'MiB' ? (1024 ** 2) : 1024;

    const payload = {
        name: document.getElementById('rule-name').value.trim(),
        time_mode: document.getElementById('rule-time-mode').value,
        min_ratio: parseFloat(document.getElementById('rule-ratio').value) || 0,
        min_seed_days: parseFloat(document.getElementById('rule-days').value) || 0,
        min_uploaded_bytes: upVal > 0 ? Math.round(upVal * upMult) : 0,
        speed_op: document.getElementById('rule-speed-op').value,
        speed_bytes: spVal > 0 ? (spVal * spMult) : 0,
        speed_window_min: parseInt(document.getElementById('rule-speed-win').value) || 60,
        action_tag: document.getElementById('rule-tag').value.trim(),
        action_remove_tag: document.getElementById('rule-remove-tag').value.trim(),
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
        const d = await res.json();
        if (!res.ok || d.success === false) {
            return alert(d.error || `HTTP ${res.status}`);
        }
        cancelEditRule();
        loadAutomation();
    } catch (e) {
        alert(e.message);
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
    if (!confirm(t('rule_del_confirm'))) return;
    if (editingRuleId === id) cancelEditRule();
    await api('/api/automation/rules/delete', 'POST', { id });
    loadAutomation();
}