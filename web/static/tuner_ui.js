// web/static/tuner_ui.js
let _tunerProfiles = {};
let _tunerCurProfile = 'performance';
let _tunerRules = {};
let _tunerAvailableDisks = [];

function syncTunerDisabledStates() {
    const setGroupState = (chkId, rowId, inputIds) => {
        const en = Boolean(document.getElementById(chkId)?.checked);
        const row = document.getElementById(rowId);
        if (row) row.classList.toggle('tuner-row-disabled', !en);
        inputIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.disabled = !en;
        });
    };

    setGroupState('tp-g-disk-en', 'guard-row-disk', ['tp-g-disk-target', 'tp-g-disk-warn', 'tp-g-disk-crit', 'tp-g-disk-rec']);
    setGroupState('tp-g-cpu-en', 'guard-row-cpu', ['tp-g-cpu-warn', 'tp-g-cpu-rec']);
    setGroupState('tp-g-ram-en', 'guard-row-ram', ['tp-g-ram-min', 'tp-g-ram-rec']);
    setGroupState('tp-g-net-en', 'guard-row-net', ['tp-g-net-warn', 'tp-g-net-rec']);

    const sqEn = Boolean(document.getElementById('tp-sq-en')?.checked);
    ['tp-sq-up', 'tp-sq-dl'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = !sqEn;
        document.getElementById(`wrap-${id}`)?.classList.toggle('tuner-row-disabled', !sqEn);
    });

    const actMode = document.getElementById('tp-act-mode')?.value || 'keep';
    const minEl = document.getElementById('tp-act-min');
    const maxEl = document.getElementById('tp-act-max');
    if (minEl) minEl.disabled = (actMode === 'keep');
    if (maxEl) maxEl.disabled = (actMode !== 'range');
    document.getElementById('wrap-tp-act-min')?.classList.toggle('tuner-row-disabled', actMode === 'keep');
    document.getElementById('wrap-tp-act-max')?.classList.toggle('tuner-row-disabled', actMode !== 'range');

    const ptUpAuto = Boolean(document.getElementById('tp-pt-up-auto')?.checked);
    ['tp-pt-up-min', 'tp-pt-up-max'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = ptUpAuto;
    });

    const mcAuto = Boolean(document.getElementById('tp-mc-auto')?.checked);
    ['tp-mc-min', 'tp-mc-max'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = mcAuto;
    });

    const prEn = Boolean(document.getElementById('tr-proc-en')?.checked);
    ['tr-proc-mode', 'tr-proc-names', 'tr-proc-enter', 'tr-proc-exit'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = !prEn;
    });
    document.getElementById('rules-box-proc')?.classList.toggle('tuner-row-disabled', !prEn);

    const extEn = Boolean(document.getElementById('tr-ext-en')?.checked);
    ['tr-ext-mode', 'tr-ext-cpu-w', 'tr-ext-cpu-r', 'tr-ext-net-w', 'tr-ext-net-r', 'tr-ext-ram-w', 'tr-ext-ram-r', 'tr-ext-enter', 'tr-ext-exit'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = !extEn;
    });
    document.getElementById('rules-box-ext')?.classList.toggle('tuner-row-disabled', !extEn);
}

function _updateDiskSelectorOptions(selectedVal) {
    const sel = document.getElementById('tp-g-disk-target');
    if (!sel) return;
    sel.innerHTML = '';
    sel.add(new Option('Авто (по раздачам)', ''));
    sel.add(new Option('Все диски (Max)', 'ALL'));
    _tunerAvailableDisks.forEach(d => {
        sel.add(new Option(`${d.path} (${d.free_fmt} своб.)`, d.path));
    });
    sel.value = selectedVal || '';
}

async function loadTunerTab() {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
    await Promise.all([refreshTunerState(), loadTunerProfiles(), loadTunerRules()]);
}

