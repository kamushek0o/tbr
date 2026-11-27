// web/static/tuner_ui.js
let _tunerProfiles = [];
let _tunerCurProfileId = 'performance';
let _tunerAvailableDisks = [];
let _tunerState = {};

function getProfileLabel(pid) {
    const p = _tunerProfiles.find(x => x.id === pid);
    return p ? `${p.icon} ${p.name}` : pid;
}

function syncTunerDisabledStates() {
    const setGroupState = (chkId, rowId, inputIds) => {
        const en = Boolean(document.getElementById(chkId)?.checked);
        document.getElementById(rowId)?.classList.toggle('tuner-row-disabled', !en);
        inputIds.forEach(id => { const el = document.getElementById(id); if (el) el.disabled = !en; });
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
    const minEl = document.getElementById('tp-act-min'), maxEl = document.getElementById('tp-act-max');
    if (minEl) minEl.disabled = (actMode === 'keep');
    if (maxEl) maxEl.disabled = (actMode !== 'range');
    document.getElementById('wrap-tp-act-min')?.classList.toggle('tuner-row-disabled', actMode === 'keep');
    document.getElementById('wrap-tp-act-max')?.classList.toggle('tuner-row-disabled', actMode !== 'range');

    const ptUpAuto = Boolean(document.getElementById('tp-pt-up-auto')?.checked);
    ['tp-pt-up-min', 'tp-pt-up-max'].forEach(id => { const e = document.getElementById(id); if (e) e.disabled = ptUpAuto; });

    const mcAuto = Boolean(document.getElementById('tp-mc-auto')?.checked);
    ['tp-mc-min', 'tp-mc-max'].forEach(id => { const e = document.getElementById(id); if (e) e.disabled = mcAuto; });
}

function _renderProfileSelectors(activeMode) {
    const pills = document.getElementById('tuner-mode-pills');
    if (pills) {
        pills.innerHTML = `<button class="${activeMode === 'off' ? 'btn btn-xs' : 'btn btn-secondary btn-xs'}" onclick="setTunerMode('off')">Выкл</button>` +
            _tunerProfiles.map(p => `<button class="${activeMode === p.id ? 'btn btn-xs' : 'btn btn-secondary btn-xs'}" onclick="setTunerMode('${escapeHtml(p.id)}')">${escapeHtml(p.icon)} ${escapeHtml(p.name)}</button>`).join('');
    }
    const selEdit = document.getElementById('tp-profile-select');
    if (selEdit) {
        selEdit.innerHTML = _tunerProfiles.map(p => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.icon)} ${escapeHtml(p.name)}</option>`).join('');
        if (_tunerProfiles.some(p => p.id === _tunerCurProfileId)) selEdit.value = _tunerCurProfileId;
        else if (_tunerProfiles.length) _tunerCurProfileId = _tunerProfiles[0].id;
    }
    ['tr-def-profile', 'tr-f-target'].forEach(id => {
        const s = document.getElementById(id);
        if (!s) return;
        const cur = s.value;
        s.innerHTML = _tunerProfiles.map(p => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.icon)} ${escapeHtml(p.name)}</option>`).join('');
        if (cur && _tunerProfiles.some(p => p.id === cur)) s.value = cur;
    });
}

function _updateDiskSelectorOptions(selectedVal) {
    const sel = document.getElementById('tp-g-disk-target');
    if (!sel) return;
    sel.innerHTML = '';
    sel.add(new Option('Авто (по раздачам)', ''));
    sel.add(new Option('Все диски (Max)', 'ALL'));
    _tunerAvailableDisks.forEach(d => sel.add(new Option(`${d.path} (${d.free_fmt} своб.)`, d.path)));
    sel.value = selectedVal || '';
}

async function loadTunerTab() {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
    await refreshTunerState(true);
    if (typeof loadTunerRulesAndCatalog === 'function') await loadTunerRulesAndCatalog();
}

