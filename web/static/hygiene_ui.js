// web/static/hygiene_ui.js
let _hygieneTorItems = [];
let _hygienePathItems = [];
let _hygieneMode = 'quarantine';
let _pathMode = 'bt_backup';

async function runHygieneTorrentScan(mode) {
    _hygieneMode = mode;
    const tbody = document.getElementById('hyg-tor-tbody');
    const summary = document.getElementById('hyg-tor-summary');
    const delBtn = document.getElementById('btn-hyg-tor-trash');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="4" class="center-msg">⏳ Сканирование...</td></tr>';
    if (delBtn) delBtn.classList.add('hidden');

    let url = '/api/hygiene/quarantine?hours=72&tag=1';
    if (mode === 'incompletes') url = '/api/hygiene/incompletes?days=14';
    if (mode === 'dead_weight') url = '/api/hygiene/dead_weight?days=30&min_seeds=10';

    const res = await api(url);
    const d = await res.json();
    if (!res.ok || !d.success) {
        summary.textContent = d.error || 'Ошибка';
        tbody.innerHTML = '';
        return;
    }
    _hygieneTorItems = d.items || [];
    summary.textContent = `Найдено: ${_hygieneTorItems.length}`;
    if (!_hygieneTorItems.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="center-msg accent-txt">🎉 Чисто! Кандидатов не найдено.</td></tr>';
        return;
    }
    if (delBtn) delBtn.classList.remove('hidden');
    tbody.innerHTML = _hygieneTorItems.map((it, idx) => {
        const meta = mode === 'quarantine'
            ? `Ошибка ${it.elapsed_hours}ч: ${escapeHtml(it.error_msg)}`
            : (mode === 'incompletes' ? `${it.progress_pct}% • Avail: ${it.availability} • ${it.idle_days}д` : `Сиды: ${it.seeds} • Простой: ${it.idle_days}д • Ratio: ${it.ratio}x`);
        return `
            <tr>
                <td><input type="checkbox" class="hyg-tor-chk" data-idx="${idx}"></td>
                <td style="white-space:normal;"><b>${escapeHtml(it.name)}</b><div class="lbl-xs muted-text">${meta}</div></td>
                <td><b>${escapeHtml(it.size_fmt)}</b></td>
                <td><span class="badge ${it.ready ? 'badge-err' : 'badge-stall'}">${mode}</span></td>
            </tr>
        `;
    }).join('');
}

async function deleteSelectedHygieneTorrents() {
    const chosen = [...document.querySelectorAll('.hyg-tor-chk:checked')].map(c => _hygieneTorItems[parseInt(c.dataset.idx)]).filter(Boolean);
    if (!chosen.length) return alert('Отметьте хотя бы одну раздачу');
    if (!confirm(`Удалить из qBittorrent (${chosen.length} шт.) и переместить файлы в корзину _tbr_trash?`)) return;
    if (!confirm('Подтвердите повторно перенос выбранных раздач в _tbr_trash:')) return;
    const res = await api('/api/hygiene/delete_torrents_soft', 'POST', { items: chosen });
    const d = await res.json();
    alert(`Перенесено в корзину: ${d.removed || 0}`);
    runHygieneTorrentScan(_hygieneMode);
    if (typeof loadTrashItems === 'function') loadTrashItems();
}

async function runHygienePathScan(mode) {
    _pathMode = mode;
    const tbody = document.getElementById('hyg-path-tbody');
    const summary = document.getElementById('hyg-path-summary');
    const delBtn = document.getElementById('btn-hyg-path-trash');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="4" class="center-msg">⏳ Сканирование...</td></tr>';
    if (delBtn) delBtn.classList.add('hidden');

    const res = await api(mode === 'bt_backup' ? '/api/hygiene/bt_backup' : '/api/hygiene/inner_junk');
    const d = await res.json();
    if (!res.ok || !d.success) {
        summary.textContent = d.error || 'Ошибка';
        tbody.innerHTML = '';
        return;
    }
    _hygienePathItems = d.items || [];
    summary.textContent = `Найдено: ${_hygienePathItems.length}`;
    if (!_hygienePathItems.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="center-msg accent-txt">🎉 Лишних файлов не найдено!</td></tr>';
        return;
    }
    if (delBtn) delBtn.classList.remove('hidden');
    tbody.innerHTML = _hygienePathItems.map((it, idx) => `
        <tr>
            <td><input type="checkbox" class="hyg-path-chk" data-idx="${idx}"></td>
            <td style="white-space:normal;"><b>${escapeHtml(it.name)}</b><div class="lbl-xs muted-text">${escapeHtml(it.torrent_name || it.path)}</div></td>
            <td><span class="badge badge-stall">${escapeHtml(it.reason || it.category)}</span></td>
            <td><b>${escapeHtml(it.size_fmt)}</b></td>
        </tr>
    `).join('');
}

async function trashSelectedHygienePaths() {
    const paths = [...document.querySelectorAll('.hyg-path-chk:checked')].map(c => _hygienePathItems[parseInt(c.dataset.idx)]?.path).filter(Boolean);
    if (!paths.length) return alert('Отметьте файлы');
    if (!confirm(`Переместить выбранные файлы (${paths.length} шт.) в _tbr_trash?`)) return;
    const res = await api('/api/hygiene/trash_paths', 'POST', { paths, reason: _pathMode });
    const d = await res.json();
    alert(`Перенесено в корзину: ${d.moved || 0}`);
    runHygienePathScan(_pathMode);
    if (typeof loadTrashItems === 'function') loadTrashItems();
}

