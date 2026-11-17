// web/static/analytics.js
let lastForecastData = null;
let chartDaily = null;
let chartTop5 = null;
let chartHourly = null;
let dayLogsPage = 1;
let dayLogsTotalPages = 1;

async function loadAnalyticsTab() {
    loadLogsList();
    loadAnalyticsCharts();
    initDayLogs();
    if (!rawSummaryItems.length) await loadSummary();
    else populateAnalyticsSelectors();
}

async function loadAnalyticsCharts() {
    if (typeof Chart === 'undefined') return;
    try {
        const res = await api('/api/analytics/charts');
        const d = await res.json();

        const cs = getComputedStyle(document.documentElement);
        const tickColor = cs.getPropertyValue('--text-muted').trim() || '#95a5a6';
        const gridColor = cs.getPropertyValue('--border').trim() || 'rgba(255,255,255,0.08)';
        const ui = typeof getUiSettings === 'function' ? getUiSettings() : {};
        const chCfg = ui.charts || {};

        const makeBg = (canvasId, key, defColor, defOp) => {
            const c = chCfg[key] || { color: defColor, gradient: false, opacity: defOp };
            const rgb = typeof hexToRgb === 'function' ? hexToRgb(c.color) : { r: 46, g: 204, b: 113 };
            const op = c.opacity ?? defOp;
            const rgbaMain = `rgba(${rgb.r},${rgb.g},${rgb.b},${op})`;
            if (!c.gradient) return rgbaMain;
            const ctx = document.getElementById(canvasId).getContext('2d');
            const grad = ctx.createLinearGradient(0, 0, 0, 200);
            grad.addColorStop(0, rgbaMain);
            grad.addColorStop(1, `rgba(${rgb.r},${rgb.g},${rgb.b},0.02)`);
            return grad;
        };

        const makeOpts = (horizontal = false) => ({
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: horizontal ? 'y' : 'x',
            plugins: { legend: { display: false } },
            scales: {
                x: {
                    beginAtZero: horizontal,
                    ticks: { color: tickColor, font: { size: 10 } },
                    grid: { color: gridColor }
                },
                y: {
                    beginAtZero: !horizontal,
                    ticks: { color: tickColor, font: { size: 10 } },
                    grid: { color: gridColor }
                }
            }
        });

        const cDaily = chCfg.daily || { color: '#2ecc71', opacity: 0.7 };
        if (chartDaily) chartDaily.destroy();
        chartDaily = new Chart(document.getElementById('chart-daily'), {
            type: 'bar',
            data: {
                labels: d.daily?.labels || [],
                datasets: [{ data: d.daily?.values || [], backgroundColor: makeBg('chart-daily', 'daily', '#2ecc71', 0.7), borderColor: cDaily.color, borderWidth: 1, borderRadius: 4 }]
            },
            options: makeOpts(false)
        });

        const cTop = chCfg.top5 || { color: '#e67e22', opacity: 0.7 };
        if (chartTop5) chartTop5.destroy();
        chartTop5 = new Chart(document.getElementById('chart-top5'), {
            type: 'bar',
            data: {
                labels: d.top5?.labels || [],
                datasets: [{ data: d.top5?.values || [], backgroundColor: makeBg('chart-top5', 'top5', '#e67e22', 0.7), borderColor: cTop.color, borderWidth: 1, borderRadius: 4 }]
            },
            options: makeOpts(true)
        });

        const cHour = chCfg.hourly || { color: '#3498db', opacity: 0.25 };
        if (chartHourly) chartHourly.destroy();
        chartHourly = new Chart(document.getElementById('chart-hourly'), {
            type: 'line',
            data: {
                labels: d.hourly?.labels || [],
                datasets: [{
                    data: d.hourly?.values || [],
                    borderColor: cHour.color,
                    backgroundColor: makeBg('chart-hourly', 'hourly', '#3498db', 0.25),
                    fill: true, tension: 0.35, pointRadius: 2
                }]
            },
            options: makeOpts(false)
        });
    } catch (e) {}
}

function populateAnalyticsSelectors() {
    const fill = (selId) => {
        const sel = document.getElementById(selId);
        if (!sel) return;
        const cur = sel.value;
        sel.innerHTML = '';
        const frag = document.createDocumentFragment();
        const def = document.createElement('option');
        def.value = 'all'; def.textContent = t('whole_seedbox');
        frag.appendChild(def);
        rawSummaryItems.forEach(item => {
            const opt = document.createElement('option');
            opt.value = item.hash_id;
            opt.textContent = `📦 ${item.name}`;
            frag.appendChild(opt);
        });
        sel.appendChild(frag);
        if (cur) sel.value = cur;
    };
    fill('smart-calc-target-type');
    fill('history-torrent-select');
}

