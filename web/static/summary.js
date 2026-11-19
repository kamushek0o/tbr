// web/static/summary.js
let rawSummaryItems = [];
let filteredSummaryItems = [];
let summarySortCol = 'uploaded';
let summarySortAsc = false;
let lastSummaryMeta = null;
let selectedSummaryHash = null;
let _summaryLiveOnly = false;
let _summaryLastSeedOnly = false;
const _liveDecayMap = new Map();

function _renderNameWithBadges(i) {
    const lastBadge = i.is_last_seed ? ` <span class="badge badge-stall" title="Вы единственный раздающий в сети">🛡️ Единственный сид</span>` : '';
    const bar = typeof renderTargetBarHtml === 'function' ? renderTargetBarHtml(i.target) : '';
    return `<div><strong>${escapeHtml(i.name)}</strong>${lastBadge}${bar}</div>`;
}

function _renderHealthBadge(i) {
    if (i.health_score === undefined || i.health_score < 0) {
        return `<span class="badge badge-pause" title="Трекер не вернул статистику пиров">нет данных</span>`;
    }
    const cls = i.is_last_seed ? 'badge-stall' : (i.health_score >= 50 ? 'badge-up' : 'badge-dl');
    return `<span class="badge ${cls}" title="Сиды: ${i.num_complete} | Личи: ${i.num_incomplete}">💎 ${i.health_score.toFixed(1)}</span>`;
}

const SUMMARY_COLS = [
    { id: 'name', labelRu: 'Имя раздачи', labelEn: 'Torrent Name', render: _renderNameWithBadges },
    { id: 'size', labelRu: 'Размер', labelEn: 'Size', render: i => escapeHtml(formatBytesJS(i.size)) },
    { id: 'uploaded', labelRu: 'Отдано', labelEn: 'Uploaded', render: i => escapeHtml(formatBytesJS(i.uploaded)) },
    { id: 'ratio', labelRu: 'Ratio', labelEn: 'Ratio', render: i => `<strong class="accent-txt">${parseFloat(i.ratio || 0).toFixed(2)}x</strong>` },
    { id: 'health_score', labelRu: 'Ценность', labelEn: 'Health', render: _renderHealthBadge },
    { id: 'speed_all_time', labelRu: 'Ср. скорость', labelEn: 'Avg Speed', render: i => `<span class="blue-txt" style="font-weight:600;">${escapeHtml(i.speed_all_time_fmt)}</span>` },
    { id: 'speed_1h', labelRu: 'Скор. 1ч', labelEn: '1h Speed', render: i => `<span class="purple-txt" style="font-weight:600;">${escapeHtml(i.speed_1h_fmt)}</span>` },
    { id: 'speed_24h', labelRu: 'Скор. 24ч', labelEn: '24h Speed', render: i => `<span class="orange-txt" style="font-weight:600;">${escapeHtml(i.speed_24h_fmt)}</span>` },
    { id: 'vol_hour', labelRu: 'МБ/ч', labelEn: 'MB/h', render: i => `<span class="purple-txt" style="font-weight:700;">${escapeHtml(trBackend(i.vol_hour_fmt))}</span>` },
    { id: 'vol_day', labelRu: 'МБ/день', labelEn: 'MB/day', render: i => `<span class="orange-txt" style="font-weight:700;">${escapeHtml(trBackend(i.vol_day_fmt))}</span>` },
    { id: 'ratio_h_all', labelRu: 'Ratio/ч', labelEn: 'Ratio/h', render: i => `<span class="muted-text" style="font-size:11px;">${escapeHtml(trBackend(i.ratio_h_all_fmt))}</span>` },
    { id: 'created', labelRu: 'Дата', labelEn: 'Added', render: i => `<span class="muted-text" style="font-size:11px;">${escapeHtml(trBackend(i.created))}</span>` }
];

function getSummaryColPrefs() {
    const ui = typeof getUiSettings === 'function' ? getUiSettings() : {};
    const sc = ui.summary_columns || {};
    const allIds = SUMMARY_COLS.map(c => c.id);
    const order = (sc.order || allIds).filter(id => allIds.includes(id));
    allIds.forEach(id => { if (!order.includes(id)) order.push(id); });
    const visible = (sc.visible || allIds).filter(id => allIds.includes(id));
    if (!localStorage.getItem('tbr_seen_health_col') && !visible.includes('health_score')) {
        visible.push('health_score');
        localStorage.setItem('tbr_seen_health_col', '1');
    }
    return { order, visible: visible.length ? visible : ['name'], widths: sc.widths || {} };
}

function saveSummaryColPrefs(prefs) {
    const ui = getUiSettings();
    ui.summary_columns = prefs;
    if (typeof persistUiSettings === 'function') persistUiSettings(ui);
}

