// web/static/analytics.js
let lastForecastData = null;
let chartDaily = null;
let chartTop5 = null;
let chartHourly = null;

async function loadAnalyticsTab() {
    syncAnalyticsControlsFromUi();
    loadAnalyticsCharts();
    initDayLogs();
    if (!rawSummaryItems.length) await loadSummary();
    else populateAnalyticsSelectors();
}

function syncAnalyticsControlsFromUi() {
    const ui = typeof getUiSettings === 'function' ? getUiSettings() : {};
    const ch = ui.charts || {};
    const hSel = document.getElementById('chart-hourly-hours');
    if (hSel) hSel.value = String(ch.hourly_hours || 24);

    const yAuto = document.getElementById('chart-hourly-ymin-auto');
    const yInp = document.getElementById('chart-hourly-ymin');
    const hasYMin = ch.hourly_y_min !== null && ch.hourly_y_min !== undefined && ch.hourly_y_min !== '';
    if (yAuto && yInp) {
        yAuto.checked = !hasYMin;
        yInp.disabled = !hasYMin;
        yInp.value = hasYMin ? ch.hourly_y_min : '';
    }

    const topInp = document.getElementById('chart-topn-val');
    if (topInp) topInp.value = Math.max(1, Math.min(25, parseInt(ch.top_n) || 5));
}

function onHourlyWindowChange() {
    const ui = getUiSettings();
    ui.charts = ui.charts || {};
    ui.charts.hourly_hours = parseInt(document.getElementById('chart-hourly-hours').value) || 24;
    persistUiSettings(ui);
}

function onHourlyYMinToggle() {
    const isAuto = document.getElementById('chart-hourly-ymin-auto').checked;
    const inp = document.getElementById('chart-hourly-ymin');
    inp.disabled = isAuto;
    const ui = getUiSettings();
    ui.charts = ui.charts || {};
    ui.charts.hourly_y_min = isAuto ? null : Math.max(0, parseFloat(inp.value) || 0);
    persistUiSettings(ui);
}

function onHourlyYMinInput() {
    const inp = document.getElementById('chart-hourly-ymin');
    const val = parseFloat(inp.value);
    const ui = getUiSettings();
    ui.charts = ui.charts || {};
    ui.charts.hourly_y_min = Number.isFinite(val) && val >= 0 ? val : 0;
    persistUiSettings(ui);
}

function setTopN(n) {
    const clamped = Math.max(1, Math.min(25, parseInt(n) || 5));
    const inp = document.getElementById('chart-topn-val');
    if (inp) inp.value = clamped;
    const ui = getUiSettings();
    ui.charts = ui.charts || {};
    ui.charts.top_n = clamped;
    persistUiSettings(ui);
}

function _computeHourMarkerFlags(meta) {
    if (!Array.isArray(meta) || !meta.length) return [];
    const bestByHour = new Map();
    meta.forEach((m, idx) => {
        if (!m || !m.ts) return;
        const dt = new Date(m.ts * 1000);
        const hKey = `${dt.getFullYear()}-${dt.getMonth()}-${dt.getDate()}-${dt.getHours()}`;
        const distSec = dt.getMinutes() * 60 + dt.getSeconds();
        const prev = bestByHour.get(hKey);
        if (!prev || distSec < prev.dist) {
            bestByHour.set(hKey, { idx, dist: distSec });
        }
    });
    const flags = new Array(meta.length).fill(false);
    bestByHour.forEach(v => { flags[v.idx] = true; });
    return flags;
}