async function refreshTunerState() {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
    try {
        const res = await api('/api/tuner/state');
        if (!res.ok) return;
        const d = await res.json();
        const st = d.state || {}, tel = d.telemetry || {}, mode = st.mode || 'off';
        _tunerAvailableDisks = d.available_disks || [];

        ['off', 'comfort', 'performance'].forEach(m => {
            const b = document.getElementById(`tuner-btn-${m}`);
            if (b) b.className = (m === mode) ? 'btn btn-xs' : 'btn btn-secondary btn-xs';
        });
        const chk = document.getElementById('tuner-auto-chk');
        if (chk) chk.checked = Boolean(st.auto_switch_enabled);

        const reason = d.switch_reason || st.last_reason || 'Выключен';
        const badge = document.getElementById('tuner-reason-badge');
        if (badge) {
            badge.textContent = reason;
            badge.className = mode === 'off' ? 'badge badge-pause' : (mode === 'performance' ? 'badge badge-up' : 'badge badge-dl');
        }
        const hb = document.getElementById('tuner-header-badge');
        if (hb) {
            hb.textContent = mode === 'off' ? '🎛️ Тюнер: Выкл' : (mode === 'performance' ? '🚀 Тюнер: Произв.' : '🛋️ Тюнер: Комф.');
            hb.className = mode === 'off' ? 'badge badge-pause pointer admin-only' : (mode === 'performance' ? 'badge badge-up pointer admin-only' : 'badge badge-dl pointer admin-only');
        }
        document.getElementById('tuner-btn-clear-ov')?.classList.toggle('hidden', !st.manual_override_mode);

        const setTxt = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
        const diskTitle = tel.monitored_disk_label ? `Диск I/O (${tel.monitored_disk_label})` : 'Диск I/O';
        setTxt('tel-disk-title', diskTitle);
        setTxt('tel-disk', tel.psutil_available === false ? 'нет psutil' : `${tel.disk_busy ?? 0}%`);
        setTxt('tel-cpu', `${tel.cpu_ext ?? 0}%`);
        setTxt('tel-ram', `${tel.ram_free ?? 0}%`);
        setTxt('tel-chan', `${tel.channel_pct ?? 0}%`);
        setTxt('tel-net', `${tel.net_ext_pct ?? 0}%`);
        const curMu = (st.current_limits || {}).max_uploads || (st.baseline || {}).max_uploads || '—';
        setTxt('tel-slots', `${curMu} (${tel.slots_fill_pct ?? 0}%)`);

        const tbody = document.getElementById('tuner-history-tbody');
        if (tbody) {
            const hist = d.history || [];
            tbody.innerHTML = hist.length ? hist.map(h => `
                <tr><td>${escapeHtml(h.time)}</td><td>${escapeHtml(h.mode)}</td><td><span class="badge badge-pause">${escapeHtml(h.event_type)}</span></td><td style="white-space:normal;">${escapeHtml(h.reason)}</td><td>${h.old_slots}→${h.new_slots}</td></tr>
            `).join('') : '<tr><td colspan="5" class="center-msg">Нет событий</td></tr>';
        }
    } catch (e) {}
}

async function setTunerMode(mode) {
    const res = await api('/api/tuner/mode', 'POST', { mode, is_manual: true });
    if (!res.ok) return alert((await res.json()).error || 'Ошибка');
    refreshTunerState();
}

async function toggleTunerAutoSwitch() {
    const auto_switch = document.getElementById('tuner-auto-chk')?.checked || false;
    const mode = auto_switch ? (_tunerRules.default_mode || 'performance') : 'off';
    await api('/api/tuner/mode', 'POST', { mode, auto_switch, is_manual: false });
    refreshTunerState();
}

async function clearTunerOverride() {
    await api('/api/tuner/mode', 'POST', { mode: _tunerRules.default_mode || 'performance', clear_override: true, is_manual: false });
    refreshTunerState();
}

async function restoreTunerBaseline() {
    if (!confirm('Выключить тюнер и восстановить эталонные настройки qBittorrent?')) return;
    const res = await api('/api/tuner/restore_baseline', 'POST');
    alert((await res.json()).message || 'Готово');
    refreshTunerState();
}

