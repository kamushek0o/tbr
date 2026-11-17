// web/static/customizer.js
const THEME_PRESETS = {
    dark:  { bg_main: '#121214', bg_panel: '#1a1a20', bg_input: '#262630', bg_hover: '#22222a', text: '#ffffff', text_muted: '#95a5a6', accent: '#2ecc71', border: '#2a2a34', th_bg: '#1e1e26' },
    light: { bg_main: '#f0f2f5', bg_panel: '#ffffff', bg_input: '#e8eaef', bg_hover: '#f4f6f8', text: '#111827', text_muted: '#6b7280', accent: '#10b981', border: '#d1d5db', th_bg: '#f3f4f6' },
    oled:  { bg_main: '#000000', bg_panel: '#08080a', bg_input: '#121216', bg_hover: '#16161c', text: '#f5f5f5', text_muted: '#888894', accent: '#2ecc71', border: '#1c1c22', th_bg: '#0d0d10' }
};

const POPULAR_PALETTE = ['#2ecc71', '#3498db', '#e67e22', '#9b59b6', '#e74c3c', '#1abc9c', '#f1c40f', '#ec4899'];

const AVAILABLE_FONTS = [
    { name: 'Segoe UI', label: 'Segoe UI / System UI', web: false, css: "'Segoe UI', system-ui, -apple-system, sans-serif" },
    { name: 'Inter', label: 'Inter', web: true, css: "'Inter', sans-serif" },
    { name: 'Roboto', label: 'Roboto', web: true, css: "'Roboto', sans-serif" },
    { name: 'Open Sans', label: 'Open Sans', web: true, css: "'Open Sans', sans-serif" },
    { name: 'Montserrat', label: 'Montserrat', web: true, css: "'Montserrat', sans-serif" },
    { name: 'Nunito', label: 'Nunito', web: true, css: "'Nunito', sans-serif" },
    { name: 'Rubik', label: 'Rubik', web: true, css: "'Rubik', sans-serif" },
    { name: 'PT Sans', label: 'PT Sans', web: true, css: "'PT Sans', sans-serif" },
    { name: 'Ubuntu', label: 'Ubuntu', web: true, css: "'Ubuntu', sans-serif" },
    { name: 'Arial', label: 'Arial', web: false, css: "Arial, Helvetica, sans-serif" },
    { name: 'JetBrains Mono', label: 'JetBrains Mono', web: true, css: "'JetBrains Mono', monospace" },
    { name: 'Fira Code', label: 'Fira Code', web: true, css: "'Fira Code', monospace" },
    { name: 'Roboto Mono', label: 'Roboto Mono', web: true, css: "'Roboto Mono', monospace" },
    { name: 'Consolas', label: 'Consolas', web: false, css: "Consolas, monospace" },
    { name: 'Georgia', label: 'Georgia', web: false, css: "Georgia, serif" },
    { name: 'Comic Sans MS', label: 'Comic Sans MS', web: false, css: "'Comic Sans MS', cursive, sans-serif" }
];

const DEFAULT_CHARTS_CFG = {
    daily:  { color: '#2ecc71', gradient: false, opacity: 0.7 },
    top5:   { color: '#e67e22', gradient: false, opacity: 0.7 },
    hourly: { color: '#3498db', gradient: true,  opacity: 0.25 }
};

function getUiSettings() {
    if (typeof CURRENT_UI_SETTINGS !== 'undefined' && CURRENT_UI_SETTINGS) return CURRENT_UI_SETTINGS;
    try {
        const raw = localStorage.getItem('tbr_ui_settings');
        if (raw) return JSON.parse(raw);
    } catch (e) {}
    return {
        theme: 'dark',
        custom_colors: { bg_main: '#121214', bg_panel: '#1a1a20', text: '#ffffff', accent: '#2ecc71' },
        font: 'Segoe UI',
        allow_google_fonts: false,
        mobile_mode: true,
        charts: JSON.parse(JSON.stringify(DEFAULT_CHARTS_CFG)),
        summary_columns: {
            visible: ['name', 'size', 'uploaded', 'ratio', 'speed_all_time', 'speed_1h', 'speed_24h', 'vol_hour', 'vol_day', 'ratio_h_all', 'created'],
            order: ['name', 'size', 'uploaded', 'ratio', 'speed_all_time', 'speed_1h', 'speed_24h', 'vol_hour', 'vol_day', 'ratio_h_all', 'created'],
            widths: {}
        }
    };
}

