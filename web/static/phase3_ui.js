// web/static/phase3_ui.js
function openPreflightModal() {
    document.getElementById('pf-url').value = '';
    document.getElementById('pf-file').value = '';
    document.getElementById('pf-save-path').value = '';
    document.getElementById('pf-tags').value = '';
    document.getElementById('pf-paused').checked = false;
    document.getElementById('pf-result-box').innerHTML = '<span class="muted-text">Вставьте magnet/ссылку или выберите .torrent и нажмите «Проверить».</span>';
    document.getElementById('preflight-modal').style.display = 'flex';
}

async function runPreflightCheck() {
    const box = document.getElementById('pf-result-box');
    const fileInp = document.getElementById('pf-file');
    const url = document.getElementById('pf-url').value.trim();
    const savePath = document.getElementById('pf-save-path').value.trim();
    box.innerHTML = '⏳ Проверка места и поиск дублей...';

    let res;
    if (fileInp.files.length) {
        const fd = new FormData();
        fd.append('file', fileInp.files[0]);
        fd.append('save_path', savePath);
        res = await fetch('/api/inbox/preflight', { method: 'POST', headers: { 'X-CSRF-Token': CSRF_TOKEN }, body: fd });
    } else {
        res = await api('/api/inbox/preflight', 'POST', { url, save_path: savePath });
    }
    const d = await res.json();
    if (!d.success) { box.innerHTML = `<span style="color:var(--danger);">❌ ${escapeHtml(d.error || 'Ошибка')}</span>`; return; }

    const simHtml = (d.similar || []).length
        ? `<div class="mt-10" style="color:var(--warning);"><b>⚠️ Похожие раздачи в клиенте:</b><br>${d.similar.map(s => `• ${escapeHtml(s.name)} (${s.similarity}%)`).join('<br>')}</div>`
        : '<div class="lbl-xs accent-txt mt-10">✅ Дубликатов в библиотеке не найдено</div>';
    const warnHtml = d.warning ? `<div class="lbl-xs orange-txt mt-10">ℹ️ ${escapeHtml(d.warning)}</div>` : '';
    box.innerHTML = `
        <div><b>${escapeHtml(d.name)}</b> (${escapeHtml(d.size_fmt)})</div>
        <div class="lbl-xs muted-text mt-10">Свободно на диске: <b>${escapeHtml(d.disk_free_fmt)}</b> • В очереди: <b>${escapeHtml(d.queue_left_fmt)}</b> • Реально свободно: <b class="${d.space_ok ? 'accent-txt' : 'orange-txt'}">${escapeHtml(d.real_free_fmt)}</b></div>
        ${warnHtml}${simHtml}
    `;
}

async function submitPreflightAdd() {
    const fileInp = document.getElementById('pf-file');
    const url = document.getElementById('pf-url').value.trim();
    const savePath = document.getElementById('pf-save-path').value.trim();
    const tags = document.getElementById('pf-tags').value.trim();
    const paused = document.getElementById('pf-paused').checked;

    let res;
    if (fileInp.files.length) {
        const fd = new FormData();
        fd.append('file', fileInp.files[0]);
        fd.append('save_path', savePath);
        fd.append('tags', tags);
        fd.append('paused', paused ? '1' : '0');
        res = await fetch('/api/inbox/add', { method: 'POST', headers: { 'X-CSRF-Token': CSRF_TOKEN }, body: fd });
    } else {
        res = await api('/api/inbox/add', 'POST', { url, save_path: savePath, tags, paused });
    }
    const d = await res.json();
    alert(d.message || d.error);
    if (d.success) {
        document.getElementById('preflight-modal').style.display = 'none';
        if (typeof loadTorrents === 'function') loadTorrents(true);
    }
}

async function toggleSelectedSniper() {
    if (typeof selectedHash === 'undefined' || !selectedHash) return alert(t('err_select_torrent'));
    const res = await api('/api/snipers', 'POST', { hash: selectedHash, idle_hours: 4 });
    const d = await res.json();
    if (d.success) alert(d.active ? '🎯 Маячок включён! Пришлёт пуш по завершении, зависании (>4ч) или нехватке места.' : '🔕 Маячок снят.');
}

async function loadSavedViews() {
    const bar = document.getElementById('saved-views-bar');
    if (!bar) return;
    try {
        const res = await api('/api/views');
        if (!res.ok) return;
        const views = (await res.json()).views || [];
        bar.innerHTML = '';
        views.forEach(v => {
            const sp = document.createElement('span');
            sp.className = 'badge badge-dl pointer';
            sp.style.gap = '5px';
            sp.textContent = `🔖 ${v.name}`;
            sp.addEventListener('click', () => applySavedView(v.filters));
            if (typeof CURRENT_ROLE === 'undefined' || CURRENT_ROLE === 'admin') {
                const del = document.createElement('b');
                del.textContent = '✕';
                del.addEventListener('click', (e) => {
                    e.stopPropagation();
                    deleteSavedView(v.id);
                });
                sp.appendChild(del);
            }
            bar.appendChild(sp);
        });
        if (typeof CURRENT_ROLE === 'undefined' || CURRENT_ROLE === 'admin') {
            const btn = document.createElement('button');
            btn.className = 'btn btn-secondary btn-xs';
            btn.textContent = '+ Вид';
            btn.addEventListener('click', saveCurrentView);
            bar.appendChild(btn);
        }
    } catch (e) {}
}