async function loadTunerProfiles() {
    const res = await api('/api/tuner/profiles');
    if (res.ok) { _tunerProfiles = (await res.json()).profiles || {}; selectTunerProfileTab(_tunerCurProfile); }
}

function selectTunerProfileTab(mode) {
    _tunerCurProfile = mode;
    document.getElementById('tp-tab-performance').className = mode === 'performance' ? 'btn btn-xs' : 'btn btn-secondary btn-xs';
    document.getElementById('tp-tab-comfort').className = mode === 'comfort' ? 'btn btn-xs' : 'btn btn-secondary btn-xs';
    const p = _tunerProfiles[mode] || {}, g = p.guards || {};
    const sv = (id, v) => { const e = document.getElementById(id); if (e) e.value = v ?? ''; };
    const sc = (id, v) => { const e = document.getElementById(id); if (e) e.checked = Boolean(v); };

    sv('tp-mu-min', p.max_uploads_min); sv('tp-mu-max', p.max_uploads_max); sv('tp-mu-start', p.max_uploads_start);
    sv('tp-pt-up-min', p.per_torrent_up_min); sv('tp-pt-up-max', p.per_torrent_up_max); sc('tp-pt-up-auto', p.per_torrent_up_auto);
    sv('tp-mc-min', p.max_connec_min); sv('tp-mc-max', p.max_connec_max); sc('tp-mc-auto', p.max_connec_auto);
    sv('tp-pt-con-min', p.per_torrent_connec_min); sv('tp-pt-con-max', p.per_torrent_connec_max);
    sv('tp-act-mode', p.active_uploads_mode || 'keep'); sv('tp-act-min', p.active_uploads_min); sv('tp-act-max', p.active_uploads_max);
    sv('tp-ch-min', p.channel_target_min); sv('tp-ch-max', p.channel_target_max);
    sv('tp-up-pct', p.up_limit_pct); sv('tp-dl-pct', p.dl_limit_pct);
    sc('tp-sq-en', p.squeeze_enabled); sv('tp-sq-up', p.squeeze_up_pct); sv('tp-sq-dl', p.squeeze_dl_pct);
    sv('tp-cd-sec', p.cooldown_sec); sv('tp-step-up', p.step_up_size); sc('tp-yield-turtle', p.yield_to_turtle);

    _updateDiskSelectorOptions(g.disk?.target_disk || '');
    sc('tp-g-disk-en', g.disk?.enabled); sv('tp-g-disk-warn', g.disk?.warn); sv('tp-g-disk-crit', g.disk?.crit); sv('tp-g-disk-rec', g.disk?.recover);
    sc('tp-g-cpu-en', g.cpu?.enabled); sv('tp-g-cpu-warn', g.cpu?.warn); sv('tp-g-cpu-rec', g.cpu?.recover);
    sc('tp-g-ram-en', g.ram?.enabled); sv('tp-g-ram-min', g.ram?.min_free); sv('tp-g-ram-rec', g.ram?.recover_free);
    sc('tp-g-net-en', g.net?.enabled); sv('tp-g-net-warn', g.net?.warn_pct); sv('tp-g-net-rec', g.net?.recover_pct);

    syncTunerDisabledStates();
}

