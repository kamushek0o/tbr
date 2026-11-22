// web/static/merger_tools.js
function onMergerSelectionChange() {
    updateMergerDiffBtn();
    updateMergerCalcPreview();
}

function updateMergerDiffBtn() {
    const oldH = document.getElementById('merger-old')?.value || '';
    const newH = document.getElementById('merger-new')?.value || '';
    const btn = document.getElementById('btn-merger-diff');
    if (btn) btn.disabled = (!oldH || !newH || oldH.toLowerCase() === newH.toLowerCase());
}

async function updateMergerCalcPreview() {
    const oldH = (document.getElementById('merger-old')?.value || '').toLowerCase();
    const newH = (document.getElementById('merger-new')?.value || '').toLowerCase();
    const mode = document.getElementById('merger-mode')?.value || 'add';
    const txtEl = document.getElementById('merger-calc-txt');
    const dupWarn = document.getElementById('merger-dup-warn');

    if (!txtEl) return;
    if (!oldH || !newH || oldH === newH) {
        txtEl.textContent = '—';
        if (dupWarn) dupWarn.classList.add('hidden');
        return;
    }

    const items = typeof torrentsData !== 'undefined' ? torrentsData : [];
    const src = items.find(x => x.hash.toLowerCase() === oldH);
    const dst = items.find(x => x.hash.toLowerCase() === newH);

    const srcUp = parseInt(src?.uploaded || 0);
    const dstUp = parseInt(dst?.uploaded || 0);

    if (mode === 'add') {
        const sumUp = srcUp + dstUp;
        txtEl.textContent = `${formatBytesJS(srcUp)} + ${formatBytesJS(dstUp)} = ${formatBytesJS(sumUp)}`;
    } else {
        txtEl.textContent = `${formatBytesJS(srcUp)} (перезапишет текущие ${formatBytesJS(dstUp)})`;
    }

    if (dupWarn) {
        try {
            const res = await api(`/api/merger/check_pair?old_hash=${encodeURIComponent(oldH)}&new_hash=${encodeURIComponent(newH)}`);
            const d = await res.json();
            dupWarn.classList.toggle('hidden', !(d && d.has_history));
        } catch (e) {
            dupWarn.classList.add('hidden');
        }
    }
}

async function loadSmartMatchCandidates() {
    const box = document.getElementById('smart-match-list');
    if (!box) return;
    box.innerHTML = '<span class="muted-text">⏳ Поиск кандидатов на объединение...</span>';
    try {
        const res = await api('/api/merger/candidates');
        if (!res.ok) {
            box.innerHTML = '<span class="muted-text">Ошибка подбора кандидатов</span>';
            return;
        }
        const d = await res.json();
        const list = d.candidates || [];
        if (!list.length) {
            box.innerHTML = '<span class="muted-text">Совпадающих пар для объединения не найдено.</span>';
            return;
        }
        box.innerHTML = '';
        const frag = document.createDocumentFragment();
        list.forEach(c => {
            const row = document.createElement('div');
            row.className = 'row-between';
            row.style.cssText = 'background:var(--bg-input); padding:6px 8px; border-radius:6px; gap:8px;';
            const sumBytes = (c.old_up_bytes || 0) + (c.new_up_bytes || 0);
            row.innerHTML = `
                <div style="min-width:0; flex:1;">
                    <div style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                        <b>${escapeHtml(c.old_name)}</b> <span class="muted-text">(${escapeHtml(c.old_up_fmt)})</span>
                        → <b>${escapeHtml(c.new_name)}</b> <span class="muted-text">(${escapeHtml(c.new_up_fmt)})</span>
                        <span class="accent-txt" style="font-weight:700;">[Σ ${formatBytesJS(sumBytes)}]</span>
                    </div>
                    <div class="lbl-xs muted-text">${escapeHtml(c.reason)}</div>
                </div>
                <button class="btn btn-xs" onclick="applySmartPair('${escapeHtml(c.old_hash)}', '${escapeHtml(c.new_hash)}')">Подставить</button>
            `;
            frag.appendChild(row);
        });
        box.appendChild(frag);
    } catch (e) {
        box.innerHTML = `<span class="muted-text">Ошибка: ${escapeHtml(e.message)}</span>`;
    }
}

