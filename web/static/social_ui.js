// web/static/social_ui.js
let _lastAchData = null;

function updateMobileCardsBtn() {
    const btn = document.getElementById('btn-toggle-mobile-cards');
    if (!btn) return;
    const isCards = document.body.classList.contains('mobile-cards-on');
    btn.textContent = isCards ? '📱 Карточки' : '📋 Таблица';
}

function toggleMobileCardsMode() {
    if (typeof getUiSettings !== 'function' || typeof persistUiSettings !== 'function') return;
    const ui = getUiSettings();
    ui.mobile_mode = (ui.mobile_mode === false);
    persistUiSettings(ui);
    updateMobileCardsBtn();
}

function renderUploadEquivalents(totalBytes) {
    const box = document.getElementById('summary-equivalents-bar');
    if (!box) return;
    const gib = (Number(totalBytes) || 0) / (1024 ** 3);
    if (gib < 1) {
        box.classList.add('hidden');
        return;
    }
    const games = Math.max(1, Math.round(gib / 100));
    const movies = Math.max(1, Math.round(gib / 40));
    const isos = Math.max(1, Math.round(gib / 4));
    const isEn = (typeof currentLang !== 'undefined' && currentLang === 'en');

    box.innerHTML = isEn
        ? `🤯 <b>That's roughly equal to:</b> 🎮 <b>${games}</b> modern games (100 GiB) &nbsp;•&nbsp; 🎬 <b>${movies}</b> 4K UHD movies (40 GiB) &nbsp;•&nbsp; 💿 <b>${isos}</b> OS ISO images (4 GiB)`
        : `🤯 <b>Это примерно как:</b> 🎮 <b>${games}</b> совр. игр (по 100 GiB) &nbsp;•&nbsp; 🎬 <b>${movies}</b> фильмов 4K UHD (по 40 GiB) &nbsp;•&nbsp; 💿 <b>${isos}</b> образов ОС (по 4 GiB)`;
    box.classList.remove('hidden');
}

