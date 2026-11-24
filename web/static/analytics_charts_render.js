// web/static/analytics_charts_render.js
function _computeHourMarkerFlags(meta) {
    if (!Array.isArray(meta) || !meta.length) return [];
    const bestByHour = new Map();
    meta.forEach((m, idx) => {
        if (!m || !m.ts) return;
        const dt = new Date(m.ts * 1000);
        const hKey = `${dt.getFullYear()}-${dt.getMonth()}-${dt.getDate()}-${dt.getHours()}`;
        const dist = dt.getMinutes() * 60 + dt.getSeconds();
        const prev = bestByHour.get(hKey);
        if (!prev || dist < prev.dist) bestByHour.set(hKey, { idx, dist });
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
    const grad = isHorizontal ? ctx.createLinearGradient(0, 0, canvas.clientWidth || 600, 0) : ctx.createLinearGradient(0, 0, 0, canvas.clientHeight || 220);
    grad.addColorStop(0, `rgba(${rgb1.r},${rgb1.g},${rgb1.b},${op})`);
    grad.addColorStop(1, `rgba(${rgb2.r},${rgb2.g},${rgb2.b},${Math.max(0.08, op * 0.45)})`);
    return grad;
}

function applyAnalyticsVisualSettingsLocally(ui) {
    const chCfg = (ui && ui.charts) || {};
    if (chartDaily) {
        const cD = chCfg.daily || { color: '#2ecc71', color2: '#10b981', opacity: 0.75 };
        chartDaily.data.datasets[0].backgroundColor = cD.gradient !== false ? _buildTwoColorGradient('chart-daily', cD.color, cD.color2, cD.opacity, false) : cD.color;
        chartDaily.data.datasets[0].borderColor = cD.color;
        chartDaily.update('none');
    }
    if (chartHourly) {
        const cH = chCfg.hourly || { color: '#00f5d4', color2: '#9b5de5', opacity: 0.35 };
        chartHourly.data.datasets[0].backgroundColor = cH.gradient !== false ? _buildTwoColorGradient('chart-hourly', cH.color, cH.color2, cH.opacity, false) : cH.color;
        chartHourly.data.datasets[0].borderColor = cH.color;
        chartHourly.update('none');
    }
    if (chartTop5 && _lastTopData) _renderTop5Chart(_lastTopData, chCfg.top_scale || 'lin', true);
}

function _chartThemeColors() {
    const cs = getComputedStyle(document.documentElement);
    return {
        tick: cs.getPropertyValue('--text-muted').trim() || '#95a5a6',
        grid: cs.getPropertyValue('--border').trim() || 'rgba(255,255,255,0.08)'
    };
}

function _renderDailyChart(dailyData) {
    const cD = ((typeof getUiSettings === 'function' ? getUiSettings().charts : {}) || {}).daily || { color: '#2ecc71', color2: '#10b981', opacity: 0.75 };
    const bg = cD.gradient !== false ? _buildTwoColorGradient('chart-daily', cD.color, cD.color2, cD.opacity, false) : cD.color;
    const { tick, grid } = _chartThemeColors();
    if (chartDaily) {
        chartDaily.data.labels = dailyData.labels || [];
        chartDaily.data.datasets[0].data = dailyData.values || [];
        chartDaily.data.datasets[0].backgroundColor = bg;
        chartDaily.data.datasets[0].borderColor = cD.color;
        chartDaily.update('none');
        return;
    }
    chartDaily = new Chart(document.getElementById('chart-daily'), {
        type: 'bar',
        data: { labels: dailyData.labels || [], datasets: [{ data: dailyData.values || [], backgroundColor: bg, borderColor: cD.color, borderWidth: 1, borderRadius: 4, minBarLength: 2, barPercentage: 0.65 }] },
        options: {
            responsive: true, maintainAspectRatio: false,
            scales: { x: { ticks: { color: tick, font: { size: 10 } }, grid: { color: grid } }, y: { beginAtZero: true, ticks: { color: tick, font: { size: 10 } }, grid: { color: grid } } },
            plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => `${currentLang === 'en' ? 'Daily Upload' : 'Отдано за день'}: ${ctx.parsed.y} GiB` } } }
        }
    });
}

