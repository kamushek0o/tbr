// web/static/analytics.js
let lastForecastData = null;
let chartDaily = null;
let chartTop5 = null;
let chartHourly = null;

async function loadAnalyticsTab() {
    syncAnalyticsControlsFromUi();
    loadAnalyticsCharts();
    if (typeof loadAnalyticsInsights === 'function') loadAnalyticsInsights(false);
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
    const perSel = document.getElementById('chart-top-period');
    if (perSel) perSel.value = ch.top_period || '1d';
    const scSel = document.getElementById('chart-top-scale');
    if (scSel) scSel.value = ch.top_scale || 'lin';
}

function onHourlyWindowChange() {
    const ui = getUiSettings(); ui.charts = ui.charts || {};
    ui.charts.hourly_hours = parseInt(document.getElementById('chart-hourly-hours').value) || 24;
    persistUiSettings(ui);
}

function onHourlyYMinToggle() {
    const isAuto = document.getElementById('chart-hourly-ymin-auto').checked;
    const inp = document.getElementById('chart-hourly-ymin');
    inp.disabled = isAuto;
    const ui = getUiSettings(); ui.charts = ui.charts || {};
    ui.charts.hourly_y_min = isAuto ? null : Math.max(0, parseFloat(inp.value) || 0);
    persistUiSettings(ui);
}

function onHourlyYMinInput() {
    const val = parseFloat(document.getElementById('chart-hourly-ymin').value);
    const ui = getUiSettings(); ui.charts = ui.charts || {};
    ui.charts.hourly_y_min = Number.isFinite(val) && val >= 0 ? val : 0;
    persistUiSettings(ui);
}

function setTopN(n) {
    const clamped = Math.max(1, Math.min(25, parseInt(n) || 5));
    const inp = document.getElementById('chart-topn-val');
    if (inp) inp.value = clamped;
    const ui = getUiSettings(); ui.charts = ui.charts || {};
    ui.charts.top_n = clamped;
    persistUiSettings(ui);
}

function onTopPeriodChange() {
    const ui = getUiSettings(); ui.charts = ui.charts || {};
    ui.charts.top_period = document.getElementById('chart-top-period').value || '1d';
    persistUiSettings(ui);
}

function onTopScaleChange() {
    const ui = getUiSettings(); ui.charts = ui.charts || {};
    ui.charts.top_scale = document.getElementById('chart-top-scale').value || 'lin';
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
        if (!prev || distSec < prev.dist) bestByHour.set(hKey, { idx, dist: distSec });
    });
    const flags = new Array(meta.length).fill(false);
    bestByHour.forEach(v => { flags[v.idx] = true; });
    return flags;
}

function _buildTwoColorGradient(canvasId, c1Hex, c2Hex, opacity, isHorizontal = false) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return c1Hex;
    const ctx = canvas.getContext('2d');
    const rgb1 = typeof hexToRgb === 'function' ? hexToRgb(c1Hex) : { r: 46, g: 204, b: 113 };
    const rgb2 = typeof hexToRgb === 'function' ? hexToRgb(c2Hex || c1Hex) : rgb1;
    const op = opacity ?? 0.75;
    const grad = isHorizontal
        ? ctx.createLinearGradient(0, 0, canvas.clientWidth || 600, 0)
        : ctx.createLinearGradient(0, 0, 0, canvas.clientHeight || 220);
    grad.addColorStop(0, `rgba(${rgb1.r},${rgb1.g},${rgb1.b},${op})`);
    grad.addColorStop(1, `rgba(${rgb2.r},${rgb2.g},${rgb2.b},${Math.max(0.08, op * 0.45)})`);
    return grad;
}

