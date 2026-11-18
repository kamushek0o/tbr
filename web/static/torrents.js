// web/static/torrents.js
let torrentsData = [];
let visibleTorrents = [];
let currentSortCol = 'name';
let currentSortAsc = true;
let selectedHash = null;
const selectedHashes = new Set();
let lastDeadHashes = [];

const STATUS_MAP = {
    'downloading': { key: 'st_downloading', badge: 'badge-dl' },
    'seeding': { key: 'st_seeding', badge: 'badge-up' },
    'uploading': { key: 'st_seeding', badge: 'badge-up' },
    'stalledup': { key: 'st_stalledup', badge: 'badge-stall' },
    'stalleddl': { key: 'st_stalleddl', badge: 'badge-stall' },
    'pausedup': { key: 'st_pausedup', badge: 'badge-pause' },
    'pauseddl': { key: 'st_pauseddl', badge: 'badge-pause' },
    'stoppedup': { key: 'st_stoppedup', badge: 'badge-stop' },
    'stoppeddl': { key: 'st_stoppeddl', badge: 'badge-stop' },
    'forcedup': { key: 'st_forcedup', badge: 'badge-force' },
    'forceddl': { key: 'st_forceddl', badge: 'badge-force' },
    'checkingup': { key: 'st_checking', badge: 'badge-pause' },
    'checkingdl': { key: 'st_checking', badge: 'badge-pause' },
    'queuedup': { key: 'st_queued', badge: 'badge-pause' },
    'queueddl': { key: 'st_queued', badge: 'badge-pause' },
    'error': { key: 'st_error', badge: 'badge-err' },
    'missingfiles': { key: 'st_missing', badge: 'badge-err' },
    'moving': { key: 'st_moving', badge: 'badge-dl' },
    'unknown': { key: 'st_unknown', badge: 'badge-up' }
};

async function loadTorrents(force = false) {
    if (force) await api('/api/torrents/refresh', 'POST');
    const res = await api('/api/torrents');
    const json = await res.json();
    torrentsData = json.torrents || [];
    populateTorrentFilters();
    checkQbStatus();
    applySortAndRender();
    if (document.getElementById('tab-merger').classList.contains('active')) loadMergerLists();
}

function populateTorrentFilters() {
    const tagSel = document.getElementById('filter-tag-select');
    const trSel = document.getElementById('filter-tracker-select');
    if (!tagSel || !trSel) return;
    const curTag = tagSel.value, curTr = trSel.value;
    const tags = new Set(), trackers = new Set();
    torrentsData.forEach(t => {
        if (t.tags) t.tags.split(',').map(s => s.trim()).filter(Boolean).forEach(s => tags.add(s));
        if (t.tracker) trackers.add(t.tracker);
    });
    tagSel.innerHTML = '<option value="">Все теги</option>';
    [...tags].sort().forEach(tg => { const o = document.createElement('option'); o.value = tg; o.textContent = `🏷️ ${tg}`; tagSel.appendChild(o); });
    tagSel.value = curTag;

    trSel.innerHTML = '<option value="">Все трекеры</option>';
    [...trackers].sort().forEach(tr => { const o = document.createElement('option'); o.value = tr; o.textContent = tr; trSel.appendChild(o); });
    trSel.value = curTr;
}

function sortTable(col) {
    if (currentSortCol === col) currentSortAsc = !currentSortAsc;
    else { currentSortCol = col; currentSortAsc = (col === 'name' || col === 'save_path'); }
    applySortAndRender();
}

function applySortAndRender() {
    ['name', 'size', 'uploaded', 'ratio', 'state', 'save_path'].forEach(c => {
        const el = document.getElementById('sort-icon-' + c);
        if (el) el.textContent = (c === currentSortCol) ? (currentSortAsc ? ' ▲' : ' ▼') : '';
    });
    torrentsData.sort((a, b) => {
        let vA = a[currentSortCol], vB = b[currentSortCol];
        if (typeof vA === 'string') vA = vA.toLowerCase();
        if (typeof vB === 'string') vB = vB.toLowerCase();
        return vA < vB ? (currentSortAsc ? -1 : 1) : (vA > vB ? (currentSortAsc ? 1 : -1) : 0);
    });
    filterTorrents();
}

function filterTorrents() {
    const q = (document.getElementById('search-box').value || '').toLowerCase();
    const tagF = (document.getElementById('filter-tag-select')?.value || '').toLowerCase();
    const trF = (document.getElementById('filter-tracker-select')?.value || '').toLowerCase();
    visibleTorrents = torrentsData.filter(t => {
        if (q && !(t.name || '').toLowerCase().includes(q) && !(t.save_path || '').toLowerCase().includes(q)) return false;
        if (tagF && !(t.tags || '').toLowerCase().split(',').map(s => s.trim()).includes(tagF)) return false;
        if (trF && (t.tracker || '').toLowerCase() !== trF) return false;
        return true;
    });
    renderTorrents(visibleTorrents);
}