async function loadAnalyticsCharts() {
    if (typeof Chart === 'undefined') return;
    try {
        const ui = typeof getUiSettings === 'function' ? getUiSettings() : {};
        const chCfg = ui.charts || {};
        const winHours = parseInt(chCfg.hourly_hours) || 24;
        const topN = Math.max(1, Math.min(25, parseInt(chCfg.top_n) || 5));
        const yMin = (chCfg.hourly_y_min !== null && chCfg.hourly_y_min !== undefined && chCfg.hourly_y_min !== '')
            ? parseFloat(chCfg.hourly_y_min)
            : null;

        const res = await api(`/api/analytics/charts?hours=${winHours}&top_n=${topN}`);
        const d = await res.json();

        const cs = getComputedStyle(document.documentElement);
        const tickColor = cs.getPropertyValue('--text-muted').trim() || '#95a5a6';
        const gridColor = cs.getPropertyValue('--border').trim() || 'rgba(255,255,255,0.08)';

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
                x: { beginAtZero: horizontal, ticks: { color: tickColor, font: { size: 10 } }, grid: { color: gridColor } },
                y: { beginAtZero: !horizontal, ticks: { color: tickColor, font: { size: 10 } }, grid: { color: gridColor } }
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
            options: {
                ...makeOpts(false),
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: ctx => `${currentLang === 'en' ? 'Daily Upload' : 'Отдано за день'}: ${ctx.parsed.y} GiB` } }
                }
            }
        });

        const topWrap = document.getElementById('chart-top5-wrap');
        const topFullLabels = d.top5?.full_labels || d.top5?.labels || [];
        const actualCount = (d.top5?.labels || []).length || topN;
        if (topWrap) topWrap.style.height = `${Math.max(200, actualCount * 32 + 44)}px`;

        const cTop = chCfg.top5 || { color: '#e67e22', opacity: 0.7 };
        if (chartTop5) chartTop5.destroy();
        chartTop5 = new Chart(document.getElementById('chart-top5'), {
            type: 'bar',
            data: {
                labels: d.top5?.labels || [],
                datasets: [{ data: d.top5?.values || [], backgroundColor: makeBg('chart-top5', 'top5', '#e67e22', 0.7), borderColor: cTop.color, borderWidth: 1, borderRadius: 4 }]
            },
            options: {
                ...makeOpts(true),
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: items => (items.length ? (topFullLabels[items[0].dataIndex] || items[0].label) : ''),
                            label: ctx => `${currentLang === 'en' ? 'Uploaded' : 'Отдано'}: ${ctx.parsed.x} GiB`
                        }
                    }
                }
            }
        });

        const cHour = chCfg.hourly || { color: '#3498db', opacity: 0.25 };
        const hourlyMeta = d.hourly?.meta || d.detailed || [];
        const hourFlags = _computeHourMarkerFlags(hourlyMeta);
        const yScaleOpts = { ticks: { color: tickColor, font: { size: 10 } }, grid: { color: gridColor } };
        if (yMin !== null && Number.isFinite(yMin)) yScaleOpts.min = yMin;
        else yScaleOpts.beginAtZero = true;

        if (chartHourly) chartHourly.destroy();
        chartHourly = new Chart(document.getElementById('chart-hourly'), {
            type: 'line',
            data: {
                labels: d.hourly?.labels || [],
                datasets: [{
                    data: d.hourly?.values || [],
                    borderColor: cHour.color,
                    backgroundColor: makeBg('chart-hourly', 'hourly', '#3498db', 0.25),
                    fill: true,
                    tension: 0.35,
                    cubicInterpolationMode: 'monotone',
                    clip: true,
                    pointRadius: ctx => (hourFlags[ctx.dataIndex] ? (winHours <= 24 ? 3.5 : 1.5) : 0),
                    pointHoverRadius: 5,
                    pointHitRadius: 10
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { ticks: { color: tickColor, font: { size: 10 } }, grid: { color: gridColor } },
                    y: yScaleOpts
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function(ctx) {
                                const m = hourlyMeta[ctx.dataIndex];
                                const isEn = (typeof currentLang !== 'undefined' && currentLang === 'en');
                                const spd = (ctx.parsed.y !== undefined ? ctx.parsed.y : (m?.speed_mbs || 0)).toFixed(2);
                                const speedLine = `⚡ ${isEn ? 'Speed' : 'Скорость'}: ${spd} MiB/s`;
                                if (!m || !m.delta_fmt) return speedLine;
                                const intTxt = m.interval_min > 0 ? (isEn ? ` (${m.interval_min}m)` : ` (${m.interval_min}м)`) : '';
                                return [speedLine, `📦 ${isEn ? 'Uploaded' : 'Отдано'}: +${m.delta_fmt}${intTxt}`];
                            }
                        }
                    }
                }
            }
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
    lbl.textContent = val === 'all' ? t('goal_lbl_all') : t('goal_lbl_one');
    inp.placeholder = val === 'all' ? t('goal_ph_all') : t('goal_ph_one');
}