function applySmartPair(oldHash, newHash) {
    const o = document.getElementById('merger-old');
    const n = document.getElementById('merger-new');
    if (o) o.value = oldHash;
    if (n) n.value = newHash;
    onMergerSelectionChange();
}

async function openTorrentDiffModal() {
    const oldH = document.getElementById('merger-old')?.value || '';
    const newH = document.getElementById('merger-new')?.value || '';
    if (!oldH || !newH || oldH.toLowerCase() === newH.toLowerCase()) return alert(t('err_same_torrent'));

    const modal = document.getElementById('diff-modal');
    const tbody = document.getElementById('diff-tbody');
    const badges = document.getElementById('diff-summary-badges');
    const matchBadge = document.getElementById('diff-match-badge');

    modal.style.display = 'flex';
    matchBadge.textContent = '⏳ Анализ...';
    badges.innerHTML = '';
    tbody.innerHTML = '<tr><td colspan="4" class="center-msg">⏳ Читаем списки файлов...</td></tr>';

    try {
        const res = await api(`/api/merger/diff?old_hash=${encodeURIComponent(oldH)}&new_hash=${encodeURIComponent(newH)}`);
        const d = await res.json();
        if (!res.ok || !d.success) {
            matchBadge.textContent = 'Ошибка';
            tbody.innerHTML = `<tr><td colspan="4" class="center-msg" style="color:var(--danger);">${escapeHtml(d.error || 'Ошибка анализа')}</td></tr>`;
            return;
        }
        matchBadge.textContent = `Совпадение: ${d.match_percent}%`;
        const st = d.stats || {};
        badges.innerHTML = `
            <span class="badge badge-up">✅ Совпадают: ${st.exact || 0}</span>
            <span class="badge badge-stall">⚠️ Размер изменён: ${st.changed || 0}</span>
            <span class="badge badge-stop">➖ Удалены: ${st.removed || 0}</span>
            <span class="badge badge-dl">➕ Новые: ${st.added || 0}</span>
            <span class="badge badge-pause">${escapeHtml(d.old_total_fmt)} → ${escapeHtml(d.new_total_fmt)}</span>
        `;
        const files = d.files || [];
        if (!files.length) { tbody.innerHTML = '<tr><td colspan="4" class="center-msg">Файлы не найдены</td></tr>'; return; }
        tbody.innerHTML = '';
        const frag = document.createDocumentFragment();
        const statusMap = { exact: { cls: 'diff-row-exact', badge: 'badge-up', txt: '100% ОК' }, changed: { cls: 'diff-row-changed', badge: 'badge-stall', txt: 'Размер ≠' }, removed: { cls: 'diff-row-removed', badge: 'badge-stop', txt: 'Удалён' }, added: { cls: 'diff-row-added', badge: 'badge-dl', txt: 'Новый' } };
        files.forEach(f => {
            const s = statusMap[f.status] || statusMap.exact;
            const tr = document.createElement('tr');
            tr.className = s.cls;
            tr.innerHTML = `<td style="white-space:normal; word-break:break-all;">${escapeHtml(f.path)}</td><td><span class="badge ${s.badge}">${s.txt}</span></td><td>${escapeHtml(f.old_size_fmt)}</td><td>${escapeHtml(f.new_size_fmt)}</td>`;
            frag.appendChild(tr);
        });
        tbody.appendChild(frag);
    } catch (e) {
        matchBadge.textContent = 'Ошибка';
        tbody.innerHTML = `<tr><td colspan="4" class="center-msg" style="color:var(--danger);">${escapeHtml(e.message)}</td></tr>`;
    }
}

function closeTorrentDiffModal() { document.getElementById('diff-modal').style.display = 'none'; }