async function syncTorrentArchive() {
    const res = await api('/api/archive/sync', 'POST');
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка');
    alert(`✅ Архив синхронизирован! Новых: ${d.added}, всего: ${d.total}`);
    loadArchivedTorrents();
}

async function loadArchivedTorrents() {
    const tbody = document.getElementById('archive-tbody');
    if (!tbody) return;
    const q = document.getElementById('archive-search')?.value || '';
    const tag = document.getElementById('archive-tag')?.value || '';
    const res = await api(`/api/archive/list?q=${encodeURIComponent(q)}&tag=${encodeURIComponent(tag)}`);
    if (!res.ok) return;
    const items = (await res.json()).items || [];
    if (!items.length) { tbody.innerHTML = '<tr><td colspan="3" class="center-msg">Архив пуст</td></tr>'; return; }
    tbody.innerHTML = items.slice(0, 100).map(it => `
        <tr>
            <td style="white-space:normal;"><b>${escapeHtml(it.name)}</b><div class="lbl-xs muted-text">UID: ${escapeHtml(it.uid.slice(0, 10))} • ${escapeHtml(it.tags || 'без тегов')}</div></td>
            <td>${escapeHtml(it.gz_fmt)}</td>
            <td><a class="btn btn-secondary btn-xs" href="/api/archive/download?hash=${encodeURIComponent(it.hash_id)}">⬇️ .torrent</a></td>
        </tr>
    `).join('');
}

function downloadArchiveZip() {
    const tag = document.getElementById('archive-tag')?.value.trim() || '';
    window.location.href = `/api/archive/export_zip?tag=${encodeURIComponent(tag)}`;
}

async function previewBatchTrackers() {
    const find = document.getElementById('batch-tr-find').value;
    const replace = document.getElementById('batch-tr-rep').value;
    const out = document.getElementById('batch-op-out');
    out.textContent = '⏳ Поиск совпадений...';
    const res = await api('/api/batch/trackers/preview', 'POST', { find, replace });
    const d = await res.json();
    if (!d.success) { out.textContent = `❌ ${d.error}`; return; }
    out.textContent = `Найдено URL: ${d.count}\n` + (d.matches || []).slice(0, 20).map(m => `${m.name}: ${m.old_url} → ${m.new_url}`).join('\n');
}

async function applyBatchTrackers() {
    const find = document.getElementById('batch-tr-find').value;
    const replace = document.getElementById('batch-tr-rep').value;
    if (!confirm('Применить замену URL трекеров в qBittorrent?')) return;
    const res = await api('/api/batch/trackers/apply', 'POST', { find, replace });
    const d = await res.json();
    document.getElementById('batch-op-out').textContent = d.success ? `✅ Обновлено URL: ${d.updated} из ${d.total}` : `❌ ${d.error}`;
}

async function previewBatchRelocate() {
    const old_prefix = document.getElementById('batch-rel-old').value;
    const new_prefix = document.getElementById('batch-rel-new').value;
    const out = document.getElementById('batch-op-out');
    const res = await api('/api/batch/relocate/preview', 'POST', { old_prefix, new_prefix });
    const d = await res.json();
    if (!d.success) { out.textContent = `❌ ${d.error}`; return; }
    out.textContent = `Раздач: ${d.count} | Нужно места: ${d.need_fmt} | Свободно: ${d.free_fmt} (${d.space_ok ? 'ОК' : 'МАЛО МЕСТА!'})\n` +
        (d.items || []).slice(0, 20).map(i => `${i.old_path} → ${i.new_path}`).join('\n');
}

async function startBatchRelocate() {
    const old_prefix = document.getElementById('batch-rel-old').value;
    const new_prefix = document.getElementById('batch-rel-new').value;
    if (!confirm('Запустить фоновый пакетный переезд раздач в qBittorrent?')) return;
    const res = await api('/api/batch/relocate/start', 'POST', { old_prefix, new_prefix });
    const d = await res.json();
    document.getElementById('batch-op-out').textContent = d.success ? `🚀 В очереди переезда: ${d.queued} раздач` : `❌ ${d.error}`;
}

async function previewBatchRemap() {
    const old_prefix = document.getElementById('batch-rem-old').value;
    const new_prefix = document.getElementById('batch-rem-new').value;
    const res = await api('/api/batch/remap/preview', 'POST', { old_prefix, new_prefix });
    const d = await res.json();
    document.getElementById('batch-op-out').textContent = d.success
        ? `Найдено .fastresume: ${d.count} (qB запущен: ${d.qb_running ? 'ДА — остановите перед записью!' : 'НЕТ'})\n` + (d.items || []).slice(0, 20).map(i => `${i.old_path} → ${i.new_path}`).join('\n')
        : `❌ ${d.error}`;
}

async function applyBatchRemap() {
    const old_prefix = document.getElementById('batch-rem-old').value;
    const new_prefix = document.getElementById('batch-rem-new').value;
    if (!confirm('Переписать save_path в локальных .fastresume файлах? (Снапшот будет создан автоматически)')) return;
    const res = await api('/api/batch/remap/apply', 'POST', { old_prefix, new_prefix });
    const d = await res.json();
    document.getElementById('batch-op-out').textContent = d.success ? `✅ Обновлено .fastresume: ${d.updated}` : `❌ ${d.error || (d.errors || []).join(', ')}`;
}