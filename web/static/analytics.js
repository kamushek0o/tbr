// web/static/analytics.js
let chartDaily = null;
let chartTop5 = null;
let chartHourly = null;
let _lastTopData = null;
let _lastHourlyMeta = [];
const _chartAborts = { daily: null, hourly: null, top5: null };
const _debounceTimers = {};

function _debounce(key, fn, ms = 500) {
    clearTimeout(_debounceTimers[key]);
    _debounceTimers[key] = setTimeout(fn, ms);
}

function _persistUiBg(ui) {
    if (typeof CURRENT_UI_SETTINGS !== 'undefined') CURRENT_UI_SETTINGS = ui;
    localStorage.setItem('tbr_ui_settings', JSON.stringify(ui));
    _debounce('ui_save', async () => {
        if (typeof CURRENT_ROLE === 'undefined' || CURRENT_ROLE === 'admin') {
            try { await api('/api/profile/ui', 'POST', ui); } catch (e) {}
        }
    }, 500);
}

async function loadAnalyticsTab() {
    syncAnalyticsControlsFromUi();
    loadAnalyticsCharts();
    if (typeof loadAnalyticsInsights === 'function') loadAnalyticsInsights(false);
    initDayLogs();
    if (!rawSummaryItems.length) await loadSummary();
    else if (typeof populateAnalyticsSelectors === 'function') populateAnalyticsSelectors();
}

function syncAnalyticsControlsFromUi() {
    const ch = (typeof getUiSettings === 'function' ? getUiSettings().charts : {}) || {};
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
    _persistUiBg(ui);
    _debounce('fetch_hourly', () => loadSingleChart('hourly'), 300);
}

function _applyHourlyYMinLocally(yMinVal) {
    if (!chartHourly) return;
    const yScale = chartHourly.options.scales.y;
    if (yMinVal !== null && Number.isFinite(yMinVal)) { delete yScale.beginAtZero; yScale.min = yMinVal; }
    else { delete yScale.min; yScale.beginAtZero = true; }
    chartHourly.update('none');
}

function onHourlyYMinToggle() {
    const isAuto = document.getElementById('chart-hourly-ymin-auto').checked;
    const inp = document.getElementById('chart-hourly-ymin');
    inp.disabled = isAuto;
    const ui = getUiSettings(); ui.charts = ui.charts || {};
    const val = isAuto ? null : Math.max(0, parseFloat(inp.value) || 0);
    ui.charts.hourly_y_min = val;
    _applyHourlyYMinLocally(val);
    _persistUiBg(ui);
}

function onHourlyYMinInput() {
    const raw = parseFloat(document.getElementById('chart-hourly-ymin').value);
    const val = Number.isFinite(raw) && raw >= 0 ? raw : 0;
    const ui = getUiSettings(); ui.charts = ui.charts || {};
    ui.charts.hourly_y_min = val;
    _applyHourlyYMinLocally(val);
    _persistUiBg(ui);
}

function setTopN(n) {
    const clamped = Math.max(1, Math.min(25, parseInt(n) || 5));
    const inp = document.getElementById('chart-topn-val');
    if (inp && document.activeElement !== inp) inp.value = clamped;
    const ui = getUiSettings(); ui.charts = ui.charts || {};
    ui.charts.top_n = clamped;
    _persistUiBg(ui);
    _debounce('fetch_top5', () => loadSingleChart('top5'), 500);
}

function onTopPeriodChange() {
    const ui = getUiSettings(); ui.charts = ui.charts || {};
    ui.charts.top_period = document.getElementById('chart-top-period').value || '1d';
    _persistUiBg(ui);
    _debounce('fetch_top5', () => loadSingleChart('top5'), 300);
}

function onTopScaleChange() {
    const scale = document.getElementById('chart-top-scale').value || 'lin';
    const ui = getUiSettings(); ui.charts = ui.charts || {};
    ui.charts.top_scale = scale;
    _persistUiBg(ui);
    if (chartTop5 && _lastTopData) _renderTop5Chart(_lastTopData, scale, true);
}

async function loadSingleChart(chartType) {
    if (typeof Chart === 'undefined') return;
    if (_chartAborts[chartType]) _chartAborts[chartType].abort();
    const ctrl = new AbortController();
    _chartAborts[chartType] = ctrl;
    const chCfg = (typeof getUiSettings === 'function' ? getUiSettings().charts : {}) || {};
    try {
        const res = await fetch(`/api/analytics/charts?chart=${encodeURIComponent(chartType)}&hours=${parseInt(chCfg.hourly_hours) || 24}&top_n=${Math.max(1, Math.min(25, parseInt(chCfg.top_n) || 5))}&top_period=${encodeURIComponent(chCfg.top_period || '1d')}`, { signal: ctrl.signal });
        if (res.status === 401) { window.location.href = '/login'; return; }
        if (!res.ok) return;
        const d = await res.json();
        if (chartType === 'daily' && d.daily) _renderDailyChart(d.daily);
        if (chartType === 'hourly' && d.hourly) _renderHourlyChart(d.hourly);
        if (chartType === 'top5' && d.top5) _renderTop5Chart(d.top5, chCfg.top_scale || 'lin', Boolean(chartTop5));
    } catch (e) { if (e.name !== 'AbortError') console.error(e); }
}

async function loadAnalyticsCharts() {
    if (typeof Chart === 'undefined') return;
    try {
        const chCfg = (typeof getUiSettings === 'function' ? getUiSettings().charts : {}) || {};
        const res = await api(`/api/analytics/charts?chart=all&hours=${parseInt(chCfg.hourly_hours) || 24}&top_n=${Math.max(1, Math.min(25, parseInt(chCfg.top_n) || 5))}&top_period=${encodeURIComponent(chCfg.top_period || '1d')}`);
        const d = await res.json();
        if (d.daily) _renderDailyChart(d.daily);
        if (d.hourly) _renderHourlyChart(d.hourly);
        if (d.top5) _renderTop5Chart(d.top5, chCfg.top_scale || 'lin', Boolean(chartTop5));
    } catch (e) { console.error(e); }
}