async function scanOrphans() {
    const tbody = document.getElementById('orphan-tbody');
    const summary = document.getElementById('orphan-summary');
    const rootsInfo = document.getElementById('orphan-roots-info');
    const delBtn = document.getElementById('btn-delete-orphans');
    const custom = document.getElementById('orphan-custom-root')?.value.trim();

    summary.textContent = '⏳ Сканирование...';
    tbody.innerHTML = '<tr><td colspan="5" class="center-msg">⏳ Сверка файловой системы с торрентами...</td></tr>';
    delBtn.classList.add('hidden');

    try {
        const body = custom ? { roots: [custom] } : {};
        const res = await api('/api/tools/orphans/scan', 'POST', body);
        const d = await res.json();
        if (!res.ok || !d.success) {
            summary.textContent = 'Ошибка';
            tbody.innerHTML = `<tr><td colspan="5" class="center-msg" style="color:var(--danger);">${escapeHtml(d.error || 'Ошибка')}</td></tr>`;
            return;
        }
        rootsInfo.textContent = 'Проверенные каталоги: ' + ((d.roots || []).join(', ') || 'не найдены');
        summary.textContent = `Найдено: ${d.count} (${d.total_size_fmt})`;

        const list = d.orphans || [];
        if (!list.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="center-msg" style="color:var(--accent);">🎉 Лишних файлов и папок не найдено!</td></tr>';
            return;
        }
        tbody.innerHTML = '';
        const frag = document.createDocumentFragment();
        list.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><input type="checkbox" class="orphan-chk" value="${escapeHtml(item.path)}" onchange="updateOrphanDelBtn()"></td>
                <td style="white-space:normal; word-break:break-all;" title="${escapeHtml(item.path)}"><b>${escapeHtml(item.name)}</b><div class="lbl-xs muted-text">${escapeHtml(item.root)}</div></td>
                <td>${item.is_dir ? '📁 Папка' : '📄 Файл'}</td>
                <td><b>${escapeHtml(item.size_fmt)}</b></td>
                <td class="muted-text">${escapeHtml(item.date)}</td>
            `;
            frag.appendChild(tr);
        });
        tbody.appendChild(frag);
    } catch (e) {
        summary.textContent = 'Ошибка';
        tbody.innerHTML = `<tr><td colspan="5" class="center-msg" style="color:var(--danger);">${escapeHtml(e.message)}</td></tr>`;
    }
}

function toggleAllOrphans(master) {
    document.querySelectorAll('.orphan-chk').forEach(c => { c.checked = master.checked; });
    updateOrphanDelBtn();
}

function updateOrphanDelBtn() {
    const cnt = document.querySelectorAll('.orphan-chk:checked').length;
    const btn = document.getElementById('btn-delete-orphans');
    if (btn) {
        btn.classList.toggle('hidden', cnt === 0);
        btn.textContent = `🗑️ В корзину _tbr_trash (${cnt})`;
    }
}

async function deleteSelectedOrphans() {
    const paths = [...document.querySelectorAll('.orphan-chk:checked')].map(c => c.value);
    if (!paths.length) return;
    if (!confirm(`Переместить выбранные объекты (${paths.length} шт.) в корзину _tbr_trash?\n(Можно восстановить в течение 7 дней)`)) return;
    if (!confirm(`Подтвердите перенос ${paths.length} объектов в корзину _tbr_trash:`)) return;

    const custom = document.getElementById('orphan-custom-root')?.value.trim();
    const res = await api('/api/tools/orphans/delete', 'POST', {
        paths, confirmed: true, use_trash: true, custom_roots: custom ? [custom] : undefined
    });
    const d = await res.json();
    const msg = `Перенесено в _tbr_trash: ${(d.deleted || []).length}` + ((d.errors && d.errors.length) ? `\nОшибки:\n${d.errors.join('\n')}` : '');
    alert(msg);
    scanOrphans();
    if (typeof loadTrashItems === 'function') loadTrashItems();
}

async function loadVaultSettings() {
    const inp = document.getElementById('vault-tags-input');
    const sel = document.getElementById('vault-aggregate-mode');
    if (!inp || !sel) return;
    try {
        const res = await api('/api/vault/settings');
        if (!res.ok) return;
        const d = await res.json();
        inp.value = (d.tags || []).join(', ');
        sel.value = d.aggregate_mode || 'exclude';
    } catch (e) {}
}

async function saveVaultSettings() {
    const tags = document.getElementById('vault-tags-input')?.value || '';
    const aggregate_mode = document.getElementById('vault-aggregate-mode')?.value || 'exclude';
    const res = await api('/api/vault/settings', 'POST', { tags, aggregate_mode });
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка сохранения Private Vault');
    alert(`✅ Private Vault сохранён (${(d.tags || []).length} тегов).`);
}