async function loadAuditLog() {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
    const tbody = document.getElementById('audit-tbody');
    if (!tbody) return;
    const cat = document.getElementById('audit-cat-filter')?.value || '';
    try {
        const res = await api(`/api/tools/audit?category=${encodeURIComponent(cat)}&limit=100`);
        if (!res.ok) return;
        const d = await res.json();
        const items = d.items || [];
        if (!items.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="center-msg">Событий по фильтру пока нет</td></tr>';
            return;
        }
        const badgeCls = { auth: 'badge-dl', automation: 'badge-up', merger: 'badge-force', system: 'badge-stall' };
        tbody.innerHTML = '';
        const frag = document.createDocumentFragment();
        items.forEach(r => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="muted-text">${escapeHtml(r.datetime)}</td>
                <td><span class="badge ${badgeCls[r.category] || 'badge-pause'}">${escapeHtml(r.category)}</span></td>
                <td><b>${escapeHtml(r.actor)}</b></td>
                <td>${escapeHtml(r.action)}</td>
                <td class="muted-text" style="white-space:normal;">${escapeHtml(r.details)}</td>
            `;
            frag.appendChild(tr);
        });
        tbody.appendChild(frag);
    } catch (e) {}
}

async function loadAchievements() {
    const grid = document.getElementById('ach-grid');
    const badge = document.getElementById('ach-progress-badge');
    if (!grid) return;
    try {
        const res = await api('/api/achievements');
        if (!res.ok) return;
        const d = await res.json();
        _lastAchData = d;
        if (badge) badge.textContent = `${d.unlocked_count || 0} / ${d.total_count || 10}`;

        const isEn = (typeof currentLang !== 'undefined' && currentLang === 'en');
        grid.innerHTML = '';
        (d.items || []).forEach(a => {
            const card = document.createElement('div');
            card.style.cssText = `background:var(--bg-input); padding:8px; border-radius:6px; border:1px solid ${a.unlocked ? 'var(--accent)' : 'var(--border)'}; opacity:${a.unlocked ? '1' : '0.48'};`;
            const title = isEn ? a.title_en : a.title;
            const desc = isEn ? a.desc_en : a.desc;
            const dateHtml = a.unlocked
                ? `<div class="lbl-xs accent-txt" style="margin-top:4px;">✅ ${escapeHtml(a.unlocked_at || '')}</div>`
                : `<div class="lbl-xs muted-text" style="margin-top:4px;">🔒 ${isEn ? 'Locked' : 'Закрыто'}</div>`;
            card.innerHTML = `
                <div style="font-size:13px; font-weight:700;">${escapeHtml(a.icon)} ${escapeHtml(title)}</div>
                <div class="lbl-xs muted-text" style="margin-top:2px;">${escapeHtml(desc)}</div>
                ${dateHtml}
            `;
            grid.appendChild(card);
        });
    } catch (e) {}
}

function _computeSeederRank(totalBytes) {
    const tib = (Number(totalBytes) || 0) / (1024 ** 4);
    if (tib >= 50) return '👑 Seedbox Overlord';
    if (tib >= 10) return '🔥 Torrent Legend';
    if (tib >= 1) return '⚡ Terabyte Knight';
    return '🌱 Rising Seeder';
}

async function openShareCardModal() {
    document.getElementById('share-card-modal').style.display = 'flex';
    if (!_lastAchData) await loadAchievements();
    renderShareCardCanvas();
}

function closeShareCardModal() {
    document.getElementById('share-card-modal').style.display = 'none';
}

function renderShareCardCanvas() {
    const canvas = document.getElementById('share-card-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const cs = getComputedStyle(document.documentElement);
    const bgMain = cs.getPropertyValue('--bg-main').trim() || '#121214';
    const bgPanel = cs.getPropertyValue('--bg-panel').trim() || '#1a1a20';
    const bgInput = cs.getPropertyValue('--bg-input').trim() || '#262630';
    const txtMain = cs.getPropertyValue('--text').trim() || '#ffffff';
    const txtMuted = cs.getPropertyValue('--text-muted').trim() || '#95a5a6';
    const accent = cs.getPropertyValue('--accent').trim() || '#2ecc71';
    const border = cs.getPropertyValue('--border').trim() || '#2a2a34';

    const W = canvas.width, H = canvas.height;
    ctx.fillStyle = bgMain;
    ctx.fillRect(0, 0, W, H);

    ctx.fillStyle = bgPanel;
    ctx.strokeStyle = border;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.roundRect(24, 24, W - 48, H - 48, 16);
    ctx.fill();
    ctx.stroke();

    // Логотип-молния
    ctx.fillStyle = accent;
    ctx.beginPath();
    ctx.moveTo(64, 48); ctx.lineTo(48, 72); ctx.lineTo(62, 72);
    ctx.lineTo(57, 92); ctx.lineTo(76, 67); ctx.lineTo(62, 67);
    ctx.closePath();
    ctx.fill();

    ctx.fillStyle = accent;
    ctx.font = 'bold 28px Segoe UI, sans-serif';
    ctx.fillText('tbr PRO', 90, 78);

    const meta = (typeof lastSummaryMeta !== 'undefined' && lastSummaryMeta) ? lastSummaryMeta : {};
    const items = (typeof rawSummaryItems !== 'undefined' && rawSummaryItems) ? rawSummaryItems : [];
    const totalUp = meta.total_uploaded || items.reduce((a, b) => a + (b.uploaded || 0), 0);
    const maxSec = items.reduce((m, x) => Math.max(m, x.active_seconds || 0), 0);
    const activeDays = Math.floor(maxSec / 86400);
    const achCount = _lastAchData ? `${_lastAchData.unlocked_count}/${_lastAchData.total_count}` : '—';

    ctx.fillStyle = txtMuted;
    ctx.font = 'bold 16px Segoe UI, sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(`${_computeSeederRank(totalUp)}  •  🏆 ${achCount}`, W - 52, 76);
    ctx.textAlign = 'left';

    const cards = [
        { lbl: 'ВСЕГО ОТДАНО', val: meta.total_uploaded_fmt || formatBytesJS(totalUp), col: accent },
        { lbl: 'ЗА 24 ЧАСА', val: meta.global_day_volume_fmt || '—', col: '#e67e22' },
        { lbl: 'РАЗДАЧ / СТАЖ', val: `${meta.total_torrents || items.length} шт. / ${activeDays} дн.`, col: '#3498db' },
    ];
    cards.forEach((c, idx) => {
        const x = 48 + idx * 272, y = 114, cw = 256, ch = 88;
        ctx.fillStyle = bgInput;
        ctx.beginPath(); ctx.roundRect(x, y, cw, ch, 10); ctx.fill();
        ctx.fillStyle = txtMuted;
        ctx.font = 'bold 12px Segoe UI, sans-serif';
        ctx.fillText(c.lbl, x + 16, y + 28);
        ctx.fillStyle = c.col;
        ctx.font = 'bold 22px Segoe UI, sans-serif';
        ctx.fillText(String(c.val).slice(0, 22), x + 16, y + 62);
    });

    const hideNames = document.getElementById('share-hide-names')?.checked ?? true;
    ctx.fillStyle = txtMuted;
    ctx.font = 'bold 13px Segoe UI, sans-serif';
    ctx.fillText(hideNames ? 'ТОП-3 РАЗДАЧИ (НАЗВАНИЯ СКРЫТЫ)' : 'ТОП-3 РАЗДАЧИ ПО ОТДАЧЕ', 48, 240);

    const top3 = [...items].sort((a, b) => (b.uploaded || 0) - (a.uploaded || 0)).slice(0, 3);
    top3.forEach((it, idx) => {
        const y = 258 + idx * 62;
        ctx.fillStyle = bgInput;
        ctx.beginPath(); ctx.roundRect(48, y, W - 96, 50, 8); ctx.fill();
        const nm = hideNames ? `*** Скрытая раздача #${idx + 1} ***` : String(it.name || '').slice(0, 56);
        ctx.fillStyle = txtMain;
        ctx.font = 'bold 16px Segoe UI, sans-serif';
        ctx.fillText(`${idx + 1}. ${nm}`, 66, y + 31);

        ctx.fillStyle = accent;
        ctx.textAlign = 'right';
        ctx.fillText(`${formatBytesJS(it.uploaded)} (${Number(it.ratio || 0).toFixed(2)}x)`, W - 66, y + 31);
        ctx.textAlign = 'left';
    });

    ctx.fillStyle = txtMuted;
    ctx.font = '12px Segoe UI, sans-serif';
    ctx.fillText(`Generated locally by tbr PRO • ${new Date().toLocaleDateString()}`, 48, H - 40);
}

function downloadShareCardPng() {
    const canvas = document.getElementById('share-card-canvas');
    if (!canvas) return;
    const a = document.createElement('a');
    a.href = canvas.toDataURL('image/png');
    a.download = `tbr_share_card_${Date.now()}.png`;
    a.click();
}

function copyShareCardPng() {
    const canvas = document.getElementById('share-card-canvas');
    if (!canvas) return;
    canvas.toBlob(async blob => {
        if (!blob) return;
        try {
            await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
            alert('✅ Карточка скопирована в буфер обмена!');
        } catch (e) {
            alert('⚠️ Копирование PNG в буфер требует HTTPS или localhost. Нажмите «Скачать PNG».');
        }
    }, 'image/png');
}