async function refreshTunerState(initEditors = false) {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
    try {
        const res = await api('/api/tuner/state');
        if (!res.ok) return;
        const d = await res.json();
        _tunerState = d.state || {};
        const tel = d.telemetry || {}, mode = _tunerState.mode || 'off';
        _tunerAvailableDisks = d.available_disks || [];
        if (Array.isArray(d.profiles)) _tunerProfiles = d.profiles;

        _renderProfileSelectors(mode);
        if (initEditors) {
            selectTunerProfile(_tunerCurProfileId);
            const pSec = document.getElementById('tr-poll-sec');
            if (pSec) pSec.value = _tunerState.poll_interval_sec || 3;
            const dSel = document.getElementById('tr-def-profile');
            if (dSel) dSel.value = _tunerState.default_profile_id || 'performance';
            const ovSel = document.getElementById('tr-ov-policy');
            if (ovSel) ovSel.value = _tunerState.manual_override_policy || '2h';
        }

        const chk = document.getElementById('tuner-auto-chk');
        if (chk) chk.checked = Boolean(_tunerState.auto_switch_enabled);

        const reason = d.switch_reason || _tunerState.last_reason || 'Выключен';
        const badge = document.getElementById('tuner-reason-badge');
        if (badge) {
            badge.textContent = reason;
            badge.className = mode === 'off' ? 'badge badge-pause' : 'badge badge-up';
        }
        const hb = document.getElementById('tuner-header-badge');
        if (hb) {
            hb.textContent = mode === 'off' ? '🎛️ Тюнер: Выкл' : `🎛️ ${getProfileLabel(mode)}`;
            hb.className = mode === 'off' ? 'badge badge-pause pointer admin-only' : 'badge badge-up pointer admin-only';
        }
        document.getElementById('tuner-btn-clear-ov')?.classList.toggle('hidden', !_tunerState.manual_override_mode);

        const setTxt = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
        setTxt('tel-disk-title', tel.monitored_disk_label ? `Загрузка диска (${tel.monitored_disk_label})` : 'Загрузка диска');
        setTxt('tel-disk', tel.psutil_available === false ? 'нет psutil' : `${tel.disk_busy ?? 0}%`);
        setTxt('tel-cpu', `${tel.cpu_ext ?? 0}%`);
        setTxt('tel-ram', `${tel.ram_free ?? 0}%`);
        setTxt('tel-chan', `${tel.channel_pct ?? 0}%`);
        setTxt('tel-net', `${tel.net_ext_pct ?? 0}%`);
        const curMu = (_tunerState.current_limits || {}).max_uploads || (_tunerState.baseline || {}).max_uploads || '—';
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
    const mode = auto_switch ? (_tunerState.default_profile_id || 'performance') : 'off';
    await api('/api/tuner/mode', 'POST', { mode, auto_switch, is_manual: false });
    refreshTunerState();
}

async function clearTunerOverride() {
    await api('/api/tuner/mode', 'POST', { mode: _tunerState.default_profile_id || 'performance', clear_override: true, is_manual: false });
    refreshTunerState();
}

async function restoreTunerBaseline() {
    if (!confirm('Выключить тюнер и вернуть исходные настройки qBittorrent?')) return;
    const res = await api('/api/tuner/restore_baseline', 'POST');
    alert((await res.json()).message || 'Готово');
    refreshTunerState();
}

async function saveTunerGlobalSettings() {
    const res = await api('/api/tuner/settings', 'POST', {
        poll_interval_sec: parseInt(document.getElementById('tr-poll-sec')?.value) || 3,
        default_profile_id: document.getElementById('tr-def-profile')?.value || 'performance',
        override_policy: document.getElementById('tr-ov-policy')?.value || '2h'
    });
    if (res.ok) { alert('✅ Общие настройки тюнера сохранены'); refreshTunerState(); }
}

function selectTunerProfile(pid) {
    _tunerCurProfileId = pid;
    const pObj = _tunerProfiles.find(x => x.id === pid);
    if (!pObj) return;
    const p = pObj.config || {}, g = p.guards || {};
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

function _collectProfileFormConfig() {
    const iv = id => parseInt(document.getElementById(id)?.value) || 0;
    const cb = id => Boolean(document.getElementById(id)?.checked);
    return {
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
            disk: { enabled: cb('tp-g-disk-en'), target_disk: document.getElementById('tp-g-disk-target')?.value || '', warn: iv('tp-g-disk-warn'), crit: iv('tp-g-disk-crit'), recover: iv('tp-g-disk-rec') },
            cpu:  { enabled: cb('tp-g-cpu-en'), warn: iv('tp-g-cpu-warn'), recover: iv('tp-g-cpu-rec') },
            ram:  { enabled: cb('tp-g-ram-en'), min_free: iv('tp-g-ram-min'), recover_free: iv('tp-g-ram-rec') },
            net:  { enabled: cb('tp-g-net-en'), warn_pct: iv('tp-g-net-warn'), recover_pct: iv('tp-g-net-rec') }
        }
    };
}

async function saveTunerProfile() {
    const pObj = _tunerProfiles.find(x => x.id === _tunerCurProfileId);
    if (!pObj) return;
    const res = await api('/api/tuner/profiles', 'POST', { id: pObj.id, name: pObj.name, icon: pObj.icon, config: _collectProfileFormConfig() });
    if (res.ok) { _tunerProfiles = (await res.json()).profiles || []; _renderProfileSelectors(_tunerState.mode || 'off'); alert(`✅ Профиль «${pObj.name}» сохранён`); }
}

async function createNewTunerProfile() {
    const name = prompt('Название нового профиля:');
    if (!name || !name.trim()) return;
    const icon = prompt('Иконка (эмодзи):', '⚙️') || '⚙️';
    const res = await api('/api/tuner/profiles', 'POST', { is_new: true, name: name.trim(), icon: icon.trim(), config: _collectProfileFormConfig() });
    if (res.ok) { const d = await res.json(); _tunerProfiles = d.profiles; _tunerCurProfileId = d.profile.id; _renderProfileSelectors(_tunerState.mode || 'off'); selectTunerProfile(_tunerCurProfileId); }
}

async function cloneTunerProfile() {
    const pObj = _tunerProfiles.find(x => x.id === _tunerCurProfileId);
    const name = prompt('Название копии профиля:', pObj ? `${pObj.name} (копия)` : 'Копия');
    if (!name || !name.trim()) return;
    const res = await api('/api/tuner/profiles', 'POST', { clone_from: _tunerCurProfileId, name: name.trim(), icon: pObj?.icon || '⚙️' });
    if (res.ok) { const d = await res.json(); _tunerProfiles = d.profiles; _tunerCurProfileId = d.profile.id; _renderProfileSelectors(_tunerState.mode || 'off'); selectTunerProfile(_tunerCurProfileId); }
}

async function renameTunerProfile() {
    const pObj = _tunerProfiles.find(x => x.id === _tunerCurProfileId);
    if (!pObj) return;
    const name = prompt('Новое название профиля:', pObj.name);
    if (!name || !name.trim()) return;
    const icon = prompt('Иконка (эмодзи):', pObj.icon) || pObj.icon;
    const res = await api('/api/tuner/profiles', 'POST', { id: pObj.id, name: name.trim(), icon: icon.trim(), config: _collectProfileFormConfig() });
    if (res.ok) { _tunerProfiles = (await res.json()).profiles; _renderProfileSelectors(_tunerState.mode || 'off'); selectTunerProfile(pObj.id); }
}

async function deleteTunerProfile() {
    const pObj = _tunerProfiles.find(x => x.id === _tunerCurProfileId);
    if (!pObj || !confirm(`Удалить профиль «${pObj.name}»?\n(Если к нему привязаны правила автопереключения, они будут отключены)`)) return;
    const res = await api('/api/tuner/profiles', 'POST', { delete_id: pObj.id });
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.message || 'Ошибка удаления');
    _tunerProfiles = d.profiles;
    _tunerCurProfileId = _tunerProfiles[0]?.id || 'performance';
    _renderProfileSelectors(_tunerState.mode || 'off');
    selectTunerProfile(_tunerCurProfileId);
    if (typeof loadTunerRulesAndCatalog === 'function') loadTunerRulesAndCatalog();
}

async function resetBuiltinTunerPresets() {
    if (!confirm('Восстановить 5 стандартных пресетов («Турбо / Ночь», «Производительность», «Баланс», «Игровой», «Тихий минимум»)? Пользовательские профили останутся на месте.')) return;
    const res = await api('/api/tuner/profiles', 'POST', { reset_builtins: true });
    if (res.ok) { _tunerProfiles = (await res.json()).profiles; _renderProfileSelectors(_tunerState.mode || 'off'); selectTunerProfile(_tunerCurProfileId); }
}

setInterval(() => {
    if (!document.hidden && (typeof CURRENT_ROLE === 'undefined' || CURRENT_ROLE === 'admin')) refreshTunerState(false);
}, 5000);
