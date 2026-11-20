// web/static/hardcore_ui.js
async function loadSmartStatus() {
    const box = document.getElementById('smart-hdd-box');
    if (!box) return;
    box.innerHTML = '⏳ Опрос smartctl...';
    const [sRes, qRes] = await Promise.all([api('/api/hdd/smart'), api('/api/recheck_queue')]);
    const s = await sRes.json();
    const q = qRes.ok ? ((await qRes.json()).queue || []) : [];

    let html = `<div class="lbl-xs mb-8">Очередь речеков (1 на диск): <b>${q.length}</b> шт.</div>`;
    if (!s.available) {
        html += `<div class="lbl-xs muted-text">ℹ️ SMART: ${escapeHtml(s.reason)}</div>`;
    } else {
        html += (s.disks || []).map(d => `
            <div class="row-between" style="background:var(--bg-input); padding:4px 8px; border-radius:5px; margin-bottom:4px;">
                <span><b>${escapeHtml(d.model)}</b> (${escapeHtml(d.device)})</span>
                <span class="badge ${d.passed ? 'badge-up' : 'badge-err'}">${d.passed ? 'OK' : 'FAIL'} ${d.temp_c ? `• ${d.temp_c}°C` : ''}</span>
            </div>
        `).join('');
    }
    box.innerHTML = html;
}

async function enqueueSelectedRecheck() {
    if (typeof selectedHash === 'undefined' || !selectedHash) return alert(t('err_select_torrent'));
    const res = await api('/api/recheck_queue', 'POST', { hash: selectedHash });
    const d = await res.json();
    if (!res.ok) return alert(d.error || 'Ошибка');
    alert(`💽 Поставлено в безопасную очередь речека (в очереди: ${(d.queue || []).length})`);
}

async function checkRssDuplicates() {
    const box = document.getElementById('rss-dedup-box');
    if (!box) return;
    box.innerHTML = '⏳ Проверка RSS-лент через API qB...';
    const res = await api('/api/rss/dedup');
    const d = await res.json();
    if (!d.success) { box.innerHTML = `<span class="lbl-xs muted-text">${escapeHtml(d.error)}</span>`; return; }
    const dups = (d.items || []).filter(x => x.is_duplicate);
    if (!dups.length) {
        box.innerHTML = `<span class="lbl-xs accent-txt">✅ Проверено релизов: ${d.total}, дубликатов не найдено.</span>`;
        return;
    }
    box.innerHTML = `<div class="lbl-xs orange-txt mb-8">Найдено дублей: ${dups.length} из ${d.total}</div>` + dups.slice(0, 15).map(x => `
        <div class="lbl-xs mb-8" style="background:var(--bg-input); padding:4px 8px; border-radius:5px;">
            <b>${escapeHtml(x.title)}</b> (${x.similarity}%)<div class="muted-text">Уже есть: ${escapeHtml(x.matched_name)}</div>
        </div>
    `).join('');
}

async function loadInspectorMediaInfo(tHash) {
    const box = document.getElementById('insp-mediainfo-box');
    if (!box) return;
    box.innerHTML = '<span class="lbl-xs muted-text">⏳ Чтение метаданных видео...</span>';
    const res = await api(`/api/torrents/mediainfo?hash=${encodeURIComponent(tHash)}`);
    const d = await res.json();
    if (!d.success) { box.innerHTML = `<span class="lbl-xs muted-text">${escapeHtml(d.error || 'Нет видео')}</span>`; return; }
    box.innerHTML = (d.items || []).map(m => `
        <div class="lbl-xs" style="background:var(--bg-input); padding:5px 8px; border-radius:5px; margin-bottom:4px;">
            <b>🎬 ${escapeHtml(m.file)}</b> (${escapeHtml(m.size_fmt)}, ${escapeHtml(m.duration_fmt)})<br>
            <span class="muted-text">Видео: ${escapeHtml(m.video)} • Битрейт: ${escapeHtml(m.bitrate_fmt)} • Аудио: ${escapeHtml(m.audio)} • Субтитры: ${escapeHtml(m.subtitles)}</span>
        </div>
    `).join('');
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelector('button[onclick*="openTorrentInspectorModal"]')?.addEventListener('click', () => {
        setTimeout(() => { if (typeof selectedHash !== 'undefined' && selectedHash) loadInspectorMediaInfo(selectedHash); }, 120);
    });
});