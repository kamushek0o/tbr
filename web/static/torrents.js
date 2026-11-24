// web/static/torrents.js
let torrentsData = [];
let visibleTorrents = [];
let currentSortCol = 'name';
let currentSortAsc = true;
let selectedHash = null;
const selectedHashes = new Set();
let lastDeadHashes = [];
let trackerErrorsMap = {};

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
    if (document.getElementById('tab-merger').classList.contains('active') && typeof loadMergerLists === 'function') loadMergerLists();
    fetchTrackerErrorsAsync(force);
}

async function fetchTrackerErrorsAsync(force = false) {
    try {
        const res = await api(`/api/torrents/tracker_errors?force=${force ? '1' : '0'}`);
        if (res.ok) {
            trackerErrorsMap = (await res.json()).errors || {};
            filterTorrents();
        }
    } catch (e) {}
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
    ['name', 'size', 'uploaded', 'ratio', 'health_score', 'state', 'save_path'].forEach(c => {
        const el = document.getElementById('sort-icon-' + c);
        if (el) el.textContent = (c === currentSortCol) ? (currentSortAsc ? ' ▲' : ' ▼') : '';
    });
    torrentsData.sort((a, b) => {
        if (currentSortCol === 'health_score') {
            const ha = (a.health_score ?? -1), hb = (b.health_score ?? -1);
            if (ha < 0 && hb >= 0) return 1;
            if (hb < 0 && ha >= 0) return -1;
            return currentSortAsc ? (ha - hb) : (hb - ha);
        }
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
    const errF = (document.getElementById('filter-tracker-err-select')?.value || '').toLowerCase();

    visibleTorrents = torrentsData.filter(t => {
        if (q && !(t.name || '').toLowerCase().includes(q) && !(t.save_path || '').toLowerCase().includes(q)) return false;
        if (tagF && !(t.tags || '').toLowerCase().split(',').map(s => s.trim()).includes(tagF)) return false;
        if (trF && (t.tracker || '').toLowerCase() !== trF) return false;
        if (errF) {
            const errObj = trackerErrorsMap[t.hash.toLowerCase()];
            if (!errObj) return false;
            if (errF !== 'any' && errObj.category !== errF) return false;
        }
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

        const lastSeedHtml = item.is_last_seed ? ` <span class="badge badge-stall">🛡️ Единственный сид</span>` : '';
        const errInfo = trackerErrorsMap[item.hash.toLowerCase()];
        const errHtml = errInfo ? ` <span class="badge badge-err" title="${escapeHtml(errInfo.message)}">⚠️ ${escapeHtml(errInfo.category_label)}</span>` : '';
        const tgtBar = typeof renderTargetBarHtml === 'function' ? renderTargetBarHtml(item.target) : '';
        const healthHtml = (item.health_score === undefined || item.health_score < 0)
            ? `<span class="badge badge-pause">нет данных</span>`
            : `<span class="badge ${item.is_last_seed ? 'badge-stall' : (item.health_score >= 50 ? 'badge-up' : 'badge-dl')}" title="Сиды: ${item.num_complete} | Личи: ${item.num_incomplete}">💎 ${Number(item.health_score).toFixed(1)}</span>`;

        tr.insertAdjacentHTML('beforeend', `
            <td style="white-space:normal;"><strong>${escapeHtml(item.name)}</strong>${lastSeedHtml}${errHtml}${item.tags ? ` <span class="muted-text" style="font-size:10px;">[${escapeHtml(item.tags)}]</span>` : ''}${tgtBar}</td>
            <td>${escapeHtml(item.size_fmt)}</td>
            <td>${escapeHtml(item.uploaded_fmt)}</td>
            <td><strong class="accent-txt">${Number(item.ratio).toFixed(2)}x</strong></td>
            <td>${healthHtml}</td>
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

async function deleteSelectedTorrent() {
    if (!selectedHash) return alert(t('err_select_torrent'));
    const item = torrentsData.find(x => x.hash === selectedHash);
    if (item && item.is_last_seed) {
        if (!confirm(`🛡️ ПРЕДУПРЕЖДЕНИЕ!\nВы единственный раздающий этот файл в сети:\n«${item.name}»\n\nТочно перейти к удалению?`)) return;
    }
    if (!confirm(`Удалить раздачу «${item ? item.name : selectedHash}» из qBittorrent (файлы на диске останутся)?`)) return;
    const delFiles = confirm('Нажмите OK, чтобы также УДАЛИТЬ ФАЙЛЫ С ДИСКА, или Отмена — удалить только торрент из клиента.');
    const res = await api('/api/torrents/delete', 'POST', { hash: selectedHash, delete_files: delFiles });
    const d = await res.json();
    if (d.success) { selectedHash = null; loadTorrents(true); }
    else alert(d.error || 'Ошибка удаления');
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