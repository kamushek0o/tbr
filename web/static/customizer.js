// web/static/customizer.js
const THEME_PRESETS = {
    dark:  { bg_main: '#121214', bg_panel: '#1a1a20', bg_input: '#262630', bg_hover: '#22222a', text: '#ffffff', text_muted: '#95a5a6', accent: '#2ecc71', border: '#2a2a34', th_bg: '#1e1e26' },
    light: { bg_main: '#f0f2f5', bg_panel: '#ffffff', bg_input: '#e8eaef', bg_hover: '#f4f6f8', text: '#111827', text_muted: '#6b7280', accent: '#10b981', border: '#d1d5db', th_bg: '#f3f4f6' },
    oled:  { bg_main: '#000000', bg_panel: '#08080a', bg_input: '#121216', bg_hover: '#16161c', text: '#f5f5f5', text_muted: '#888894', accent: '#2ecc71', border: '#1c1c22', th_bg: '#0d0d10' }
};

const NEON_PRESETS = [
    { c1: '#00f5d4', c2: '#9b5de5', label: 'Бирюза → Фиолет' },
    { c1: '#ff9f1c', c2: '#ff4d6d', label: 'Оранж → Коралл' },
    { c1: '#2ecc71', c2: '#10b981', label: 'Лайм → Изумруд' },
    { c1: '#38bdf8', c2: '#6366f1', label: 'Электрик → Индиго' },
    { c1: '#f72585', c2: '#7209b7', label: 'Неон → Маджента' }
];

const AVAILABLE_FONTS = [
    { name: 'Segoe UI', label: 'Segoe UI / System UI', web: false, css: "'Segoe UI', system-ui, -apple-system, sans-serif" },
    { name: 'Inter', label: 'Inter', web: true, css: "'Inter', sans-serif" },
    { name: 'Roboto', label: 'Roboto', web: true, css: "'Roboto', sans-serif" },
    { name: 'Open Sans', label: 'Open Sans', web: true, css: "'Open Sans', sans-serif" },
    { name: 'JetBrains Mono', label: 'JetBrains Mono', web: true, css: "'JetBrains Mono', monospace" },
    { name: 'Fira Code', label: 'Fira Code', web: true, css: "'Fira Code', monospace" }
];

function getUiSettings() {
    if (typeof CURRENT_UI_SETTINGS !== 'undefined' && CURRENT_UI_SETTINGS) return CURRENT_UI_SETTINGS;
    try {
        const raw = localStorage.getItem('tbr_ui_settings');
        if (raw) return JSON.parse(raw);
    } catch (e) {}
    return {
        theme: 'dark',
        custom_colors: { bg_main: '#121214', bg_panel: '#1a1a20', text: '#ffffff', accent: '#2ecc71' },
        font: 'Segoe UI', allow_google_fonts: false, mobile_mode: true,
        charts: {
            daily:  { color: '#2ecc71', color2: '#10b981', gradient: true, opacity: 0.75 },
            top5:   { color: '#ff9f1c', color2: '#ff4d6d', gradient: true, opacity: 0.8 },
            hourly: { color: '#00f5d4', color2: '#9b5de5', gradient: true, opacity: 0.35 }
        },
        peer_client_colors: {
            "qBittorrent": "#2ecc71", "Transmission": "#e74c3c", "uTorrent": "#27ae60",
            "Deluge": "#3498db", "BiglyBT": "#9b59b6", "Aria2": "#1abc9c",
            "Tixati": "#f39c12", "Vuze": "#00bcd4", "libtorrent": "#95a5a6", "Прочие": "#64748b"
        }
    };
}

