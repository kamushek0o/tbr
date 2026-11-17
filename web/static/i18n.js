// web/static/i18n.js
const I18N = { ru: I18N_RU, en: I18N_EN };
let currentLang = localStorage.getItem('tbr_lang') || 'ru';

function t(key, vars = {}) {
    let str = (I18N[currentLang] && I18N[currentLang][key]) || I18N.ru[key] || key;
    for (const [k, v] of Object.entries(vars)) {
        str = str.replace(new RegExp(`\\{${k}\\}`, 'g'), v);
    }
    return str;
}

function trBackend(str) {
    if (!str || currentLang === 'ru') return str || '';
    const s = String(str);
    if (s === 'ожидание замера') return 'waiting for snapshot';
    if (s === 'прошлый полный час (<5м нового)') return 'previous full hour (<5m elapsed)';
    if (s === 'по снимку ~1ч назад') return 'from snapshot ~1h ago';
    if (s === 'расчётное от суток') return 'estimated from 24h';
    const mMin = s.match(/^прошло\s+(\d+)\s+мин\s+с\s+техлога$/);
    if (mMin) return `${mMin[1]} min since last snapshot`;
    if (s === 'Дата неизвестна') return 'Unknown date';

    return s
        .replace(/МБ\/день/g, 'MB/day')
        .replace(/МБ\/ч/g, 'MB/h')
        .replace(/\/\s*час/g, '/ h')
        .replace(/\/\s*день/g, '/ day')
        .replace(/\/ч/g, '/h')
        .replace(/МБ/g, 'MB');
}

function applyI18n() {
    document.title = t('title');
    document.querySelectorAll('[data-i18n]').forEach(el => {
        el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll('[data-i18n-ph]').forEach(el => {
        el.placeholder = t(el.dataset.i18nPh);
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
        el.title = t(el.dataset.i18nTitle);
    });
    const btn = document.getElementById('lang-toggle-btn');
    if (btn) btn.textContent = currentLang === 'ru' ? '🌐 RU' : '🌐 EN';
}

function toggleLang() {
    currentLang = currentLang === 'ru' ? 'en' : 'ru';
    localStorage.setItem('tbr_lang', currentLang);
    applyI18n();
    if (typeof checkQbStatus === 'function') checkQbStatus();
    if (typeof filterTorrents === 'function' && torrentsData.length) filterTorrents();
    if (typeof renderSummaryMeta === 'function') renderSummaryMeta();
    if (typeof applySummarySortAndRender === 'function' && rawSummaryItems.length) applySummarySortAndRender();
    if (typeof populateAnalyticsSelectors === 'function' && rawSummaryItems.length) populateAnalyticsSelectors();
    if (typeof onSmartCalcTargetChange === 'function') onSmartCalcTargetChange();
    if (typeof renderRules === 'function' && currentRules.length) renderRules(currentRules);
}