function hexToRgb(hex) {
    const m = String(hex || '#2ecc71').replace('#', '').match(/^([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
    if (!m) return { r: 46, g: 204, b: 113 };
    return { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) };
}

function rgbToHex(r, g, b) {
    const clamp = v => Math.max(0, Math.min(255, parseInt(v) || 0)).toString(16).padStart(2, '0');
    return `#${clamp(r)}${clamp(g)}${clamp(b)}`;
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
            bg_main: c.bg_main || '#121214',
            bg_panel: c.bg_panel || '#1a1a20',
            bg_input: isDark ? '#262630' : '#e8eaef',
            bg_hover: isDark ? '#22222a' : '#f4f6f8',
            text: c.text || '#ffffff',
            text_muted: isDark ? '#95a5a6' : '#6b7280',
            accent: c.accent || '#2ecc71',
            border: isDark ? '#2a2a34' : '#d1d5db',
            th_bg: isDark ? '#1e1e26' : '#f3f4f6'
        };
    }

    root.style.setProperty('--bg-main', palette.bg_main);
    root.style.setProperty('--bg-panel', palette.bg_panel);
    root.style.setProperty('--bg-input', palette.bg_input);
    root.style.setProperty('--bg-hover', palette.bg_hover);
    root.style.setProperty('--text', palette.text);
    root.style.setProperty('--text-muted', palette.text_muted);
    root.style.setProperty('--accent', palette.accent);
    root.style.setProperty('--border', palette.border);
    root.style.setProperty('--th-bg', palette.th_bg);
    document.body.dataset.theme = theme;

    // Мобильный режим
    document.body.classList.toggle('mobile-cards-on', ui.mobile_mode !== false);

    // Шрифт + Google Fonts строго по согласию
    const fontObj = AVAILABLE_FONTS.find(f => f.name === ui.font) || AVAILABLE_FONTS[0];
    root.style.setProperty('--app-font', fontObj.css);
    if (fontObj.web && ui.allow_google_fonts) {
        loadGoogleFont(fontObj.name);
    }
    updateFontNote(fontObj);

    if (typeof loadAnalyticsCharts === 'function' && document.getElementById('tab-analytics')?.classList.contains('active')) {
        loadAnalyticsCharts();
    }
}