function applySavedView(flt) {
    if (!flt) return;
    if (document.getElementById('search-box')) document.getElementById('search-box').value = flt.q || '';
    if (document.getElementById('filter-tag-select')) document.getElementById('filter-tag-select').value = flt.tag || '';
    if (document.getElementById('filter-tracker-select')) document.getElementById('filter-tracker-select').value = flt.tracker || '';
    if (document.getElementById('filter-tracker-err-select')) document.getElementById('filter-tracker-err-select').value = flt.err || '';
    if (typeof filterTorrents === 'function') filterTorrents();
}

async function saveCurrentView() {
    const name = prompt('Название быстрого вида (например: Ошибки или Игры):');
    if (!name || !name.trim()) return;
    const filters = {
        q: document.getElementById('search-box')?.value || '',
        tag: document.getElementById('filter-tag-select')?.value || '',
        tracker: document.getElementById('filter-tracker-select')?.value || '',
        err: document.getElementById('filter-tracker-err-select')?.value || ''
    };
    await api('/api/views', 'POST', { name: name.trim(), filters });
    loadSavedViews();
}

async function deleteSavedView(id) {
    await api('/api/views/delete', 'POST', { id });
    loadSavedViews();
}

async function loadNetOpsTab() {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
    loadUndoStack();
    try {
        const [ifRes, whRes] = await Promise.all([api('/api/net/iface_guard'), api('/api/webhooks')]);
        if (ifRes.ok) {
            const d = await ifRes.json();
            document.getElementById('iface-guard-en').checked = Boolean(d.enabled);
            const ifInp = document.getElementById('iface-guard-name');
            ifInp.value = d.expected_cfg || '';
            const curLbl = d.current_name || d.current || 'Any';
            ifInp.placeholder = `Эталонный интерфейс (сейчас в qB: ${curLbl})`;
            document.getElementById('iface-guard-panic').checked = Boolean(d.panic_on_drop);
        }
        if (whRes.ok) {
            const w = await whRes.json();
            document.getElementById('webhooks-urls').value = w.urls || '';
            document.getElementById('webhooks-bundler').checked = Boolean(w.bundler_enabled);
        }
    } catch (e) {}
}

async function runBottleneckCheck() {
    const box = document.getElementById('net-diag-out');
    box.textContent = '⏳ Анализ узких горлышек...';
    const res = await api('/api/net/bottleneck');
    const d = await res.json();
    box.textContent = (d.issues || []).join('\n');
}

async function runTrackerPing() {
    const box = document.getElementById('net-diag-out');
    box.textContent = '⏳ DNS + TCP пинг доменов трекеров...';
    const res = await api('/api/net/ping_trackers');
    const d = await res.json();
    box.textContent = (d.items || []).map(x => `${x.dns_ok ? '🟢' : '🔴'} ${x.host}:${x.port} (${x.scheme}) — ${x.latency_ms !== null ? x.latency_ms + ' ms' : x.error}`).join('\n') || 'Нет трекеров';
}

async function loadQbLog() {
    const box = document.getElementById('net-diag-out');
    const res = await api('/api/qb/log');
    const d = await res.json();
    box.textContent = d.success ? d.log : `❌ ${d.error}`;
}

async function reanimateQb(force) {
    if (!confirm(force ? 'Принудительно убить и перезапустить qBittorrent?' : 'Мягко перезапустить qBittorrent (ожидание до 20с)?')) return;
    const res = await api('/api/qb/reanimate', 'POST', { force });
    const d = await res.json();
    alert(d.message);
}

async function saveIfaceGuard() {
    await api('/api/net/iface_guard', 'POST', {
        enabled: document.getElementById('iface-guard-en').checked,
        expected: document.getElementById('iface-guard-name').value.trim(),
        panic_on_drop: document.getElementById('iface-guard-panic').checked
    });
    alert('✅ Страж интерфейса сохранён');
}

async function saveWebhooks(test = false) {
    await api('/api/webhooks', 'POST', {
        urls: document.getElementById('webhooks-urls').value,
        bundler_enabled: document.getElementById('webhooks-bundler').checked,
        test
    });
    alert(test ? '🔔 Тестовый вебхук отправлен' : '✅ Настройки вебхуков сохранены');
}