function hexToRgb(hex) {
    const m = String(hex || '#2ecc71').replace('#', '').match(/^([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
    if (!m) return { r: 46, g: 204, b: 113 };
    return { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) };
}

function applyUiSettings(ui) {
    if (!ui) return;
    const root = document.documentElement;
    const theme = ui.theme || 'dark';
    let palette = THEME_PRESETS[theme] || THEME_PRESETS.dark;

    if (theme === 'custom' && ui.custom_colors) {
        const c = ui.custom_colors;
        const isDark = hexToRgb(c.bg_main).r * 0.299 + hexToRgb(c.bg_main).g * 0.587 + hexToRgb(c.bg_main).b * 0.114 < 128;
        palette = {
            bg_main: c.bg_main || '#121214', bg_panel: c.bg_panel || '#1a1a20',
            bg_input: isDark ? '#262630' : '#e8eaef', bg_hover: isDark ? '#22222a' : '#f4f6f8',
            text: c.text || '#ffffff', text_muted: isDark ? '#95a5a6' : '#6b7280',
            accent: c.accent || '#2ecc71', border: isDark ? '#2a2a34' : '#d1d5db',
            th_bg: isDark ? '#1e1e26' : '#f3f4f6'
        };
    }

    for (const [k, v] of Object.entries(palette)) root.style.setProperty(`--${k.replace('_', '-')}`, v);
    document.body.dataset.theme = theme;
    document.body.classList.toggle('mobile-cards-on', ui.mobile_mode !== false);
    if (typeof updateMobileCardsBtn === 'function') updateMobileCardsBtn();

    const fontObj = AVAILABLE_FONTS.find(f => f.name === ui.font) || AVAILABLE_FONTS[0];
    root.style.setProperty('--app-font', fontObj.css);

    if (typeof syncAnalyticsControlsFromUi === 'function') syncAnalyticsControlsFromUi();
    if (typeof applySummarySortAndRender === 'function' && typeof rawSummaryItems !== 'undefined' && rawSummaryItems.length) {
        applySummarySortAndRender();
    }
    if (typeof applyAnalyticsVisualSettingsLocally === 'function' && document.getElementById('tab-analytics')?.classList.contains('active')) {
        applyAnalyticsVisualSettingsLocally(ui);
    }
}

async function persistUiSettings(ui) {
    if (typeof CURRENT_UI_SETTINGS !== 'undefined') CURRENT_UI_SETTINGS = ui;
    localStorage.setItem('tbr_ui_settings', JSON.stringify(ui));
    applyUiSettings(ui);
    if (typeof CURRENT_ROLE === 'undefined' || CURRENT_ROLE === 'admin') {
        try { await api('/api/profile/ui', 'POST', ui); } catch (e) {}
    }
}

function openCustomizeModal() {
    const ui = getUiSettings();
    document.getElementById('cust-theme').value = ui.theme || 'dark';
    const cc = ui.custom_colors || {};
    document.getElementById('cust-bg-main').value = cc.bg_main || '#121214';
    document.getElementById('cust-bg-panel').value = cc.bg_panel || '#1a1a20';
    document.getElementById('cust-text').value = cc.text || '#ffffff';
    document.getElementById('cust-accent').value = cc.accent || '#2ecc71';
    document.getElementById('cust-custom-colors').classList.toggle('hidden', (ui.theme || 'dark') !== 'custom');

    const fontSel = document.getElementById('cust-font');
    fontSel.innerHTML = '';
    AVAILABLE_FONTS.forEach(f => {
        const opt = document.createElement('option');
        opt.value = f.name; opt.textContent = f.label;
        fontSel.appendChild(opt);
    });
    fontSel.value = ui.font || 'Segoe UI';
    document.getElementById('cust-allow-gf').checked = Boolean(ui.allow_google_fonts);
    document.getElementById('cust-mobile-mode').checked = (ui.mobile_mode !== false);

    renderChartEditors(ui.charts || {});
    renderClientColorEditors(ui.peer_client_colors || {});
    document.getElementById('customize-modal').style.display = 'flex';
}

function closeCustomizeModal() { document.getElementById('customize-modal').style.display = 'none'; }
function onCustThemeChange() { document.getElementById('cust-custom-colors').classList.toggle('hidden', document.getElementById('cust-theme').value !== 'custom'); }

function renderChartEditors(chartsCfg) {
    const box = document.getElementById('cust-charts-editors');
    box.innerHTML = '';
    const defs = [
        { key: 'daily', title: '1. По дням (GiB)', def1: '#2ecc71', def2: '#10b981' },
        { key: 'top5', title: '2. Топ-N раздач (горизонтальный)', def1: '#ff9f1c', def2: '#ff4d6d' },
        { key: 'hourly', title: '3. Скорость нагрузки', def1: '#00f5d4', def2: '#9b5de5' }
    ];
    defs.forEach(d => {
        const cfg = chartsCfg[d.key] || { color: d.def1, color2: d.def2, gradient: true, opacity: 0.7 };
        const c1 = cfg.color || d.def1, c2 = cfg.color2 || cfg.color || d.def2;
        const div = document.createElement('div');
        div.style.cssText = 'background:var(--bg-input); padding:8px; border-radius:6px; margin-bottom:8px;';
        div.innerHTML = `
            <div class="row-between mb-8">
                <b style="font-size:12px;">${d.title}</b>
                <label class="row-gap lbl-xs pointer"><input type="checkbox" id="cc-${d.key}-grad" ${cfg.gradient !== false ? 'checked' : ''}> Градиент</label>
            </div>
            <div class="row-wrap" style="gap:8px;">
                <div class="row-gap"><span class="lbl-xs">Цвет 1:</span><input type="color" id="cc-${d.key}-c1" value="${c1}"></div>
                <div class="row-gap"><span class="lbl-xs">Цвет 2:</span><input type="color" id="cc-${d.key}-c2" value="${c2}"></div>
                <div class="row-gap"><span class="lbl-xs">Прозрачность:</span><input type="range" id="cc-${d.key}-op" min="0.1" max="1" step="0.05" value="${cfg.opacity ?? 0.7}" style="width:75px;"></div>
            </div>
            <div class="row-wrap mt-10" style="gap:4px;">
                <span class="lbl-xs muted-text" style="width:100%;">Неоновые пары:</span>
                ${NEON_PRESETS.map(p => `<button type="button" class="btn btn-secondary btn-xs" style="font-size:10px; padding:2px 6px;" onclick="applyNeonPreset('${d.key}','${p.c1}','${p.c2}')"><span style="display:inline-block;width:8px;height:8px;background:${p.c1};border-radius:2px;"></span><span style="display:inline-block;width:8px;height:8px;background:${p.c2};border-radius:2px;"></span> ${p.label}</button>`).join('')}
            </div>
        `;
        box.appendChild(div);
    });
}

function applyNeonPreset(key, c1, c2) {
    const el1 = document.getElementById(`cc-${key}-c1`), el2 = document.getElementById(`cc-${key}-c2`);
    if (el1) el1.value = c1; if (el2) el2.value = c2;
}

function renderClientColorEditors(clientColors) {
    let box = document.getElementById('cust-clients-editors');
    if (!box) {
        box = document.createElement('div');
        box.id = 'cust-clients-editors';
        box.innerHTML = '<div class="card-title mt-10">👥 ЦВЕТА КЛИЕНТОВ ПИРОВ</div><div id="cust-clients-grid" class="grid-2" style="gap:6px;"></div>';
        document.getElementById('cust-charts-editors').after(box);
    }
    const grid = document.getElementById('cust-clients-grid');
    grid.innerHTML = '';
    const defs = { "qBittorrent": "#2ecc71", "Transmission": "#e74c3c", "uTorrent": "#27ae60", "Deluge": "#3498db", "BiglyBT": "#9b59b6", "Aria2": "#1abc9c", "Tixati": "#f39c12", "Vuze": "#00bcd4", "libtorrent": "#95a5a6", "Прочие": "#64748b" };
    for (const [name, defCol] of Object.entries(defs)) {
        const row = document.createElement('div');
        row.className = 'row-between';
        row.style.cssText = 'background:var(--bg-input); padding:4px 8px; border-radius:5px; font-size:11px;';
        row.innerHTML = `<span>${name}</span><input type="color" class="client-col-inp" data-client="${name}" value="${clientColors[name] || defCol}">`;
        grid.appendChild(row);
    }
}

async function saveCustomization() {
    const ui = getUiSettings();
    ui.theme = document.getElementById('cust-theme').value;
    ui.custom_colors = {
        bg_main: document.getElementById('cust-bg-main').value, bg_panel: document.getElementById('cust-bg-panel').value,
        text: document.getElementById('cust-text').value, accent: document.getElementById('cust-accent').value
    };
    ui.font = document.getElementById('cust-font').value;
    ui.allow_google_fonts = document.getElementById('cust-allow-gf').checked;
    ui.mobile_mode = document.getElementById('cust-mobile-mode').checked;
    ui.charts = ui.charts || {};
    ['daily', 'top5', 'hourly'].forEach(k => {
        ui.charts[k] = {
            color: document.getElementById(`cc-${k}-c1`)?.value || '#2ecc71', color2: document.getElementById(`cc-${k}-c2`)?.value || '#10b981',
            gradient: document.getElementById(`cc-${k}-grad`)?.checked !== false, opacity: parseFloat(document.getElementById(`cc-${k}-op`)?.value) || 0.7
        };
    });
    ui.peer_client_colors = ui.peer_client_colors || {};
    document.querySelectorAll('.client-col-inp').forEach(inp => { ui.peer_client_colors[inp.dataset.client] = inp.value; });
    await persistUiSettings(ui);
    closeCustomizeModal();
}

document.addEventListener('DOMContentLoaded', () => applyUiSettings(getUiSettings()));