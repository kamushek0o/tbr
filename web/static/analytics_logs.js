// web/static/analytics_logs.js
let dayLogsPage = 1;
let dayLogsTotalPages = 1;

async function loadTorrentHourlyHistory() {
    const hash = document.getElementById('history-torrent-select').value || 'all';
    const res = await api(`/api/analytics/history?hash=${encodeURIComponent(hash)}&limit=36`);
    const list = await res.json();
    const tbody = document.getElementById('torrent-history-tbody');
    tbody.innerHTML = '';
    if (!list.length) {
        tbody.innerHTML = `<tr><td colspan="4" class="center-msg">${t('no_hourly_snaps')}</td></tr>`;
        return;
    }
    const frag = document.createDocumentFragment();
    list.forEach(r => {
        const tr = document.createElement('tr');
        const intLbl = r.interval_min > 0 ? ` (${r.interval_min}м)` : '';
        tr.innerHTML = `
            <td>${escapeHtml(r.datetime)}</td>
            <td>${escapeHtml(r.uploaded_fmt)}</td>
            <td class="purple-txt" style="font-weight:700;">+${escapeHtml(trBackend(r.delta_mb))}<span class="muted-text" style="font-size:10px;">${intLbl}</span></td>
            <td class="blue-txt" style="font-weight:600;">${escapeHtml(r.speed_fmt)}</td>
        `;
        frag.appendChild(tr);
    });
    tbody.appendChild(frag);
}

async function initDayLogs() {
    const card = document.getElementById('admin-day-logs-card');
    if (!card) return;
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE === 'viewer') {
        card.classList.add('hidden');
        return;
    }
    try {
        const [canRes, daysRes] = await Promise.all([api('/api/logs/can_open_folder'), api('/api/logs/days')]);
        if (canRes.ok) {
            const d = await canRes.json();
            document.getElementById('btn-open-logs-folder')?.classList.toggle('hidden', !d.can_open);
        }
        if (daysRes.ok) {
            const dd = await daysRes.json();
            const sel = document.getElementById('logs-day-picker');
            if (sel) {
                sel.innerHTML = '';
                const ph = document.createElement('option');
                ph.value = ''; ph.textContent = `-- ${t('pick_day_hint')} --`;
                sel.appendChild(ph);
                (dd.days || []).forEach(day => {
                    const opt = document.createElement('option');
                    opt.value = day; opt.textContent = day;
                    sel.appendChild(opt);
                });
            }
        }
    } catch (e) {}
}

async function loadDayLogs(page = 1) {
    const picker = document.getElementById('logs-day-picker');
    const dateVal = picker ? picker.value : '';
    const dlBtn = document.getElementById('btn-dl-day-logs');
    if (!dateVal) {
        if (dlBtn) dlBtn.classList.add('hidden');
        return;
    }
    if (dlBtn) {
        dlBtn.href = `/api/logs/day/download?date=${encodeURIComponent(dateVal)}`;
        dlBtn.classList.remove('hidden');
    }

    const targetPage = Math.max(1, Math.min(dayLogsTotalPages || 1, page));
    const res = await api(`/api/logs/day?date=${encodeURIComponent(dateVal)}&page=${targetPage}&per_page=15`);
    if (!res.ok) return;
    const d = await res.json();
    dayLogsPage = d.page || 1;
    dayLogsTotalPages = d.total_pages || 1;
    document.getElementById('day-logs-page-info').textContent = `${dayLogsPage} / ${dayLogsTotalPages} (${d.total || 0})`;

    const tbody = document.getElementById('day-logs-tbody');
    tbody.innerHTML = '';
    if (!d.items || !d.items.length) {
        tbody.innerHTML = `<tr><td colspan="5" class="center-msg">${t('no_snaps_day')}</td></tr>`;
        return;
    }
    const frag = document.createDocumentFragment();
    d.items.forEach(r => {
        const isIgn = Boolean(r.ignore_in_stats);
        const tr = document.createElement('tr');
        if (isIgn) tr.style.cssText = 'opacity:0.45; text-decoration:line-through;';
        tr.innerHTML = `
            <td>${escapeHtml(r.datetime)}</td>
            <td class="accent-txt"><b>${escapeHtml(r.uploaded_fmt)}</b></td>
            <td>${escapeHtml(r.size_fmt)}</td>
            <td>${r.count}</td>
            <td>
                <button class="btn ${isIgn ? 'btn-secondary' : 'btn-danger'} btn-xs"
                        title="${isIgn ? 'Вернуть снимок в расчёты' : 'Исключить аномальный снимок из статистики'}"
                        onclick="toggleSnapshotIgnore(${r.id}, ${!isIgn})">${isIgn ? '♻️' : '🗑️'}</button>
            </td>
        `;
        frag.appendChild(tr);
    });
    tbody.appendChild(frag);
}

async function toggleSnapshotIgnore(snapId, ignored) {
    const msg = ignored
        ? 'Исключить этот снимок из статистики (графиков, рекордов и тепловой карты)?'
        : 'Вернуть этот снимок обратно в статистику?';
    if (!confirm(msg)) return;
    const res = await api('/api/logs/snapshot/ignore', 'POST', { id: snapId, ignored });
    const d = await res.json();
    if (!res.ok || !d.success) return alert(d.error || 'Ошибка');
    if (d.records && typeof _renderRecords === 'function') _renderRecords(d.records);
    loadDayLogs(dayLogsPage);
    if (typeof loadAnalyticsCharts === 'function') loadAnalyticsCharts();
}

async function openLogsFolderHost() {
    const res = await api('/api/logs/open_folder', 'POST');
    if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        alert(d.error || 'Недоступно');
    }
}