function renderTorrents(list) {
    const tbody = document.getElementById('torrents-tbody');
    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    list.forEach(item => {
        const tr = document.createElement('tr');
        if (item.hash === selectedHash) tr.classList.add('selected');
        tr.addEventListener('click', e => {
            if (e.target.type === 'checkbox') return;
            selectTorrent(item, tr);
        });
        const st = STATUS_MAP[(item.state || '').toLowerCase()] || STATUS_MAP['unknown'];
        const chk = document.createElement('input');
        chk.type = 'checkbox';
        chk.checked = selectedHashes.has(item.hash);
        chk.onchange = () => {
            if (chk.checked) selectedHashes.add(item.hash);
            else selectedHashes.delete(item.hash);
            updateBulkSelectionUI();
        };
        const tdChk = document.createElement('td');
        tdChk.appendChild(chk);
        tr.appendChild(tdChk);
        tr.insertAdjacentHTML('beforeend', `
            <td><strong>${escapeHtml(item.name)}</strong>${item.tags ? ` <span class="muted-text" style="font-size:10px;">[${escapeHtml(item.tags)}]</span>` : ''}</td>
            <td>${escapeHtml(item.size_fmt)}</td>
            <td>${escapeHtml(item.uploaded_fmt)}</td>
            <td><strong class="accent-txt">${Number(item.ratio).toFixed(2)}x</strong></td>
            <td><span class="badge ${st.badge}">${t(st.key)}</span></td>
            <td class="muted-text" style="font-size:11px;">${escapeHtml(item.save_path)}</td>
        `);
        frag.appendChild(tr);
    });
    tbody.appendChild(frag);
    updateBulkSelectionUI();
}

function toggleSelectAllVisible(masterChk) {
    visibleTorrents.forEach(item => {
        if (masterChk.checked) selectedHashes.add(item.hash);
        else selectedHashes.delete(item.hash);
    });
    renderTorrents(visibleTorrents);
}

function updateBulkSelectionUI() {
    const bar = document.getElementById('bulk-actions-bar');
    const cnt = document.getElementById('bulk-selected-count');
    if (cnt) cnt.textContent = selectedHashes.size;
    if (bar) bar.classList.toggle('hidden', selectedHashes.size === 0);
}

async function bulkTorrentAction(action) {
    if (!selectedHashes.size) return;
    let tag = '';
    if (action === 'addTags' || action === 'removeTags') {
        tag = prompt(action === 'addTags' ? 'Введите тег для добавления:' : 'Введите тег для удаления:');
        if (!tag || !tag.trim()) return;
    }
    const res = await api('/api/torrents/action', 'POST', { hash: [...selectedHashes].join('|'), action, tag: tag.trim() });
    const d = await res.json();
    if (!d.success && d.error) alert(d.error);
    loadTorrents(true);
}

function selectTorrent(item, tr) {
    selectedHash = item.hash;
    document.querySelectorAll('#torrents-tbody tr').forEach(r => r.classList.remove('selected'));
    if (tr) tr.classList.add('selected');
    document.getElementById('selected-title').textContent = `${item.name} (${item.size_fmt})`;
}

async function torrentAction(action) {
    if (!selectedHash) return alert(t('err_select_torrent'));
    const res = await api('/api/torrents/action', 'POST', { hash: selectedHash, action });
    const d = await res.json();
    if (!d.success && d.error) alert(d.error);
    loadTorrents();
}

async function globalTorrentAction(action) {
    const msg = action === 'stop' ? t('confirm_pause_all') : t('confirm_start_all');
    if (!confirm(msg)) return;
    const res = await api('/api/torrents/action_all', 'POST', { action });
    const d = await res.json();
    alert(d.message || d.error);
    loadTorrents();
}

function goToAnalyticsWithTorrent() {
    if (!selectedHash) return alert(t('err_select_torrent_tbl'));
    switchTab('analytics');
    setTimeout(() => {
        const sel = document.getElementById('smart-calc-target-type');
        sel.value = selectedHash;
        onSmartCalcTargetChange();
        document.getElementById('smart-calc-goal').focus();
    }, 150);
}

