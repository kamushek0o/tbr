// web/static/tuner_rules_ui.js
let _tunerRulesList = [];
let _editingRuleId = null;
let _editingRuleApps = [];
let _appsCatalog = [];
let _friendlyAppsMap = {};

async function loadTunerRulesAndCatalog() {
    const [rRes, cRes] = await Promise.all([api('/api/tuner/rules'), api('/api/tuner/catalog')]);
    if (rRes.ok) { _tunerRulesList = (await rRes.json()).rules || []; renderTunerRulesList(); }
    if (cRes.ok) {
        const c = await cRes.json();
        _appsCatalog = c.catalog || [];
        _friendlyAppsMap = c.friendly_map || {};
    }
}

function _formatRuleSummary(r) {
    const c = r.config || {}, parts = [];
    if (c.processes?.enabled && c.processes.names?.length) parts.push(`🎮 Программы (${c.processes.names.length})`);
    if (c.schedule?.enabled) parts.push(`⏰ ${c.schedule.start}–${c.schedule.end}`);
    if (c.external_load?.enabled) parts.push('⚡ Нагрузка ПК');
    return parts.join(' + ') || 'Нет условий';
}

function renderTunerRulesList() {
    const box = document.getElementById('tuner-rules-list');
    if (!box) return;
    if (!_tunerRulesList.length) {
        box.innerHTML = '<div class="center-msg lbl-xs muted-text">Правил пока нет. Нажмите «+ Добавить правило».</div>';
        return;
    }
    box.innerHTML = _tunerRulesList.map((r, idx) => `
        <div class="tuner-rule-row ${r.enabled ? '' : 'tuner-row-disabled'}" style="opacity:${r.enabled ? '1' : '0.5'};">
            <div class="row-gap" style="gap:6px; min-width:0; flex:1;">
                <span class="badge badge-pause">#${idx + 1}</span>
                <input type="checkbox" ${r.enabled ? 'checked' : ''} onchange="toggleTunerRuleEnabled(${r.id}, this.checked)" title="Вкл/Выкл">
                <div style="min-width:0; flex:1;">
                    <div style="font-size:12px; font-weight:700; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(r.name)} → <span class="accent-txt">${escapeHtml(getProfileLabel(r.target_profile_id))}</span></div>
                    <div class="lbl-micro">${escapeHtml(_formatRuleSummary(r))}</div>
                </div>
            </div>
            <div class="row-gap" style="gap:3px;">
                <button class="btn btn-secondary btn-xs" ${idx === 0 ? 'disabled' : ''} onclick="moveTunerRule(${r.id}, 'up')">⬆️</button>
                <button class="btn btn-secondary btn-xs" ${idx === _tunerRulesList.length - 1 ? 'disabled' : ''} onclick="moveTunerRule(${r.id}, 'down')">⬇️</button>
                <button class="btn btn-secondary btn-xs" onclick="editTunerRule(${r.id})">✏️</button>
                <button class="btn btn-danger btn-xs" onclick="deleteTunerRule(${r.id})">🗑️</button>
            </div>
        </div>
    `).join('');
}

function syncRuleFormDisabledStates() {
    const prEn = Boolean(document.getElementById('tr-f-proc-en')?.checked);
    document.getElementById('tr-f-proc-chips')?.classList.toggle('tuner-row-disabled', !prEn);

    const scEn = Boolean(document.getElementById('tr-f-sched-en')?.checked);
    document.getElementById('tr-f-sched-start').disabled = !scEn;
    document.getElementById('tr-f-sched-end').disabled = !scEn;
    document.querySelectorAll('.tr-f-day').forEach(d => { d.disabled = !scEn; });

    const exEn = Boolean(document.getElementById('tr-f-ext-en')?.checked);
    ['cpu', 'net', 'ram', 'disk'].forEach(k => {
        const chk = document.getElementById(`tr-f-${k}-en`);
        if (chk) chk.disabled = !exEn;
        const subEn = exEn && Boolean(chk?.checked);
        ['w', 'r'].forEach(s => { const inp = document.getElementById(`tr-f-${k}-${s}`); if (inp) inp.disabled = !subEn; });
    });
}

function _renderAppChipHtml(exe, removable = true) {
    const meta = _friendlyAppsMap[exe.toLowerCase()];
    const lbl = meta ? `${meta.icon} ${meta.name}` : `🖥️ ${exe}`;
    const btn = removable ? ` <b class="pointer" onclick="removeAppFromRule('${escapeHtml(exe)}')">×</b>` : '';
    return `<span class="tuner-chip">${escapeHtml(lbl)}${btn}</span>`;
}

function renderRuleAppChips() {
    const box = document.getElementById('tr-f-proc-chips');
    if (box) box.innerHTML = _editingRuleApps.length ? _editingRuleApps.map(e => _renderAppChipHtml(e, true)).join('') : '<span class="lbl-xs muted-text">Программы не выбраны</span>';
    const mBox = document.getElementById('apps-modal-selected');
    if (mBox) mBox.innerHTML = _editingRuleApps.map(e => _renderAppChipHtml(e, true)).join('');
}