function toggleSummaryColsMenu() {
    const menu = document.getElementById('summary-cols-menu');
    if (!menu) return;
    if (!menu.classList.contains('hidden')) { menu.classList.add('hidden'); return; }
    const prefs = getSummaryColPrefs();
    const isEn = (typeof currentLang !== 'undefined' && currentLang === 'en');
    menu.innerHTML = '';
    SUMMARY_COLS.forEach(col => {
        const lbl = document.createElement('label');
        lbl.className = 'row-gap pointer lbl-xs';
        lbl.style.padding = '3px 0';
        const chk = document.createElement('input');
        chk.type = 'checkbox';
        chk.checked = prefs.visible.includes(col.id);
        chk.onchange = () => {
            const p = getSummaryColPrefs();
            if (chk.checked) { if (!p.visible.includes(col.id)) p.visible.push(col.id); }
            else { p.visible = p.visible.filter(x => x !== col.id); if (!p.visible.length) { chk.checked = true; return; } }
            saveSummaryColPrefs(p);
            applySummarySortAndRender();
        };
        lbl.appendChild(chk);
        lbl.appendChild(document.createTextNode(isEn ? col.labelEn : col.labelRu));
        menu.appendChild(lbl);
    });
    menu.classList.remove('hidden');
}

function toggleSummaryLiveFilter() {
    _summaryLiveOnly = !_summaryLiveOnly;
    const btn = document.getElementById('btn-live-filter');
    if (btn) btn.className = _summaryLiveOnly ? 'btn' : 'btn btn-secondary';
    applySummaryFilters();
}

function toggleSummaryLastSeedFilter() {
    _summaryLastSeedOnly = !_summaryLastSeedOnly;
    const btn = document.getElementById('btn-last-seed-filter');
    if (btn) btn.className = _summaryLastSeedOnly ? 'btn' : 'btn btn-secondary';
    applySummaryFilters();
}

async function loadSummary(force = false) {
    if (force) await api('/api/torrents/refresh', 'POST');
    const res = await api('/api/summary');
    const d = await res.json();
    lastSummaryMeta = d;
    renderSummaryMeta();

    rawSummaryItems = d.items || [];
    const nowMs = Date.now();
    rawSummaryItems.forEach(it => {
        const h = (it.hash_id || it.hash || '').toLowerCase();
        if (h && ((it.upspeed || 0) > 0 || (it.dlspeed || 0) > 0)) _liveDecayMap.set(h, nowMs);
    });

    if (typeof populateAnalyticsSelectors === 'function') populateAnalyticsSelectors();
    applySummaryFilters();
}

function renderSummaryMeta() {
    const d = lastSummaryMeta;
    if (!d) return;
    document.getElementById('sum-count').textContent = d.total_torrents;
    document.getElementById('sum-size').textContent = d.total_size_fmt;
    document.getElementById('sum-uploaded').textContent = d.total_uploaded_fmt;
    document.getElementById('sum-global-hour').textContent = trBackend(d.global_hour_volume_fmt || '-');
    document.getElementById('sum-global-hour-speed').textContent = d.global_hour_speed_fmt || '-';
    document.getElementById('sum-global-hour-note').textContent = trBackend(d.global_hour_note || '');
    document.getElementById('sum-global-day').textContent = trBackend(d.global_day_volume_fmt || '-');
    document.getElementById('sum-global-day-speed').textContent = d.global_day_speed_fmt || '-';
    document.getElementById('sum-ratio-h').textContent = `${trBackend(d.global_ratio_h_all_fmt)} / ${trBackend(d.global_ratio_h_day_fmt)}`;
    if (typeof renderUploadEquivalents === 'function') renderUploadEquivalents(d.total_uploaded);
}

function applySummaryFilters() {
    const q = (document.getElementById('sum-filter-search').value || '').toLowerCase();
    const minRatio = parseFloat(document.getElementById('sum-filter-ratio').value) || 0;
    const minUpGb = (parseFloat(document.getElementById('sum-filter-uploaded').value) || 0) * (1024 ** 3);
    const nowMs = Date.now();

    filteredSummaryItems = rawSummaryItems.filter(i => {
        if (q && !(i.name || '').toLowerCase().includes(q)) return false;
        if (minRatio > 0 && (i.ratio || 0) < minRatio) return false;
        if (minUpGb > 0 && (i.uploaded || 0) < minUpGb) return false;
        if (_summaryLastSeedOnly && !i.is_last_seed) return false;
        if (_summaryLiveOnly) {
            const h = (i.hash_id || i.hash || '').toLowerCase();
            const lastSeen = _liveDecayMap.get(h) || 0;
            if ((nowMs - lastSeen) > 45000) return false;
        }
        return true;
    });
    applySummarySortAndRender();
}

function resetSummaryFilters() {
    document.getElementById('sum-filter-search').value = '';
    document.getElementById('sum-filter-ratio').value = '';
    document.getElementById('sum-filter-uploaded').value = '';
    _summaryLiveOnly = false;
    _summaryLastSeedOnly = false;
    const b1 = document.getElementById('btn-live-filter');
    const b2 = document.getElementById('btn-last-seed-filter');
    if (b1) b1.className = 'btn btn-secondary';
    if (b2) b2.className = 'btn btn-secondary';
    applySummaryFilters();
}

function sortSummary(col) {
    if (summarySortCol === col) summarySortAsc = !summarySortAsc;
    else { summarySortCol = col; summarySortAsc = (col === 'name'); }
    applySummarySortAndRender();
}

