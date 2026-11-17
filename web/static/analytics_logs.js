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
        tr.innerHTML = `
            <td>${escapeHtml(r.datetime)}</td>
            <td>${escapeHtml(r.uploaded_fmt)}</td>
            <td class="purple-txt" style="font-weight:700;">+${escapeHtml(trBackend(r.delta_mb))}</td>
            <td class="blue-txt" style="font-weight:600;">${escapeHtml(r.speed_fmt)}</td>
        `;
        frag.appendChild(tr);
    });
    tbody.appendChild(frag);
}

async function loadLogsList() {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE === 'viewer') return;
    const res = await api('/api/logs/list');
    if (!res.ok) return;
    const files = await res.json();
    const sel = document.getElementById('log-file-select');
    sel.innerHTML = '';

    const frag = document.createDocumentFragment();
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = t('select_log_ph');
    frag.appendChild(placeholder);

    files.forEach(f => {
        const opt = document.createElement('option');
        opt.value = f;
        opt.textContent = f;
        frag.appendChild(opt);
    });
    sel.appendChild(frag);

    document.getElementById('download-log-btn').classList.add('hidden');
    document.getElementById('log-view-terminal').textContent = t('log_view_hint');
}

function onLogSelectChange() {
    const name = document.getElementById('log-file-select').value;
    const dlBtn = document.getElementById('download-log-btn');
    if (!name) {
        dlBtn.classList.add('hidden');
        document.getElementById('log-view-terminal').textContent = t('log_view_hint');
        return;
    }
    dlBtn.href = `/api/logs/download?name=${encodeURIComponent(name)}`;
    dlBtn.classList.remove('hidden');
}

async function loadLogContent() {
    const name = document.getElementById('log-file-select').value;
    if (!name) return alert(t('err_select_file'));
    onLogSelectChange();
    const res = await api(`/api/logs/view?name=${encodeURIComponent(name)}`);
    const d = await res.json();
    document.getElementById('log-view-terminal').textContent = d.content || d.error || t('file_empty');
}

async function initDayLogs() {
    const card = document.getElementById('admin-day-logs-card');
    if (!card) return;
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE === 'viewer') {
        card.classList.add('hidden');
        return;
    }
    const picker = document.getElementById('logs-day-picker');
    if (picker && !picker.value) {
        picker.value = new Date().toLocaleString('sv-SE').slice(0, 10);
    }
    try {
        const res = await api('/api/logs/can_open_folder');
        if (res.ok) {
            const d = await res.json();
            document.getElementById('btn-open-logs-folder')?.classList.toggle('hidden', !d.can_open);
        }
    } catch (e) {}
    loadDayLogs(1);
}

async function loadDayLogs(page = 1) {
    const picker = document.getElementById('logs-day-picker');
    const dateVal = picker ? picker.value : '';
    const targetPage = Math.max(1, Math.min(dayLogsTotalPages || 1, page));
    const dlBtn = document.getElementById('btn-dl-day-logs');
    if (dlBtn && dateVal) dlBtn.href = `/api/logs/day/download?date=${encodeURIComponent(dateVal)}`;

    const res = await api(`/api/logs/day?date=${encodeURIComponent(dateVal)}&page=${targetPage}&per_page=15`);
    if (!res.ok) return;
    const d = await res.json();
    dayLogsPage = d.page || 1;
    dayLogsTotalPages = d.total_pages || 1;
    document.getElementById('day-logs-page-info').textContent = `${dayLogsPage} / ${dayLogsTotalPages} (${d.total || 0})`;

    const tbody = document.getElementById('day-logs-tbody');
    tbody.innerHTML = '';
    if (!d.items || !d.items.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="center-msg">Нет снимков за выбранный день</td></tr>';
        return;
    }
    const frag = document.createDocumentFragment();
    d.items.forEach(r => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${escapeHtml(r.datetime)}</td>
            <td class="accent-txt"><b>${escapeHtml(r.uploaded_fmt)}</b></td>
            <td>${escapeHtml(r.size_fmt)}</td>
            <td>${r.count}</td>
        `;
        frag.appendChild(tr);
    });
    tbody.appendChild(frag);
}

async function openLogsFolderHost() {
    const res = await api('/api/logs/open_folder', 'POST');
    if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        alert(d.error || 'Недоступно');
    }
}