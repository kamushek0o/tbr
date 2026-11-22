// web/static/common.js
const VALID_TABS = ['torrents', 'merger', 'summary', 'analytics', 'automation', 'tools'];
const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]')?.content || '';

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

async function api(url, method = 'GET', body = null) {
    const opts = { method, headers: {} };
    if (method === 'POST') {
        opts.headers['X-CSRF-Token'] = CSRF_TOKEN;
        if (body !== null) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
    }
    const res = await fetch(url, opts);
    if (res.status === 401) {
        window.location.href = '/login';
        throw new Error('Auth required');
    }
    return res;
}

function formatBytesJS(bytes) {
    if (!bytes || bytes <= 0) return '0 B';
    const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'];
    let val = parseFloat(bytes);
    let u = 0;
    while (val >= 1024 && u < units.length - 1) { val /= 1024; u++; }
    return `${val.toFixed(2)} ${units[u]}`;
}

function parseDateToTs(str) {
    if (!str || typeof str !== 'string' || str.includes('неизвестна')) return 0;
    const parts = str.trim().split(' ');
    if (parts.length < 2) return 0;
    const dmy = parts[0].split('.');
    const hm = parts[1].split(':');
    if (dmy.length !== 3 || hm.length !== 2) return 0;
    return new Date(parseInt(dmy[2]), parseInt(dmy[1]) - 1, parseInt(dmy[0]), parseInt(hm[0]), parseInt(hm[1])).getTime();
}

function switchTab(name, updateHash = true) {
    if (!VALID_TABS.includes(name)) name = 'torrents';
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.toggle('active', c.id === 'tab-' + name));
    if (updateHash && window.location.hash !== '#' + name) window.location.hash = name;

    if (name === 'torrents') loadTorrents();
    if (name === 'merger') loadMergerLists();
    if (name === 'summary') loadSummary();
    if (name === 'analytics') loadAnalyticsTab();
    if (name === 'automation') loadAutomation();
    if (name === 'tools' && typeof loadToolsTab === 'function') loadToolsTab();
}

function refreshActiveTab() {
    const active = document.querySelector('.tab-btn.active')?.dataset.tab || 'torrents';
    if (active === 'torrents') loadTorrents(true);
    else if (active === 'summary') loadSummary(true);
    else if (active === 'analytics') loadAnalyticsTab();
    else if (active === 'automation') loadAutomation();
    else if (active === 'merger') loadTorrents(true);
    else if (active === 'tools' && typeof loadToolsTab === 'function') loadToolsTab();
    checkQbStatus();
}

function syncTabWithHash() {
    const rawHash = (window.location.hash || '').replace('#', '').trim();
    switchTab(VALID_TABS.includes(rawHash) ? rawHash : 'torrents', false);
}
window.addEventListener('hashchange', syncTabWithHash);

document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        if (typeof openCommandPalette === 'function') openCommandPalette();
    }
});

document.addEventListener('DOMContentLoaded', async () => {
    applyI18n();
    await loadMeAndApplyRole();
    syncTabWithHash();
    if (typeof initSystemStatusAndUpdates === 'function') initSystemStatusAndUpdates();
    if (typeof initTimersUi === 'function') initTimersUi();
    setInterval(checkQbStatus, 5000);
});