function onSmartCalcTargetChange() {
    const val = document.getElementById('smart-calc-target-type').value;
    const lbl = document.getElementById('smart-calc-goal-label');
    const inp = document.getElementById('smart-calc-goal');
    if (val === 'all') {
        lbl.textContent = t('goal_lbl_all');
        inp.placeholder = t('goal_ph_all');
    } else {
        lbl.textContent = t('goal_lbl_one');
        inp.placeholder = t('goal_ph_one');
    }
}

async function runSmartCalc() {
    const term = document.getElementById('smart-calc-terminal');
    const targetVal = document.getElementById('smart-calc-target-type').value;
    const isAll = (targetVal === 'all');
    const goal = document.getElementById('smart-calc-goal').value.trim();
    const speed = document.getElementById('smart-calc-speed').value.trim();

    if (!goal) {
        term.textContent = t('err_no_goal');
        return;
    }

    term.textContent = t('calc_running');
    let d;
    try {
        const res = await api('/api/smart_calc', 'POST', {
            target_type: isAll ? 'all' : 'torrent',
            hash: isAll ? '' : targetVal,
            target: goal,
            speed: speed
        });
        if (!res.ok) {
            term.textContent = t('http_err', { status: res.status });
            return;
        }
        d = await res.json();
    } catch (err) {
        term.textContent = t('net_err', { msg: err.message });
        return;
    }

    const btnTable = document.getElementById('btn-toggle-forecast-table');
    const btnCsv = document.getElementById('btn-export-forecast-csv');
    const wrapTable = document.getElementById('smart-res-table-wrap');

    if (!d.success) {
        btnTable.classList.add('hidden');
        btnCsv.classList.add('hidden');
        wrapTable.classList.add('hidden');
        if (d.need_manual) {
            term.textContent =
                `=================================================================\n` +
                t('need_manual_msg', { avail: d.days_available, req: d.req_days }) + `\n` +
                `=================================================================`;
        } else {
            term.textContent = t('err_prefix', { msg: d.error });
        }
        return;
    }

    lastForecastData = d;
    btnCsv.classList.remove('hidden');

    if (d.achieved) {
        btnTable.classList.add('hidden');
        term.textContent = t('goal_achieved', { name: d.name, cur: d.current_up_fmt, tgt: d.target_fmt });
        return;
    }

    btnTable.classList.remove('hidden');
    const modeTxt = d.is_manual ? t('mode_manual') : t('mode_smart', { w: d.weights_desc });
    let out =
        `=================================================================\n` +
        `${t('res_header')}\n` +
        `${t('obj_lbl')}        ${d.name}\n` +
        `${t('up_now_lbl')} ${d.current_up_fmt}  -->  ${t('goal_lbl')} ${d.target_fmt}\n` +
        `${t('rem_lbl')}      ${d.remaining_fmt}\n`;
    if (!d.is_seedbox) out += `${t('ratio_lbl', { cur: d.ratio_current, nxt: d.ratio_after_24h })}\n`;
    out +=
        `-----------------------------------------------------------------\n` +
        `${t('mode_lbl')} ${modeTxt}\n` +
        `${t('f24_lbl')} +${d.forecast_24h_vol_fmt}\n` +
        `${t('eta_lbl')}   ${d.eta_str}\n` +
        `=================================================================`;
    term.textContent = out;

    const tbody = document.getElementById('smart-res-tbody');
    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    (d.forecast_rows || []).forEach(r => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${escapeHtml(r.date)}</td>
            <td><strong>${escapeHtml(r.hour)}</strong></td>
            <td class="purple-txt" style="font-weight:700;">+${escapeHtml(trBackend(r.volume_mb))}</td>
            <td class="blue-txt" style="font-weight:600;">${escapeHtml(r.speed_fmt)}</td>
            <td class="muted-text" style="font-size:11px;">${escapeHtml(r.basis)}</td>
        `;
        frag.appendChild(tr);
    });
    tbody.appendChild(frag);
}

function toggleForecastTable() {
    const wrap = document.getElementById('smart-res-table-wrap');
    const btn = document.getElementById('btn-toggle-forecast-table');
    const isHidden = wrap.classList.toggle('hidden');
    btn.textContent = isHidden ? t('btn_hourly_show') : t('btn_hourly_hide');
}

async function exportForecastCSV() {
    if (!lastForecastData) return;
    const res = await api('/api/smart_calc/export', 'POST', { forecast_data: lastForecastData });
    if (!res.ok) return alert(t('export_err'));
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = window.URL.createObjectURL(blob);
    const ts = new Date().toLocaleString('sv-SE').replace(/[- :]/g, '_');
    a.download = `forecast_24h_${ts}.csv`;
    a.click();
}

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