function removeAppFromRule(exe) {
    _editingRuleApps = _editingRuleApps.filter(x => x.toLowerCase() !== exe.toLowerCase());
    renderRuleAppChips();
    filterAppsCatalog();
}

function toggleAppInRule(exe) {
    const low = exe.toLowerCase();
    if (_editingRuleApps.some(x => x.toLowerCase() === low)) _editingRuleApps = _editingRuleApps.filter(x => x.toLowerCase() !== low);
    else _editingRuleApps.push(exe);
    renderRuleAppChips();
    filterAppsCatalog();
}

function addManualAppToRule() {
    const inp = document.getElementById('apps-modal-manual');
    const val = (inp?.value || '').trim();
    if (!val) return;
    if (!_editingRuleApps.some(x => x.toLowerCase() === val.toLowerCase())) _editingRuleApps.push(val);
    inp.value = '';
    renderRuleAppChips();
}

function openNewRuleForm() {
    _editingRuleId = null;
    _editingRuleApps = [];
    document.getElementById('tr-edit-title').textContent = 'Новое правило';
    document.getElementById('tr-f-name').value = '';
    document.getElementById('tr-f-proc-en').checked = true;
    document.getElementById('tr-f-sched-en').checked = false;
    document.getElementById('tr-f-ext-en').checked = false;
    document.getElementById('tr-f-cpu-en').checked = true; document.getElementById('tr-f-cpu-w').value = 45; document.getElementById('tr-f-cpu-r').value = 25;
    document.getElementById('tr-f-net-en').checked = true; document.getElementById('tr-f-net-w').value = 25; document.getElementById('tr-f-net-r').value = 12;
    document.getElementById('tr-f-ram-en').checked = false; document.getElementById('tr-f-ram-w').value = 15; document.getElementById('tr-f-ram-r').value = 25;
    document.getElementById('tr-f-disk-en').checked = false; document.getElementById('tr-f-disk-w').value = 70; document.getElementById('tr-f-disk-r').value = 45;
    document.getElementById('tr-f-enter').value = 10; document.getElementById('tr-f-exit').value = 180;
    renderRuleAppChips();
    syncRuleFormDisabledStates();
    document.getElementById('tuner-rule-editor').classList.remove('hidden');
}

function editTunerRule(rid) {
    const r = _tunerRulesList.find(x => x.id === rid);
    if (!r) return;
    _editingRuleId = rid;
    const c = r.config || {}, pr = c.processes || {}, sc = c.schedule || {}, ex = c.external_load || {};
    _editingRuleApps = [...(pr.names || [])];
    document.getElementById('tr-edit-title').textContent = `Редактирование: ${r.name}`;
    document.getElementById('tr-f-name').value = r.name || '';
    document.getElementById('tr-f-target').value = r.target_profile_id || 'comfort';
    document.getElementById('tr-f-proc-en').checked = Boolean(pr.enabled);
    document.getElementById('tr-f-sched-en').checked = Boolean(sc.enabled);
    document.getElementById('tr-f-sched-start').value = sc.start || '01:00';
    document.getElementById('tr-f-sched-end').value = sc.end || '08:00';
    document.querySelectorAll('.tr-f-day').forEach(d => { d.checked = (sc.days || [0,1,2,3,4,5,6]).includes(parseInt(d.value)); });
    document.getElementById('tr-f-ext-en').checked = Boolean(ex.enabled);
    document.getElementById('tr-f-cpu-en').checked = Boolean(ex.cpu_enabled); document.getElementById('tr-f-cpu-w').value = ex.cpu_warn ?? 45; document.getElementById('tr-f-cpu-r').value = ex.cpu_recover ?? 25;
    document.getElementById('tr-f-net-en').checked = Boolean(ex.net_enabled); document.getElementById('tr-f-net-w').value = ex.net_warn_pct ?? 25; document.getElementById('tr-f-net-r').value = ex.net_recover_pct ?? 12;
    document.getElementById('tr-f-ram-en').checked = Boolean(ex.ram_enabled); document.getElementById('tr-f-ram-w').value = ex.ram_min_free ?? 15; document.getElementById('tr-f-ram-r').value = ex.ram_recover_free ?? 25;
    document.getElementById('tr-f-disk-en').checked = Boolean(ex.disk_enabled); document.getElementById('tr-f-disk-w').value = ex.disk_warn ?? 70; document.getElementById('tr-f-disk-r').value = ex.disk_recover ?? 45;
    document.getElementById('tr-f-enter').value = c.enter_sec ?? 10; document.getElementById('tr-f-exit').value = c.exit_sec ?? 180;
    renderRuleAppChips();
    syncRuleFormDisabledStates();
    document.getElementById('tuner-rule-editor').classList.remove('hidden');
}

function cancelTunerRuleEdit() {
    document.getElementById('tuner-rule-editor').classList.add('hidden');
}