async function saveTunerProfile() {
    const iv = id => parseInt(document.getElementById(id)?.value) || 0;
    const cb = id => Boolean(document.getElementById(id)?.checked);
    const profile = {
        max_uploads_min: iv('tp-mu-min'), max_uploads_max: iv('tp-mu-max'), max_uploads_start: iv('tp-mu-start'),
        per_torrent_up_min: iv('tp-pt-up-min'), per_torrent_up_max: iv('tp-pt-up-max'), per_torrent_up_auto: cb('tp-pt-up-auto'),
        max_connec_min: iv('tp-mc-min'), max_connec_max: iv('tp-mc-max'), max_connec_auto: cb('tp-mc-auto'),
        per_torrent_connec_min: iv('tp-pt-con-min'), per_torrent_connec_max: iv('tp-pt-con-max'),
        active_uploads_mode: document.getElementById('tp-act-mode')?.value || 'keep',
        active_uploads_min: iv('tp-act-min'), active_uploads_max: iv('tp-act-max'),
        channel_target_min: iv('tp-ch-min'), channel_target_max: iv('tp-ch-max'),
        up_limit_pct: iv('tp-up-pct'), dl_limit_pct: iv('tp-dl-pct'),
        squeeze_enabled: cb('tp-sq-en'), squeeze_up_pct: iv('tp-sq-up'), squeeze_dl_pct: iv('tp-sq-dl'),
        cooldown_sec: iv('tp-cd-sec'), step_up_size: iv('tp-step-up'), yield_to_turtle: cb('tp-yield-turtle'),
        guards: {
            disk: {
                enabled: cb('tp-g-disk-en'),
                target_disk: document.getElementById('tp-g-disk-target')?.value || '',
                warn: iv('tp-g-disk-warn'), crit: iv('tp-g-disk-crit'), recover: iv('tp-g-disk-rec')
            },
            cpu:  { enabled: cb('tp-g-cpu-en'), warn: iv('tp-g-cpu-warn'), recover: iv('tp-g-cpu-rec') },
            ram:  { enabled: cb('tp-g-ram-en'), min_free: iv('tp-g-ram-min'), recover_free: iv('tp-g-ram-rec') },
            net:  { enabled: cb('tp-g-net-en'), warn_pct: iv('tp-g-net-warn'), recover_pct: iv('tp-g-net-rec') }
        }
    };
    const res = await api('/api/tuner/profiles', 'POST', { mode: _tunerCurProfile, profile });
    if (res.ok) { _tunerProfiles[_tunerCurProfile] = (await res.json()).profile; alert(`✅ Профиль «${_tunerCurProfile}» сохранён`); }
}

async function resetTunerProfile() {
    if (!confirm(`Сбросить профиль «${_tunerCurProfile}» к заводским значениям?`)) return;
    const res = await api('/api/tuner/profiles', 'POST', { reset_mode: _tunerCurProfile });
    if (res.ok) { _tunerProfiles[_tunerCurProfile] = (await res.json()).profile; selectTunerProfileTab(_tunerCurProfile); }
}

async function loadTunerRules() {
    const res = await api('/api/tuner/rules');
    if (!res.ok) return;
    _tunerRules = (await res.json()).rules || {};
    const sv = (id, v) => { const e = document.getElementById(id); if (e) e.value = v ?? ''; };
    const sc = (id, v) => { const e = document.getElementById(id); if (e) e.checked = Boolean(v); };

    sv('tr-def-mode', _tunerRules.default_mode || 'performance');
    sv('tr-ov-policy', _tunerRules.override_policy || '2h');
    const pr = _tunerRules.processes || {}, ex = _tunerRules.external_load || {};
    sc('tr-proc-en', pr.enabled); sv('tr-proc-mode', pr.target_mode || 'comfort');
    sv('tr-proc-names', (pr.names || []).join(', ')); sv('tr-proc-enter', pr.enter_sec); sv('tr-proc-exit', pr.exit_sec);
    sc('tr-ext-en', ex.enabled); sv('tr-ext-mode', ex.target_mode || 'comfort');
    sv('tr-ext-cpu-w', ex.cpu_warn); sv('tr-ext-cpu-r', ex.cpu_recover);
    sv('tr-ext-net-w', ex.net_warn_pct); sv('tr-ext-net-r', ex.net_recover_pct);
    sv('tr-ext-ram-w', ex.ram_min_free); sv('tr-ext-ram-r', ex.ram_recover_free);
    sv('tr-ext-enter', ex.enter_sec); sv('tr-ext-exit', ex.exit_sec);

    renderTunerSchedules();
    syncTunerDisabledStates();
}