async function runSmartCalc() {
    const term = document.getElementById('smart-calc-terminal');
    const targetVal = document.getElementById('smart-calc-target-type').value;
    const isAll = (targetVal === 'all');
    const goal = document.getElementById('smart-calc-goal').value.trim();
    const speed = document.getElementById('smart-calc-speed').value.trim();
    if (!goal) { term.textContent = t('err_no_goal'); return; }

    term.textContent = t('calc_running');
    let d;
    try {
        const res = await api('/api/smart_calc', 'POST', { target_type: isAll ? 'all' : 'torrent', hash: isAll ? '' : targetVal, target: goal, speed });
        if (!res.ok) { term.textContent = t('http_err', { status: res.status }); return; }
        d = await res.json();
    } catch (err) {
        term.textContent = t('net_err', { msg: err.message });
        return;
    }

    const btnTable = document.getElementById('btn-toggle-forecast-table');
    const btnCsv = document.getElementById('btn-export-forecast-csv');
    const wrapTable = document.getElementById('smart-res-table-wrap');

    if (!d.success) {
        btnTable.classList.add('hidden'); btnCsv.classList.add('hidden'); wrapTable.classList.add('hidden');
        term.textContent = d.need_manual
            ? `=================================================================\n${t('need_manual_msg', { avail: d.days_available, req: d.req_days })}\n=================================================================`
            : t('err_prefix', { msg: d.error });
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
    let out = `=================================================================\n${t('res_header')}\n${t('obj_lbl')}        ${d.name}\n${t('up_now_lbl')} ${d.current_up_fmt}  -->  ${t('goal_lbl')} ${d.target_fmt}\n${t('rem_lbl')}      ${d.remaining_fmt}\n`;
    if (!d.is_seedbox) out += `${t('ratio_lbl', { cur: d.ratio_current, nxt: d.ratio_after_24h })}\n`;
    out += `-----------------------------------------------------------------\n${t('mode_lbl')} ${modeTxt}\n${t('f24_lbl')} +${d.forecast_24h_vol_fmt}\n${t('eta_lbl')}   ${d.eta_str}\n=================================================================`;
    term.textContent = out;

    const tbody = document.getElementById('smart-res-tbody');
    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    (d.forecast_rows || []).forEach(r => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${escapeHtml(r.date)}</td><td><strong>${escapeHtml(r.hour)}</strong></td><td class="purple-txt" style="font-weight:700;">+${escapeHtml(trBackend(r.volume_mb))}</td><td class="blue-txt" style="font-weight:600;">${escapeHtml(r.speed_fmt)}</td><td class="muted-text" style="font-size:11px;">${escapeHtml(r.basis)}</td>`;
        frag.appendChild(tr);
    });
    tbody.appendChild(frag);
}

function toggleForecastTable() {
    const isHidden = document.getElementById('smart-res-table-wrap').classList.toggle('hidden');
    document.getElementById('btn-toggle-forecast-table').textContent = isHidden ? t('btn_hourly_show') : t('btn_hourly_hide');
}

async function exportForecastCSV() {
    if (!lastForecastData) return;
    const res = await api('/api/smart_calc/export', 'POST', { forecast_data: lastForecastData });
    if (!res.ok) return alert(t('export_err'));
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = window.URL.createObjectURL(blob);
    a.download = `forecast_24h_${new Date().toLocaleString('sv-SE').replace(/[- :]/g, '_')}.csv`;
    a.click();
}