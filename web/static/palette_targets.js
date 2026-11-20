// web/static/palette_targets.js
let _cmdItems = [];
let _cmdIdx = 0;
let _ftsDebounce = null;

function renderTargetBarHtml(target) {
    if (!target) return '';
    const pct = Math.min(100, Math.max(0, parseFloat(target.percent || 0)));
    const color = target.achieved ? 'var(--accent)' : 'var(--info)';
    const goalTxt = target.target_ratio > 0 ? `${target.target_ratio}x` : target.target_bytes_fmt;
    return `
        <div style="margin-top:4px; width:100%;">
            <div class="row-between lbl-xs muted-text" style="font-size:10px; margin-bottom:2px;">
                <span>🎯 Цель: ${escapeHtml(goalTxt)}</span>
                <span style="color:${color}; font-weight:700;">${pct}%</span>
            </div>
            <div style="height:4px; background:var(--bg-main); border-radius:2px; overflow:hidden;">
                <div style="height:100%; width:${pct}%; background:${color}; transition:width 0.25s;"></div>
            </div>
        </div>
    `;
}

function openCommandPalette() {
    const modal = document.getElementById('cmd-palette-modal');
    const inp = document.getElementById('cmd-palette-input');
    if (!modal || !inp) return;
    modal.style.display = 'flex';
    inp.value = '';
    _cmdIdx = 0;
    renderCommandPalette();
    inp.focus();
}

function closeCommandPalette() {
    const modal = document.getElementById('cmd-palette-modal');
    if (modal) modal.style.display = 'none';
}

function _buildCommandActions() {
    const actions = [
        { label: '⚡ Вкладка: Раздачи', run: () => switchTab('torrents') },
        { label: '📊 Вкладка: Сводка', run: () => switchTab('summary') },
        { label: '📈 Вкладка: Аналитика', run: () => switchTab('analytics') },
        { label: '🛠️ Вкладка: Инструменты', run: () => switchTab('tools') },
        { label: '🖥️ Режим Киоск (/kiosk)', run: () => window.open('/kiosk', '_blank') },
        { label: '🎨 Тема: Dark (Тёмная)', run: () => _quickSetTheme('dark') },
        { label: '☀️ Тема: Light (Светлая)', run: () => _quickSetTheme('light') },
        { label: '🖤 Тема: OLED (Чёрная)', run: () => _quickSetTheme('oled') },
    ];
    if (typeof CURRENT_ROLE === 'undefined' || CURRENT_ROLE === 'admin') {
        actions.push(
            { label: '🔀 Вкладка: Подменщик', run: () => switchTab('merger') },
            { label: '🤖 Вкладка: Автопилот', run: () => switchTab('automation') },
            { label: '❄️ Умная заморозка / Разморозка', run: () => toggleSmartFreeze() },
            { label: '😴 Таймер сна (Snooze)', run: () => openSnoozeModal() },
            { label: '🔄 Переиндексировать файлы FTS5', run: () => api('/api/search/reindex', 'POST', { force: false }).then(() => alert('✅ Индекс файлов обновлён')) },
            { label: '⚙️ Настройки системы', run: () => openSettingsModal() }
        );
    }
    return actions;
}

function _quickSetTheme(theme) {
    if (typeof getUiSettings === 'function' && typeof persistUiSettings === 'function') {
        const ui = getUiSettings();
        ui.theme = theme;
        persistUiSettings(ui);
    }
}