function renderTunerSchedules() {
    const box = document.getElementById('tr-sched-list');
    if (!box) return;
    const list = _tunerRules.schedules || [];
    box.innerHTML = list.map((s, idx) => `
        <div class="row-gap" style="gap:4px;">
            <input type="time" class="form-control" style="width:96px; padding:3px 4px;" value="${escapeHtml(s.start)}" onchange="_tunerRules.schedules[${idx}].start=this.value">
            <span>—</span>
            <input type="time" class="form-control" style="width:96px; padding:3px 4px;" value="${escapeHtml(s.end)}" onchange="_tunerRules.schedules[${idx}].end=this.value">
            <select class="form-control grow-1" style="padding:3px 4px;" onchange="_tunerRules.schedules[${idx}].mode=this.value">
                <option value="performance" ${s.mode==='performance'?'selected':''}>Производ.</option>
                <option value="comfort" ${s.mode==='comfort'?'selected':''}>Комфорт</option>
            </select>
            <button class="btn btn-danger btn-xs" onclick="_tunerRules.schedules.splice(${idx},1);renderTunerSchedules()">✕</button>
        </div>
    `).join('') || '<span class="lbl-xs muted-text">Окон расписания нет</span>';
}

function addTunerScheduleRow() {
    _tunerRules.schedules = _tunerRules.schedules || [];
    _tunerRules.schedules.push({ start: '01:00', end: '08:00', days: [0, 1, 2, 3, 4, 5, 6], mode: 'performance' });
    renderTunerSchedules();
}

async function loadRunningProcessesPicker() {
    const box = document.getElementById('tr-proc-picker');
    if (!box) return;
    box.classList.remove('hidden'); box.innerHTML = '<span class="lbl-xs muted-text">⏳ Сканирую процессы...</span>';
    const res = await api('/api/tuner/processes');
    if (!res.ok) return;
    const list = (await res.json()).processes || [];
    box.innerHTML = list.map(p => `<button type="button" class="btn btn-secondary btn-xs" onclick="appendProcessToWatchlist('${escapeHtml(p)}')">+ ${escapeHtml(p)}</button>`).join('');
}

function appendProcessToWatchlist(name) {
    const inp = document.getElementById('tr-proc-names');
    const cur = inp.value.split(',').map(x => x.trim()).filter(Boolean);
    if (!cur.some(x => x.toLowerCase() === name.toLowerCase())) { cur.push(name); inp.value = cur.join(', '); }
}

async function saveTunerRules() {
    const iv = id => parseInt(document.getElementById(id)?.value) || 0;
    const cb = id => Boolean(document.getElementById(id)?.checked);
    const rules = {
        default_mode: document.getElementById('tr-def-mode')?.value || 'performance',
        override_policy: document.getElementById('tr-ov-policy')?.value || '2h',
        schedules: _tunerRules.schedules || [],
        processes: {
            enabled: cb('tr-proc-en'), target_mode: document.getElementById('tr-proc-mode')?.value || 'comfort',
            names: (document.getElementById('tr-proc-names')?.value || '').split(',').map(x => x.trim()).filter(Boolean),
            enter_sec: iv('tr-proc-enter'), exit_sec: iv('tr-proc-exit')
        },
        external_load: {
            enabled: cb('tr-ext-en'), target_mode: document.getElementById('tr-ext-mode')?.value || 'comfort',
            cpu_warn: iv('tr-ext-cpu-w'), cpu_recover: iv('tr-ext-cpu-r'),
            net_warn_pct: iv('tr-ext-net-w'), net_recover_pct: iv('tr-ext-net-r'),
            ram_min_free: iv('tr-ext-ram-w'), ram_recover_free: iv('tr-ext-ram-r'),
            enter_sec: iv('tr-ext-enter'), exit_sec: iv('tr-ext-exit')
        }
    };
    const res = await api('/api/tuner/rules', 'POST', { rules });
    if (res.ok) { _tunerRules = (await res.json()).rules; alert('✅ Правила автопереключения сохранены'); }
}

setInterval(() => {
    if (!document.hidden && (typeof CURRENT_ROLE === 'undefined' || CURRENT_ROLE === 'admin')) refreshTunerState();
}, 10000);