function applySummarySortAndRender() {
    const scrollWrap = document.getElementById('summary-table-wrap');
    const prevTop = scrollWrap ? scrollWrap.scrollTop : 0;
    const prevLeft = scrollWrap ? scrollWrap.scrollLeft : 0;

    filteredSummaryItems.sort((a, b) => {
        if (summarySortCol === 'health_score') {
            const ha = (a.health_score ?? -1), hb = (b.health_score ?? -1);
            if (ha < 0 && hb >= 0) return 1;
            if (hb < 0 && ha >= 0) return -1;
            return summarySortAsc ? (ha - hb) : (hb - ha);
        }
        let vA = a[summarySortCol], vB = b[summarySortCol];
        if (summarySortCol === 'created') {
            vA = a.created_ts || parseDateToTs(a.created);
            vB = b.created_ts || parseDateToTs(b.created);
        } else {
            if (typeof vA === 'string') vA = vA.toLowerCase();
            if (typeof vB === 'string') vB = vB.toLowerCase();
        }
        return vA < vB ? (summarySortAsc ? -1 : 1) : (vA > vB ? (summarySortAsc ? 1 : -1) : 0);
    });

    const prefs = getSummaryColPrefs();
    const isEn = (typeof currentLang !== 'undefined' && currentLang === 'en');
    const isMobileCards = window.innerWidth <= 768 && document.body.classList.contains('mobile-cards-on');
    const activeCols = prefs.order.filter(id => prefs.visible.includes(id)).map(id => SUMMARY_COLS.find(c => c.id === id));

    const theadRow = document.getElementById('summary-thead-row');
    theadRow.innerHTML = '';
    let dragSrcId = null;

    activeCols.forEach(col => {
        const th = document.createElement('th');
        th.style.position = 'sticky';
        if (prefs.widths[col.id]) th.style.width = prefs.widths[col.id] + 'px';
        const arrow = (col.id === summarySortCol) ? (summarySortAsc ? ' ▲' : ' ▼') : '';
        th.textContent = (isEn ? col.labelEn : col.labelRu) + arrow;
        th.onclick = (e) => { if (!e.target.classList.contains('col-resizer')) sortSummary(col.id); };

        if (!isMobileCards) {
            th.draggable = true;
            th.ondragstart = () => { dragSrcId = col.id; };
            th.ondragover = (e) => e.preventDefault();
            th.ondrop = (e) => {
                e.preventDefault();
                if (!dragSrcId || dragSrcId === col.id) return;
                const p = getSummaryColPrefs();
                const fromIdx = p.order.indexOf(dragSrcId), toIdx = p.order.indexOf(col.id);
                if (fromIdx > -1 && toIdx > -1) {
                    p.order.splice(fromIdx, 1); p.order.splice(toIdx, 0, dragSrcId);
                    saveSummaryColPrefs(p); applySummarySortAndRender();
                }
            };
            const resizer = document.createElement('div');
            resizer.className = 'col-resizer';
            resizer.onmousedown = (e) => {
                e.stopPropagation(); e.preventDefault();
                const startX = e.pageX, startW = th.offsetWidth;
                const onMove = (ev) => { th.style.width = Math.max(60, startW + (ev.pageX - startX)) + 'px'; };
                const onUp = () => {
                    document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp);
                    const p = getSummaryColPrefs(); p.widths[col.id] = th.offsetWidth; saveSummaryColPrefs(p);
                };
                document.addEventListener('mousemove', onMove); document.addEventListener('mouseup', onUp);
            };
            th.appendChild(resizer);
        }
        theadRow.appendChild(th);
    });

    const tbody = document.getElementById('summary-tbody');
    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    filteredSummaryItems.forEach(i => {
        const tr = document.createElement('tr');
        const hId = i.hash_id || i.hash || '';
        if (selectedSummaryHash && hId === selectedSummaryHash) tr.classList.add('selected');
        tr.onclick = () => {
            selectedSummaryHash = hId;
            tbody.querySelectorAll('tr').forEach(r => r.classList.remove('selected'));
            tr.classList.add('selected');
        };
        activeCols.forEach(col => {
            const td = document.createElement('td');
            td.dataset.col = col.id;
            td.setAttribute('data-label', isEn ? col.labelEn : col.labelRu);
            td.innerHTML = col.render(i);
            tr.appendChild(td);
        });
        frag.appendChild(tr);
    });
    tbody.appendChild(frag);

    if (scrollWrap) { scrollWrap.scrollTop = prevTop; scrollWrap.scrollLeft = prevLeft; }
}

async function exportFilteredSummaryCSV() {
    const res = await api('/api/export_csv', 'POST', { items: filteredSummaryItems });
    if (!res.ok) return alert(t('export_err'));
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = window.URL.createObjectURL(blob);
    a.download = `summary_manual_${new Date().toLocaleString('sv-SE').replace(/[- :]/g, '_')}.csv`;
    a.click();
}

setInterval(() => {
    const tab = document.getElementById('tab-summary');
    if (tab && tab.classList.contains('active') && !document.hidden) loadSummary(false);
}, 5000);