function renderCommandPalette(extraFiles = []) {
    const rawQ = (document.getElementById('cmd-palette-input')?.value || '').trim();
    const q = rawQ.toLowerCase();
    const listEl = document.getElementById('cmd-palette-list');
    if (!listEl) return;

    const actions = _buildCommandActions().filter(a => !q || a.label.toLowerCase().includes(q));
    const source = (typeof torrentsData !== 'undefined' && torrentsData.length)
        ? torrentsData : (typeof rawSummaryItems !== 'undefined' ? rawSummaryItems : []);

    const matchedTorrents = [];
    for (const item of source) {
        const nm = String(item.name || ''), hs = String(item.hash || item.hash_id || '');
        if (!q || nm.toLowerCase().includes(q) || hs.toLowerCase().includes(q)) {
            matchedTorrents.push({
                label: `📦 ${nm}`,
                sub: `${hs.slice(0, 10)} • ${item.uploaded_fmt || formatBytesJS(item.uploaded)}`,
                run: () => {
                    switchTab('torrents'); selectedHash = hs;
                    const t = torrentsData.find(x => x.hash === hs);
                    if (t) { document.getElementById('selected-title').textContent = `${t.name} (${t.size_fmt})`; renderTorrents(visibleTorrents); }
                }
            });
        }
        if (matchedTorrents.length >= 15) break;
    }

    const fileItems = extraFiles.map(f => ({
        label: `📄 ${f.file_path}`,
        sub: `${f.torrent_name} (${f.size_fmt})`,
        run: () => { switchTab('torrents'); selectedHash = f.hash; }
    }));

    _cmdItems = [...actions, ...matchedTorrents, ...fileItems].slice(0, 28);
    if (_cmdIdx >= _cmdItems.length) _cmdIdx = 0;

    listEl.innerHTML = '';
    if (!_cmdItems.length) { listEl.innerHTML = '<div class="center-msg muted-text">Ничего не найдено</div>'; return; }
    _cmdItems.forEach((it, idx) => {
        const row = document.createElement('div');
        row.className = 'row-between pointer';
        row.style.cssText = `padding:8px 10px; border-radius:6px; background:${idx === _cmdIdx ? 'rgba(46,204,113,0.18)' : 'var(--bg-input)'}; border:1px solid ${idx === _cmdIdx ? 'var(--accent)' : 'transparent'};`;
        row.innerHTML = `<span style="font-size:12.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(it.label)}</span>` +
            (it.sub ? `<span class="lbl-xs muted-text">${escapeHtml(it.sub)}</span>` : '');
        row.onclick = () => { closeCommandPalette(); it.run(); };
        listEl.appendChild(row);
    });

    if (!extraFiles.length && rawQ.length >= 3) {
        clearTimeout(_ftsDebounce);
        _ftsDebounce = setTimeout(async () => {
            try {
                const clean = rawQ.replace(/^file:/i, '').trim();
                if (clean.length < 2) return;
                const res = await api(`/api/search/files?q=${encodeURIComponent(clean)}`);
                if (res.ok && document.getElementById('cmd-palette-modal').style.display === 'flex') {
                    const files = (await res.json()).items || [];
                    if (files.length) renderCommandPalette(files);
                }
            } catch (e) {}
        }, 300);
    }
}

function onCmdPaletteKey(e) {
    if (e.key === 'Escape') { closeCommandPalette(); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); if (_cmdItems.length) _cmdIdx = (_cmdIdx + 1) % _cmdItems.length; renderCommandPalette(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); if (_cmdItems.length) _cmdIdx = (_cmdIdx - 1 + _cmdItems.length) % _cmdItems.length; renderCommandPalette(); }
    else if (e.key === 'Enter' && _cmdItems[_cmdIdx]) { e.preventDefault(); const c = _cmdItems[_cmdIdx]; closeCommandPalette(); c.run(); }
}

function openTargetModal() {
    if (typeof selectedHash === 'undefined' || !selectedHash) return alert(t('err_select_torrent'));
    const item = (typeof torrentsData !== 'undefined' ? torrentsData : []).find(x => x.hash === selectedHash);
    document.getElementById('tgt-torrent-name').textContent = item ? item.name : selectedHash;
    const tgt = item?.target || null;
    document.getElementById('tgt-ratio').value = tgt && tgt.target_ratio > 0 ? tgt.target_ratio : '';
    document.getElementById('tgt-gib').value = tgt && tgt.target_bytes > 0 ? Math.round(tgt.target_bytes / (1024 ** 3)) : '';
    document.getElementById('btn-tgt-remove').classList.toggle('hidden', !tgt);
    document.getElementById('target-modal').style.display = 'flex';
}
function closeTargetModal() { document.getElementById('target-modal').style.display = 'none'; }

async function saveTargetForSelected() {
    const tr = parseFloat(document.getElementById('tgt-ratio').value) || 0, gib = parseFloat(document.getElementById('tgt-gib').value) || 0;
    const res = await api('/api/targets/set', 'POST', { hash: selectedHash, target_ratio: tr, target_bytes: gib > 0 ? Math.round(gib * (1024 ** 3)) : 0 });
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка');
    closeTargetModal(); loadTorrents(false);
}

async function removeTargetForSelected() {
    const res = await api('/api/targets/delete', 'POST', { hash: selectedHash });
    if (res.ok) { closeTargetModal(); loadTorrents(false); }
}