async function scanDeadTorrents() {
    const modal = document.getElementById('dead-torrents-modal');
    const tbody = document.getElementById('dead-torrents-tbody');
    const badges = document.getElementById('dead-summary-badges');
    const pauseAllBtn = document.getElementById('btn-pause-all-dead');
    modal.style.display = 'flex';
    badges.innerHTML = `<span class="badge badge-pause">${t('dead_scanning_badge')}</span>`;
    tbody.innerHTML = `<tr><td colspan="4" class="center-msg">${t('scanning')}</td></tr>`;
    pauseAllBtn.classList.add('hidden');
    lastDeadHashes = [];
    try {
        const res = await api('/api/torrents/scan_dead', 'POST');
        const d = await res.json();
        if (!res.ok || !d.success) { badges.innerHTML = ''; tbody.innerHTML = `<tr><td colspan="4" class="center-msg" style="color:var(--danger);">${escapeHtml(d.error || 'Error')}</td></tr>`; return; }
        badges.innerHTML = `<span class="badge badge-dl">${t('dead_scanned', { n: d.total_scanned })}</span><span class="badge ${d.dead_count > 0 ? 'badge-err' : 'badge-up'}">${t('dead_found', { n: d.dead_count })}</span>`;
        (d.groups || []).forEach(g => { const sp = document.createElement('span'); sp.className = 'badge badge-stall'; sp.textContent = `${g.error_msg}: ${g.count}`; badges.appendChild(sp); });
        if (!d.items || !d.items.length) { tbody.innerHTML = `<tr><td colspan="4" class="center-msg" style="color:var(--accent);">${t('dead_none')}</td></tr>`; return; }
        lastDeadHashes = d.items.map(i => i.hash);
        pauseAllBtn.classList.remove('hidden');
        tbody.innerHTML = '';
        const frag = document.createDocumentFragment();
        d.items.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `<td style="max-width:260px; overflow:hidden; text-overflow:ellipsis;" title="${escapeHtml(item.name)}"><strong>${escapeHtml(item.name)}</strong></td><td>${escapeHtml(item.size_fmt)}</td><td><span class="badge badge-err">${escapeHtml(item.error_msg)}</span></td><td><button class="btn btn-secondary btn-xs" onclick="pauseSingleDead('${escapeHtml(item.hash)}', this)">${t('btn_pause')}</button></td>`;
            frag.appendChild(tr);
        });
        tbody.appendChild(frag);
    } catch (e) { badges.innerHTML = ''; tbody.innerHTML = `<tr><td colspan="4" class="center-msg" style="color:var(--danger);">${escapeHtml(e.message)}</td></tr>`; }
}

async function pauseSingleDead(hash, btn) {
    const res = await api('/api/torrents/action', 'POST', { hash, action: 'stop' });
    const d = await res.json();
    if (d.success) { btn.textContent = t('dead_paused'); btn.disabled = true; loadTorrents(); } else alert(d.error || 'Error');
}

async function pauseAllDeadTorrents() {
    if (!lastDeadHashes.length || !confirm(t('dead_pause_confirm', { n: lastDeadHashes.length }))) return;
    const res = await api('/api/torrents/action', 'POST', { hash: lastDeadHashes.join('|'), action: 'stop' });
    const d = await res.json();
    if (d.success) { alert(t('dead_paused_msg', { n: lastDeadHashes.length })); closeDeadModal(); loadTorrents(); } else alert(d.error || 'Error');
}

function closeDeadModal() { document.getElementById('dead-torrents-modal').style.display = 'none'; }

function loadMergerLists() {
    const o = document.getElementById('merger-old'), n = document.getElementById('merger-new');
    if (!torrentsData.length) { loadTorrents().then(() => loadMergerLists()); return; }
    o.innerHTML = ''; n.innerHTML = '';
    torrentsData.forEach(item => {
        const opt1 = document.createElement('option');
        opt1.value = item.hash; opt1.textContent = `${item.name} [${item.hash.substring(0, 8)}]`;
        o.appendChild(opt1); n.appendChild(opt1.cloneNode(true));
    });
    if (torrentsData.length > 1) n.selectedIndex = 1;
}

function onMergerDeleteModeChange() {
    document.getElementById('merger-force-warn').classList.toggle('hidden', document.getElementById('merger-delete-mode').value !== 'force');
}

async function runMerger() {
    const logBox = document.getElementById('merger-log');
    const old_hash = document.getElementById('merger-old').value, new_hash = document.getElementById('merger-new').value;
    const delete_mode = document.getElementById('merger-delete-mode').value || 'none';
    if (!old_hash || !new_hash) return alert(t('err_select_both'));
    if (old_hash.toLowerCase() === new_hash.toLowerCase()) return alert(t('err_same_torrent'));
    logBox.textContent = t('merger_running');
    const res = await api('/api/merger/run', 'POST', { old_hash, new_hash, delete_mode });
    const d = await res.json();
    logBox.textContent = (d.log || []).join('\n');
    if (d.success && d.needs_delete_confirm && d.confirm_info) {
        const ci = d.confirm_info;
        const msg = ci.method === 'disk_only' ? t('confirm_del_disk_only', { name: ci.old_name })
            : (ci.delete_files ? t('confirm_del_with_files', { name: ci.old_name })
                : (ci.downgraded ? t('confirm_del_downgraded', { name: ci.old_name }) : t('confirm_del_torrent_only', { name: ci.old_name })));
        if (confirm(msg)) {
            const delRes = await api('/api/merger/delete_source', 'POST', { old_hash, new_hash, delete_mode, confirmed: true });
            const delData = await delRes.json();
            logBox.textContent += '\n' + (delData.log || []).join('\n');
            loadTorrents(true);
        } else logBox.textContent += '\n' + t('del_cancelled');
    }
}