async function loadAnalyticsCharts() {
    if (typeof Chart === 'undefined') return;
    try {
        const ui = typeof getUiSettings === 'function' ? getUiSettings() : {};
        const chCfg = ui.charts || {};
        const winHours = parseInt(chCfg.hourly_hours) || 24;
        const topN = Math.max(1, Math.min(25, parseInt(chCfg.top_n) || 5));
        const topPeriod = chCfg.top_period || '1d';
        const topScale = chCfg.top_scale || 'lin';
        const yMin = (chCfg.hourly_y_min !== null && chCfg.hourly_y_min !== undefined && chCfg.hourly_y_min !== '')
            ? parseFloat(chCfg.hourly_y_min) : null;

        const res = await api(`/api/analytics/charts?hours=${winHours}&top_n=${topN}&top_period=${encodeURIComponent(topPeriod)}`);
        const d = await res.json();

        const cs = getComputedStyle(document.documentElement);
        const tickColor = cs.getPropertyValue('--text-muted').trim() || '#95a5a6';
        const gridColor = cs.getPropertyValue('--border').trim() || 'rgba(255,255,255,0.08)';

        // 1. График по дням (Двухцветный вертикальный градиент)
        const cDaily = chCfg.daily || { color: '#2ecc71', color2: '#10b981', opacity: 0.75 };
        const dailyBg = cDaily.gradient !== false
            ? _buildTwoColorGradient('chart-daily', cDaily.color, cDaily.color2, cDaily.opacity, false)
            : cDaily.color;

        if (chartDaily) chartDaily.destroy();
        chartDaily = new Chart(document.getElementById('chart-daily'), {
            type: 'bar',
            data: {
                labels: d.daily?.labels || [],
                datasets: [{
                    data: d.daily?.values || [],
                    backgroundColor: dailyBg,
                    borderColor: cDaily.color,
                    borderWidth: 1, borderRadius: 4, minBarLength: 2, barPercentage: 0.65
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { ticks: { color: tickColor, font: { size: 10 } }, grid: { color: gridColor } },
                    y: { beginAtZero: true, ticks: { color: tickColor, font: { size: 10 } }, grid: { color: gridColor } }
                },
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: ctx => `${currentLang === 'en' ? 'Daily Upload' : 'Отдано за день'}: ${ctx.parsed.y} GiB` } }
                }
            }
        });

        // 2. Топ-N раздач + Столбик «Все остальные»
        const rawTopVals = [...(d.top5?.values || [])];
        const topLabels = [...(d.top5?.labels || [])];
        const topFullLabels = [...(d.top5?.full_labels || d.top5?.labels || [])];
        const others = d.top5?.others;
        const hasOthers = Boolean(others && (others.gb > 0 || others.count > 0));

        if (hasOthers) {
            const isEn = (typeof currentLang !== 'undefined' && currentLang === 'en');
            topLabels.push(isEn ? `Others (${others.count})` : `Все остальные (${others.count})`);
            topFullLabels.push(isEn ? `All other torrents (${others.count} pcs)` : `Все остальные раздачи (${others.count} шт.)`);
            rawTopVals.push(others.gb);
        }

        const topWrap = document.getElementById('chart-top5-wrap');
        const actualCount = topLabels.length || topN;
        if (topWrap) topWrap.style.height = `${Math.max(210, actualCount * 32 + 48)}px`;

        const isLog = (topScale === 'log10');
        const plotTopVals = isLog ? rawTopVals.map(v => Math.log10(1 + Math.max(0, v))) : rawTopVals;
        const maxReal = Math.max(1, ...rawTopVals);

        const topXScale = { beginAtZero: true, ticks: { color: tickColor, font: { size: 10 } }, grid: { color: gridColor } };
        if (isLog) {
            const pwrTicks = [0, 1, 10, 100, 1000, 10000, 100000].filter(p => p === 0 || p <= maxReal * 2.5);
            if (pwrTicks.length < 2) pwrTicks.push(1, 10);
            topXScale.afterBuildTicks = axis => { axis.ticks = pwrTicks.map(p => ({ value: Math.log10(1 + p) })); };
            topXScale.ticks.callback = val => { const orig = Math.round(Math.pow(10, val) - 1); return orig <= 0 ? '0' : String(orig); };
        }

        const cTop = chCfg.top5 || { color: '#ff9f1c', color2: '#ff4d6d', opacity: 0.8 };
        const topGrad = _buildTwoColorGradient('chart-top5', cTop.color, cTop.color2, cTop.opacity, true);
        const topBgColors = plotTopVals.map((_, idx) => (hasOthers && idx === plotTopVals.length - 1) ? 'rgba(100, 116, 139, 0.55)' : topGrad);

        if (chartTop5) chartTop5.destroy();
        chartTop5 = new Chart(document.getElementById('chart-top5'), {
            type: 'bar',
            data: {
                labels: topLabels,
                datasets: [{
                    data: plotTopVals,
                    backgroundColor: topBgColors,
                    borderColor: cTop.color,
                    borderWidth: 1, borderRadius: 4, minBarLength: 2, barPercentage: 0.72
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false, indexAxis: 'y',
                scales: { x: topXScale, y: { ticks: { color: tickColor, font: { size: 10 } }, grid: { color: gridColor } } },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: items => (items.length ? (topFullLabels[items[0].dataIndex] || items[0].label) : ''),
                            label: ctx => {
                                const val = rawTopVals[ctx.dataIndex] ?? 0;
                                if (hasOthers && ctx.dataIndex === rawTopVals.length - 1) {
                                    const isEn = (typeof currentLang !== 'undefined' && currentLang === 'en');
                                    return `${isEn ? 'All other torrents' : 'Все остальные раздачи'} (${others.count} шт.): ${val} GiB`;
                                }
                                return `${currentLang === 'en' ? 'Uploaded' : 'Отдано'}: ${val} GiB`;
                            }
                        }
                    }
                }
            }
        });

        // 3. График скорости нагрузки (Двухцветный вертикальный градиент)
        const cHour = chCfg.hourly || { color: '#00f5d4', color2: '#9b5de5', opacity: 0.35 };
        const hourlyBg = _buildTwoColorGradient('chart-hourly', cHour.color, cHour.color2, cHour.opacity, false);
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
                    backgroundColor: hourlyBg,
                    fill: true, tension: 0.35, cubicInterpolationMode: 'monotone', clip: true,
                    pointRadius: ctx => (hourFlags[ctx.dataIndex] ? (winHours <= 24 ? 3.5 : 1.5) : 0),
                    pointHoverRadius: 5, pointHitRadius: 10
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: { x: { ticks: { color: tickColor, font: { size: 10 } }, grid: { color: gridColor } }, y: yScaleOpts },
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
    } catch (e) { console.error(e); }
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
            opt.value = item.hash_id; opt.textContent = `📦 ${item.name}`;
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
    document.getElementById('smart-calc-goal-label').textContent = val === 'all' ? t('goal_lbl_all') : t('goal_lbl_one');
    document.getElementById('smart-calc-goal').placeholder = val === 'all' ? t('goal_ph_all') : t('goal_ph_one');
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
    } catch (err) { term.textContent = t('net_err', { msg: err.message }); return; }

    const btnTable = document.getElementById('btn-toggle-forecast-table');
    const btnCsv = document.getElementById('btn-export-forecast-csv');
    const wrapTable = document.getElementById('smart-res-table-wrap');
    if (!d.success) {
        btnTable.classList.add('hidden'); btnCsv.classList.add('hidden'); wrapTable.classList.add('hidden');
        term.textContent = d.need_manual ? `=================================================================\n${t('need_manual_msg', { avail: d.days_available, req: d.req_days })}\n=================================================================` : t('err_prefix', { msg: d.error });
        return;
    }

    lastForecastData = d;
    btnCsv.classList.remove('hidden');
    if (d.achieved) { btnTable.classList.add('hidden'); term.textContent = t('goal_achieved', { name: d.name, cur: d.current_up_fmt, tgt: d.target_fmt }); return; }

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