async function loadUndoStack() {
    const box = document.getElementById('undo-stack-list');
    if (!box) return;
    const res = await api('/api/undo/list');
    if (!res.ok) return;
    const items = (await res.json()).items || [];
    box.innerHTML = items.length ? items.map(u => `
        <div class="row-between" style="background:var(--bg-input); padding:5px 8px; border-radius:5px;">
            <span>[${u.date}] <b>${escapeHtml(u.title)}</b></span>
            ${u.undone ? '<span class="muted-text">Отменено</span>' : `<button class="btn btn-secondary btn-xs" onclick="runUndoOp(${u.id})">↩️ Отменить</button>`}
        </div>
    `).join('') : '<span class="muted-text">Стек отката пуст</span>';
}

async function runUndoOp(id) {
    if (!confirm('Откатить эту массовую операцию?')) return;
    const res = await api('/api/undo/execute', 'POST', { id });
    const d = await res.json();
    alert(d.message || d.error);
    loadUndoStack();
}

async function checkUpdateRadar() {
    const box = document.getElementById('radar-out');
    box.textContent = '⏳ Проверка...';
    const res = await api('/api/radar/updates?force=1');
    const d = await res.json();
    box.textContent = `tbr PRO: v${d.tbr?.current_version} (последняя v${d.tbr?.latest_version}) | qBittorrent на GitHub: ${d.qb_latest}`;
}

async function prepareQbUpdate() {
    if (!confirm('Создать полный сейф (Config Vault + ZIP баз + Архив .torrent) перед обновлением qBittorrent?')) return;
    const res = await api('/api/radar/prepare_qb', 'POST');
    const d = await res.json();
    alert(`✅ Всё готово к обновлению!\nБД: ${d.db_backup}\nАрхив .torrent (+${d.archive_added})`);
}

async function loadAutoExtrasTab() {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
    const [cRes, rRes] = await Promise.all([api('/api/conductor'), api('/api/router/rules')]);
    if (cRes.ok) {
        const c = await cRes.json();
        document.getElementById('cond-enabled').checked = Boolean(c.enabled);
        document.getElementById('cond-blocks').value = JSON.stringify(c.blocks || [{ start_h: 0, end_h: 8, pct_limit: 100 }, { start_h: 8, end_h: 23, pct_limit: 50 }]);
        document.getElementById('smart-queue-en').checked = Boolean(c.smart_queue);
        document.getElementById('smart-reannounce-en').checked = Boolean(c.smart_reannounce);
    }
    if (rRes.ok) {
        const rules = (await rRes.json()).rules || [];
        document.getElementById('router-rules-list').innerHTML = rules.map(r => `
            <div class="row-between" style="background:var(--bg-input); padding:4px 8px; border-radius:5px;">
                <span>#${r.priority} ${escapeHtml(r.match_field)}: <code>${escapeHtml(r.pattern)}</code> → <b>${escapeHtml(r.target_category || r.target_path)}</b></span>
                <button class="btn btn-danger btn-xs" onclick="deleteRouterRule(${r.id})">✕</button>
            </div>
        `).join('') || '<span class="muted-text">Правил авто-роутера нет</span>';
    }
}

async function saveConductorAndExtras() {
    let blocks = [];
    try { blocks = JSON.parse(document.getElementById('cond-blocks').value); } catch (e) { return alert('Некорректный JSON блоков дирижёра'); }
    await api('/api/conductor', 'POST', {
        enabled: document.getElementById('cond-enabled').checked,
        blocks,
        smart_queue: document.getElementById('smart-queue-en').checked,
        smart_reannounce: document.getElementById('smart-reannounce-en').checked
    });
    alert('✅ Настройки дирижёра и очередей сохранены');
}

async function overrideConductor() {
    await api('/api/conductor/override', 'POST');
    alert('⚡ Ручное переопределение включено до конца текущего часа!');
}

async function addRouterRule() {
    const res = await api('/api/router/rules', 'POST', {
        match_field: document.getElementById('router-field').value,
        pattern: document.getElementById('router-pattern').value,
        category: document.getElementById('router-cat').value,
        path: document.getElementById('router-path').value
    });
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка добавления правила');
    document.getElementById('router-pattern').value = '';
    loadAutoExtrasTab();
}

async function deleteRouterRule(id) {
    await api('/api/router/delete', 'POST', { id });
    loadAutoExtrasTab();
}

function exportPresets() { window.location.href = '/api/presets/export'; }

async function importPresetsFile(file) {
    if (!file) return;
    try {
        const data = JSON.parse(await file.text());
        const res = await api('/api/presets/import', 'POST', data);
        const d = await res.json();
        alert(d.message || d.error);
        if (typeof loadAutomation === 'function') loadAutomation();
    } catch (e) { alert('Ошибка чтения JSON: ' + e.message); }
}

document.addEventListener('DOMContentLoaded', () => {
    setTimeout(loadSavedViews, 600);
});