function loadGoogleFont(fontName) {
    const id = 'gf-' + fontName.replace(/\s+/g, '-').toLowerCase();
    if (document.getElementById(id)) return;
    const link = document.createElement('link');
    link.id = id;
    link.rel = 'stylesheet';
    link.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(fontName)}:wght@400;600;700;800&display=swap`;
    document.head.appendChild(link);
}

function updateFontNote(fontObj) {
    const note = document.getElementById('cust-font-note');
    if (!note || !fontObj) return;
    const hasLocal = document.fonts ? document.fonts.check(`12px "${fontObj.name}"`) : true;
    if (fontObj.web && !hasLocal) {
        note.textContent = '⚠️ Нет локально — отметьте согласие ниже для подгрузки с Google Fonts.';
    } else {
        note.textContent = '';
    }
}

async function persistUiSettings(ui) {
    if (typeof CURRENT_UI_SETTINGS !== 'undefined') CURRENT_UI_SETTINGS = ui;
    localStorage.setItem('tbr_ui_settings', JSON.stringify(ui));
    applyUiSettings(ui);
    if (typeof CURRENT_ROLE === 'undefined' || CURRENT_ROLE === 'admin') {
        try {
            await api('/api/profile/ui', 'POST', ui);
        } catch (e) {}
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
        opt.value = f.name;
        opt.textContent = f.web ? `${f.label} (Google Fonts)` : f.label;
        fontSel.appendChild(opt);
    });
    fontSel.value = ui.font || 'Segoe UI';
    document.getElementById('cust-allow-gf').checked = Boolean(ui.allow_google_fonts);
    document.getElementById('cust-mobile-mode').checked = (ui.mobile_mode !== false);
    updateFontNote(AVAILABLE_FONTS.find(f => f.name === fontSel.value));

    renderChartEditors(ui.charts || DEFAULT_CHARTS_CFG);
    document.getElementById('customize-modal').style.display = 'flex';
}

function closeCustomizeModal() {
    document.getElementById('customize-modal').style.display = 'none';
}

function onCustThemeChange() {
    const val = document.getElementById('cust-theme').value;
    document.getElementById('cust-custom-colors').classList.toggle('hidden', val !== 'custom');
}

function renderChartEditors(chartsCfg) {
    const box = document.getElementById('cust-charts-editors');
    box.innerHTML = '';
    const defs = [
        { key: 'daily', title: '1. По дням (GiB)' },
        { key: 'top5', title: '2. Топ-5 раздач' },
        { key: 'hourly', title: '3. По часам суток' }
    ];
    defs.forEach(d => {
        const cfg = (chartsCfg && chartsCfg[d.key]) || DEFAULT_CHARTS_CFG[d.key];
        const rgb = hexToRgb(cfg.color);
        const div = document.createElement('div');
        div.style.cssText = 'background:var(--bg-input); padding:8px; border-radius:6px; margin-bottom:8px;';
        div.innerHTML = `
            <div class="row-between mb-8">
                <b style="font-size:12px;">${d.title}</b>
                <button type="button" class="btn btn-secondary btn-xs" onclick="resetSingleChart('${d.key}')">Сброс</button>
            </div>
            <div class="row-wrap" style="gap:6px;">
                <input type="color" id="cc-${d.key}-picker" value="${cfg.color}" oninput="syncChartColorFromHex('${d.key}', this.value)">
                <input type="text" id="cc-${d.key}-hex" value="${cfg.color}" class="form-control" style="width:78px;" oninput="syncChartColorFromHex('${d.key}', this.value)">
                <input type="number" id="cc-${d.key}-r" value="${rgb.r}" min="0" max="255" class="form-control" style="width:52px;" title="R" oninput="syncChartColorFromRgb('${d.key}')">
                <input type="number" id="cc-${d.key}-g" value="${rgb.g}" min="0" max="255" class="form-control" style="width:52px;" title="G" oninput="syncChartColorFromRgb('${d.key}')">
                <input type="number" id="cc-${d.key}-b" value="${rgb.b}" min="0" max="255" class="form-control" style="width:52px;" title="B" oninput="syncChartColorFromRgb('${d.key}')">
                <label class="row-gap lbl-xs pointer"><input type="checkbox" id="cc-${d.key}-grad" ${cfg.gradient ? 'checked' : ''}> Градиент</label>
                <input type="range" id="cc-${d.key}-op" min="0.1" max="1" step="0.05" value="${cfg.opacity ?? 0.7}" style="width:75px;" title="Прозрачность">
            </div>
            <div class="row-gap mt-10" style="margin-top:6px;">
                ${POPULAR_PALETTE.map(c => `<span onclick="syncChartColorFromHex('${d.key}','${c}')" style="width:16px;height:16px;border-radius:3px;background:${c};display:inline-block;cursor:pointer;border:1px solid #000;"></span>`).join('')}
            </div>
        `;
        box.appendChild(div);
    });
}

function syncChartColorFromHex(key, hex) {
    if (!/^#[0-9a-f]{6}$/i.test(hex)) return;
    document.getElementById(`cc-${key}-picker`).value = hex;
    document.getElementById(`cc-${key}-hex`).value = hex;
    const rgb = hexToRgb(hex);
    document.getElementById(`cc-${key}-r`).value = rgb.r;
    document.getElementById(`cc-${key}-g`).value = rgb.g;
    document.getElementById(`cc-${key}-b`).value = rgb.b;
}

function syncChartColorFromRgb(key) {
    const r = document.getElementById(`cc-${key}-r`).value;
    const g = document.getElementById(`cc-${key}-g`).value;
    const b = document.getElementById(`cc-${key}-b`).value;
    const hex = rgbToHex(r, g, b);
    document.getElementById(`cc-${key}-picker`).value = hex;
    document.getElementById(`cc-${key}-hex`).value = hex;
}

function resetSingleChart(key) {
    const def = DEFAULT_CHARTS_CFG[key];
    syncChartColorFromHex(key, def.color);
    document.getElementById(`cc-${key}-grad`).checked = def.gradient;
    document.getElementById(`cc-${key}-op`).value = def.opacity;
}

async function saveCustomization() {
    const ui = getUiSettings();
    ui.theme = document.getElementById('cust-theme').value;
    ui.custom_colors = {
        bg_main: document.getElementById('cust-bg-main').value,
        bg_panel: document.getElementById('cust-bg-panel').value,
        text: document.getElementById('cust-text').value,
        accent: document.getElementById('cust-accent').value
    };
    ui.font = document.getElementById('cust-font').value;
    ui.allow_google_fonts = document.getElementById('cust-allow-gf').checked;
    ui.mobile_mode = document.getElementById('cust-mobile-mode').checked;

    ui.charts = {};
    ['daily', 'top5', 'hourly'].forEach(k => {
        ui.charts[k] = {
            color: document.getElementById(`cc-${k}-hex`).value || DEFAULT_CHARTS_CFG[k].color,
            gradient: document.getElementById(`cc-${k}-grad`).checked,
            opacity: parseFloat(document.getElementById(`cc-${k}-op`).value) || 0.7
        };
    });

    await persistUiSettings(ui);
    closeCustomizeModal();
}

// Сразу применяем кэшированное оформление при старте, чтобы не мигало
document.addEventListener('DOMContentLoaded', () => applyUiSettings(getUiSettings()));