async function saveTunerRuleForm() {
    const iv = id => parseInt(document.getElementById(id)?.value) || 0;
    const cb = id => Boolean(document.getElementById(id)?.checked);
    const existing = _editingRuleId ? _tunerRulesList.find(x => x.id === _editingRuleId) : null;
    const payload = {
        id: _editingRuleId,
        name: document.getElementById('tr-f-name').value.trim() || 'Новое правило',
        enabled: existing ? Boolean(existing.enabled) : true,
        target_profile_id: document.getElementById('tr-f-target').value,
        config: {
            processes: { enabled: cb('tr-f-proc-en'), names: _editingRuleApps },
            schedule: { enabled: cb('tr-f-sched-en'), start: document.getElementById('tr-f-sched-start').value, end: document.getElementById('tr-f-sched-end').value, days: [...document.querySelectorAll('.tr-f-day:checked')].map(d => parseInt(d.value)) },
            external_load: {
                enabled: cb('tr-f-ext-en'),
                cpu_enabled: cb('tr-f-cpu-en'), cpu_warn: iv('tr-f-cpu-w'), cpu_recover: iv('tr-f-cpu-r'),
                net_enabled: cb('tr-f-net-en'), net_warn_pct: iv('tr-f-net-w'), net_recover_pct: iv('tr-f-net-r'),
                ram_enabled: cb('tr-f-ram-en'), ram_min_free: iv('tr-f-ram-w'), ram_recover_free: iv('tr-f-ram-r'),
                disk_enabled: cb('tr-f-disk-en'), disk_warn: iv('tr-f-disk-w'), disk_recover: iv('tr-f-disk-r'),
            },
            enter_sec: iv('tr-f-enter'), exit_sec: iv('tr-f-exit')
        }
    };
    const res = await api('/api/tuner/rules', 'POST', payload);
    if (res.ok) { _tunerRulesList = (await res.json()).rules; cancelTunerRuleEdit(); renderTunerRulesList(); }
}

async function toggleTunerRuleEnabled(rid, en) {
    const r = _tunerRulesList.find(x => x.id === rid);
    if (!r) return;
    const res = await api('/api/tuner/rules', 'POST', { id: r.id, name: r.name, enabled: en, target_profile_id: r.target_profile_id, config: r.config });
    if (res.ok) { _tunerRulesList = (await res.json()).rules; renderTunerRulesList(); }
}

async function moveTunerRule(rid, direction) {
    const res = await api('/api/tuner/rules', 'POST', { move_id: rid, direction });
    if (res.ok) { _tunerRulesList = (await res.json()).rules; renderTunerRulesList(); }
}

async function deleteTunerRule(rid) {
    if (!confirm('Удалить это правило?')) return;
    const res = await api('/api/tuner/rules', 'POST', { delete_id: rid });
    if (res.ok) { _tunerRulesList = (await res.json()).rules; renderTunerRulesList(); }
}

function openAppsPickerModal() {
    document.getElementById('apps-modal-search').value = '';
    document.getElementById('tuner-apps-modal').style.display = 'flex';
    renderRuleAppChips();
    filterAppsCatalog();
    loadRunningAppsForModal();
}

function closeAppsPickerModal() { document.getElementById('tuner-apps-modal').style.display = 'none'; }

function filterAppsCatalog() {
    const q = (document.getElementById('apps-modal-search')?.value || '').trim().toLowerCase();
    const box = document.getElementById('apps-modal-catalog');
    if (!box) return;
    box.innerHTML = _appsCatalog.map(grp => {
        const items = (grp.apps || []).filter(a => !q || a.name.toLowerCase().includes(q) || a.exe.toLowerCase().includes(q));
        if (!items.length) return '';
        return `<div><div class="lbl-micro mb-6">${grp.icon} ${escapeHtml(grp.category)}</div><div class="row-wrap" style="gap:4px;">` +
            items.map(a => {
                const active = _editingRuleApps.some(x => x.toLowerCase() === a.exe.toLowerCase());
                return `<button type="button" class="${active ? 'btn btn-xs' : 'btn btn-secondary btn-xs'}" onclick="toggleAppInRule('${escapeHtml(a.exe)}')">${a.icon} ${escapeHtml(a.name)}</button>`;
            }).join('') + '</div></div>';
    }).join('');
}

async function loadRunningAppsForModal() {
    const box = document.getElementById('apps-modal-running');
    if (!box) return;
    box.innerHTML = '<span class="lbl-xs muted-text">⏳ Читаю процессы ПК...</span>';
    const sys = document.getElementById('apps-modal-sys')?.checked ? '1' : '0';
    const res = await api(`/api/tuner/processes?system=${sys}`);
    if (!res.ok) return;
    const list = (await res.json()).processes || [];
    box.innerHTML = list.map(p => {
        const cnt = p.count > 1 ? ` ×${p.count}` : '';
        return `<button type="button" class="btn btn-secondary btn-xs" onclick="toggleAppInRule('${escapeHtml(p.exe)}')" title="${escapeHtml(p.exe)}">${escapeHtml(p.icon)} ${escapeHtml(p.label)} (${escapeHtml(p.exe)})${cnt}</button>`;
    }).join('') || '<span class="lbl-xs muted-text">Процессы не найдены</span>';
}