function _renderTop5Chart(topData, topScale = 'lin', updateOnly = false) {
    _lastTopData = topData;
    const chCfg = (typeof getUiSettings === 'function' ? getUiSettings().charts : {}) || {};
    const rawVals = [...(topData?.values || [])], labels = [...(topData?.labels || [])], fullLabels = [...(topData?.full_labels || topData?.labels || [])];
    const others = topData?.others, hasOthers = Boolean(others && (others.gb > 0 || others.count > 0));
    const isEn = (typeof currentLang !== 'undefined' && currentLang === 'en');
    if (hasOthers) {
        labels.push(isEn ? `Others (${others.count})` : `Все остальные (${others.count})`);
        fullLabels.push(isEn ? `All other torrents (${others.count} pcs)` : `Все остальные раздачи (${others.count} шт.)`);
        rawVals.push(others.gb);
    }
    const topWrap = document.getElementById('chart-top5-wrap');
    if (topWrap) topWrap.style.height = `${Math.max(210, (labels.length || 5) * 32 + 48)}px`;

    const isLog = (topScale === 'log10'), plotVals = isLog ? rawVals.map(v => Math.log10(1 + Math.max(0, v))) : rawVals;
    const { tick, grid } = _chartThemeColors();
    const xScale = { beginAtZero: true, ticks: { color: tick, font: { size: 10 } }, grid: { color: grid } };
    if (isLog) {
        const maxR = Math.max(1, ...rawVals), pwr = [0, 1, 10, 100, 1000, 10000, 100000].filter(p => p === 0 || p <= maxR * 2.5);
        if (pwr.length < 2) pwr.push(1, 10);
        xScale.afterBuildTicks = ax => { ax.ticks = pwr.map(p => ({ value: Math.log10(1 + p) })); };
        xScale.ticks.callback = v => { const o = Math.round(Math.pow(10, v) - 1); return o <= 0 ? '0' : String(o); };
    }
    const cTop = chCfg.top5 || { color: '#ff9f1c', color2: '#ff4d6d', opacity: 0.8 };
    const grad = cTop.gradient !== false ? _buildTwoColorGradient('chart-top5', cTop.color, cTop.color2, cTop.opacity, true) : cTop.color;
    const bg = plotVals.map((_, i) => (hasOthers && i === plotVals.length - 1) ? 'rgba(100, 116, 139, 0.55)' : grad);
    const tooltips = {
        title: items => (items.length ? (fullLabels[items[0].dataIndex] || items[0].label) : ''),
        label: ctx => (hasOthers && ctx.dataIndex === rawVals.length - 1)
            ? `${isEn ? 'All other torrents' : 'Все остальные раздачи'} (${others.count} шт.): ${rawVals[ctx.dataIndex] ?? 0} GiB`
            : `${isEn ? 'Uploaded' : 'Отдано'}: ${rawVals[ctx.dataIndex] ?? 0} GiB`
    };
    if (chartTop5 && updateOnly) {
        chartTop5.data.labels = labels;
        chartTop5.data.datasets[0].data = plotVals;
        chartTop5.data.datasets[0].backgroundColor = bg;
        chartTop5.data.datasets[0].borderColor = cTop.color;
        chartTop5.options.scales.x = xScale;
        chartTop5.options.plugins.tooltip.callbacks = tooltips;
        chartTop5.resize();
        chartTop5.update('none');
        return;
    }
    if (chartTop5) chartTop5.destroy();
    chartTop5 = new Chart(document.getElementById('chart-top5'), {
        type: 'bar',
        data: { labels, datasets: [{ data: plotVals, backgroundColor: bg, borderColor: cTop.color, borderWidth: 1, borderRadius: 4, minBarLength: 2, barPercentage: 0.72 }] },
        options: { responsive: true, maintainAspectRatio: false, indexAxis: 'y', scales: { x: xScale, y: { ticks: { color: tick, font: { size: 10 } }, grid: { color: grid } } }, plugins: { legend: { display: false }, tooltip: { callbacks: tooltips } } }
    });
}

function _renderHourlyChart(hourlyData) {
    const chCfg = (typeof getUiSettings === 'function' ? getUiSettings().charts : {}) || {};
    const cH = chCfg.hourly || { color: '#00f5d4', color2: '#9b5de5', opacity: 0.35 };
    const bg = cH.gradient !== false ? _buildTwoColorGradient('chart-hourly', cH.color, cH.color2, cH.opacity, false) : cH.color;
    const winHours = parseInt(hourlyData?.hours || chCfg.hourly_hours || 24);
    _lastHourlyMeta = hourlyData?.meta || [];
    const flags = _computeHourMarkerFlags(_lastHourlyMeta);
    const yMin = (chCfg.hourly_y_min !== null && chCfg.hourly_y_min !== undefined && chCfg.hourly_y_min !== '') ? parseFloat(chCfg.hourly_y_min) : null;
    const { tick, grid } = _chartThemeColors();
    const yOpts = { ticks: { color: tick, font: { size: 10 } }, grid: { color: grid } };
    if (yMin !== null && Number.isFinite(yMin)) yOpts.min = yMin; else yOpts.beginAtZero = true;

    if (chartHourly) {
        chartHourly.data.labels = hourlyData?.labels || [];
        chartHourly.data.datasets[0].data = hourlyData?.values || [];
        chartHourly.data.datasets[0].borderColor = cH.color;
        chartHourly.data.datasets[0].backgroundColor = bg;
        chartHourly.data.datasets[0].pointRadius = ctx => (flags[ctx.dataIndex] ? (winHours <= 24 ? 3.5 : 1.5) : 0);
        chartHourly.options.scales.y = yOpts;
        chartHourly.update('none');
        return;
    }
    chartHourly = new Chart(document.getElementById('chart-hourly'), {
        type: 'line',
        data: { labels: hourlyData?.labels || [], datasets: [{ data: hourlyData?.values || [], borderColor: cH.color, backgroundColor: bg, fill: true, tension: 0.35, cubicInterpolationMode: 'monotone', clip: true, pointRadius: ctx => (flags[ctx.dataIndex] ? (winHours <= 24 ? 3.5 : 1.5) : 0), pointHoverRadius: 5, pointHitRadius: 10 }] },
        options: {
            responsive: true, maintainAspectRatio: false,
            scales: { x: { ticks: { color: tick, font: { size: 10 } }, grid: { color: grid } }, y: yOpts },
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: ctx => { const m = _lastHourlyMeta[ctx.dataIndex], l = `⚡ ${currentLang === 'en' ? 'Speed' : 'Скорость'}: ${(ctx.parsed.y ?? m?.speed_mbs ?? 0).toFixed(2)} MiB/s`; return (!m || !m.delta_fmt) ? l : [l, `📦 ${currentLang === 'en' ? 'Uploaded' : 'Отдано'}: +${m.delta_fmt}${m.interval_min > 0 ? ` (${m.interval_min}м)` : ''}`]; } } }
            }
        }
    });
}