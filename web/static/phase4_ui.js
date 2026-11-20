// web/static/phase4_ui.js
let _hmMode = '365';
let _inspFilesPage = 1;

async function toggleHeatmapMode(mode) {
    _hmMode = mode;
    document.getElementById('heatmap-grid')?.classList.toggle('hidden', mode !== '365');
    document.getElementById('rhythm-7x24-box')?.classList.toggle('hidden', mode !== '7x24');
    if (mode === '7x24') {
        const box = document.getElementById('rhythm-7x24-box');
        box.innerHTML = '<span class="muted-text">⏳ Расчёт медианы 7×24...</span>';
        const res = await api('/api/analytics/rhythm');
        const d = await res.json();
        const days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
        const maxM = Math.max(0.1, d.max_mbs || 0.1);
        let html = '<table style="font-size:10px; text-align:center;"><thead><tr><th></th>' + Array.from({ length: 24 }, (_, h) => `<th>${h}</th>`).join('') + '</tr></thead><tbody>';
        (d.matrix || []).forEach((row, wd) => {
            html += `<tr><td><b>${days[wd]}</b></td>` + row.map((v, hr) => {
                const op = v > 0 ? Math.min(1, 0.15 + (v / maxM) * 0.85) : 0.05;
                return `<td title="${days[wd]} ${hr}:00 — ${v} MiB/s" style="background:rgba(46,204,113,${op.toFixed(2)}); padding:3px 2px;">${v >= 1 ? Math.round(v) : ''}</td>`;
            }).join('') + '</tr>';
        });
        box.innerHTML = html + '</tbody></table>';
    }
}

async function loadDayHourlyBreakdown(dateStr) {
    const out = document.getElementById('heatmap-day-detail');
    if (!out) return;
    out.classList.remove('hidden');
    out.innerHTML = `⏳ Загрузка часов за ${escapeHtml(dateStr)}...`;
    const res = await api(`/api/analytics/day_hourly?date=${encodeURIComponent(dateStr)}`);
    const d = await res.json();
    if (!d.success) { out.textContent = d.error || 'Ошибка'; return; }
    if (!d.has_detail) { out.innerHTML = `📅 <b>${escapeHtml(dateStr)}</b>: детальные почасовые точки за этот архивный день отсутствуют.`; return; }
    out.innerHTML = `<b>📅 ${escapeHtml(dateStr)} по часам:</b> ` + (d.hours || []).filter(h => h.bytes > 0).map(h => `<span class="badge badge-up" style="margin:2px;">${h.hour}: ${escapeHtml(h.fmt)}</span>`).join('') || 'Нулевая активность';
}

async function loadDeepAnalyticsWidgets() {
    loadRunwayAndQuota();
    loadTreemap('tags');
    loadSwarmAnalytics();
    refreshActivityTicker();
}

async function loadRunwayAndQuota() {
    try {
        const [rRes, qRes] = await Promise.all([api('/api/analytics/runway'), api('/api/analytics/quota')]);
        if (rRes.ok) {
            const r = await rRes.json();
            document.getElementById('runway-box').innerHTML = `
                <div>Диск <b>${escapeHtml(r.disk_path)}</b>: свободно <b>${escapeHtml(r.free_fmt)}</b> (после очереди: <b class="${r.guard_triggered ? 'orange-txt' : 'accent-txt'}">${escapeHtml(r.post_queue_fmt)}</b>)</div>
                <div class="lbl-xs muted-text mt-10">Темп роста (30д): ${escapeHtml(r.daily_growth_fmt)} • Запас до резерва (${r.reserve_gib} GiB): <b>${r.days_left !== null ? r.days_left + ' дн.' : '∞'}</b></div>
            `;
        }
        if (qRes.ok) {
            const q = await qRes.json();
            document.getElementById('quota-box').innerHTML = `
                <div>За месяц: <b class="accent-txt">${escapeHtml(q.used_fmt)}</b> / <b>${escapeHtml(q.quota_fmt)}</b> (${q.percent}%)</div>
                <div style="height:6px; background:var(--bg-main); border-radius:3px; overflow:hidden; margin:6px 0;"><div style="height:100%; width:${q.percent}%; background:var(--accent);"></div></div>
                <div class="lbl-xs muted-text">Прогноз к концу месяца: ~${escapeHtml(q.projected_fmt)}</div>
            `;
        }
    } catch (e) {}
}

async function saveQuotaAndReserve() {
    const quota_tib = parseFloat(document.getElementById('inp-quota-tib')?.value || 0);
    const reserve_gib = parseInt(document.getElementById('inp-reserve-gib')?.value || 20);
    await api('/api/analytics/quota', 'POST', { quota_tib, reserve_gib });
    loadRunwayAndQuota();
}

async function runABCompare() {
    const payload = {
        start_a: document.getElementById('ab-a1').value, end_a: document.getElementById('ab-a2').value,
        start_b: document.getElementById('ab-b1').value, end_b: document.getElementById('ab-b2').value,
        same_n_days: document.getElementById('ab-same-n').checked
    };
    const res = await api('/api/analytics/ab_compare', 'POST', payload);
    const d = await res.json();
    const out = document.getElementById('ab-out');
    if (!d.success) { out.textContent = `❌ ${d.error}`; return; }
    out.innerHTML = `Период A: <b>${escapeHtml(d.period_a.fmt)}</b> (${d.period_a.avg_mbs} MiB/s, пик ${d.period_a.peak_hour}) vs Период B: <b>${escapeHtml(d.period_b.fmt)}</b> (${d.period_b.avg_mbs} MiB/s, пик ${d.period_b.peak_hour}) • Дельта: <b class="accent-txt">${d.diff_pct !== null ? d.diff_pct + '%' : '—'}</b>`;
}

async function loadTreemap(groupBy = 'tags') {
    const box = document.getElementById('treemap-box');
    if (!box) return;
    const res = await api(`/api/analytics/treemap?group_by=${encodeURIComponent(groupBy)}`);
    if (!res.ok) return;
    const items = (await res.json()).items || [];
    const maxB = Math.max(1, ...items.map(x => x.bytes));
    const cols = ['#2ecc71', '#3498db', '#9b59b6', '#e67e22', '#1abc9c', '#f39c12'];
    box.innerHTML = items.map((it, idx) => {
        const flex = Math.max(12, Math.round((it.bytes / maxB) * 100));
        return `<div style="flex:${flex} 1 110px; background:${cols[idx % cols.length]}22; border:1px solid ${cols[idx % cols.length]}; border-radius:6px; padding:6px 8px; min-width:110px;">
            <div style="font-size:11px; font-weight:700; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(it.label)}</div>
            <div class="lbl-xs muted-text">${escapeHtml(it.fmt)}</div>
        </div>`;
    }).join('') || '<span class="muted-text">Нет данных</span>';
}

async function loadSwarmAnalytics() {
    const box = document.getElementById('swarm-analytics-box');
    if (!box) return;
    const res = await api('/api/analytics/swarm');
    if (!res.ok) return;
    const d = await res.json();
    const p = d.protocols || {};
    const recs = (d.slot_recs || []).map(r => `<div>${escapeHtml(r)}</div>`).join('');
    const trRows = (d.survivability || []).slice(0, 8).map(t => `<tr><td>${escapeHtml(t.tracker)}</td><td>${t.count}</td><td>${t.uptime_pct}%</td><td><b>${t.gb_roi}x</b></td><td>${t.uploaded_gb} GiB</td></tr>`).join('');
    box.innerHTML = `
        <div class="mb-8 lbl-xs"><b>📡 Протоколы (топ-${p.sampled || 0} активных):</b> uTP: <b>${p.utp || 0}</b> (${p.utp_avg_kbs || 0} KB/s) • TCP: <b>${p.tcp || 0}</b> (${p.tcp_avg_kbs || 0} KB/s) • IPv4: <b>${p.ipv4 || 0}</b> • IPv6: <b>${p.ipv6 || 0}</b></div>
        <div class="mb-8 lbl-xs" style="background:var(--bg-main); padding:6px 8px; border-radius:5px;"><b>🎛️ Авто-тюнер qB:</b>${recs}</div>
        <div class="scroll-box" style="max-height:170px;"><table><thead><tr><th>Трекер</th><th>Раздач</th><th>Аптайм</th><th>GB-ROI</th><th>Отдано</th></tr></thead><tbody>${trRows}</tbody></table></div>
    `;
}

async function loadNormalizedTitleGroups() {
    const box = document.getElementById('title-groups-box');
    box.innerHTML = '⏳ Поиск похожих релизов...';
    const res = await api('/api/analytics/title_groups');
    const groups = (await res.json()).groups || [];
    box.innerHTML = groups.map(g => `<div class="mb-8" style="background:var(--bg-main); padding:6px 8px; border-radius:6px;"><b>${escapeHtml(g.title)}</b> (${g.count} версий) — ${formatBytesJS(g.total_size)}<div class="lbl-xs muted-text">${g.items.map(x => escapeHtml(x.name)).join(' | ')}</div></div>`).join('') || '<span class="muted-text">Дубликатов версий не найдено</span>';
}

async function openWrappedModal(period = 'month') {
    document.getElementById('wrapped-modal').style.display = 'flex';
    const res = await api(`/api/analytics/wrapped?period=${encodeURIComponent(period)}`);
    const d = await res.json();
    const c = document.getElementById('wrapped-canvas'), ctx = c.getContext('2d');
    ctx.fillStyle = '#0d0d12'; ctx.fillRect(0, 0, c.width, c.height);
    const grd = ctx.createLinearGradient(0, 0, c.width, c.height);
    grd.addColorStop(0, '#10b98133'); grd.addColorStop(1, '#9b5de533');
    ctx.fillStyle = grd; ctx.fillRect(20, 20, c.width - 40, c.height - 40);
    ctx.fillStyle = '#2ecc71'; ctx.font = 'bold 34px Segoe UI, sans-serif'; ctx.fillText(`⚡ tbr PRO WRAPPED`, 50, 80);
    ctx.fillStyle = '#95a5a6'; ctx.font = 'bold 18px Segoe UI, sans-serif'; ctx.fillText(d.period_label, 50, 115);
    ctx.fillStyle = '#ffffff'; ctx.font = 'bold 42px Segoe UI, sans-serif'; ctx.fillText(d.total_uploaded_fmt, 50, 195);
    ctx.fillStyle = '#95a5a6'; ctx.font = '16px Segoe UI, sans-serif'; ctx.fillText(`Лучший день: ${d.best_day_date} (${d.best_day_fmt})`, 50, 250);
    ctx.fillText(`Спасено (Последний сид): ${d.last_seed_saved} • Раздач: ${d.visible_torrents}`, 50, 285);
    ctx.fillStyle = '#2ecc71'; ctx.fillText(`Топ теги: ${(d.top_tags || []).map(t => `${t.tag} (${t.fmt})`).join(', ') || '—'}`, 50, 330);
}

function downloadWrappedPng() {
    const a = document.createElement('a');
    a.href = document.getElementById('wrapped-canvas').toDataURL('image/png');
    a.download = `tbr_wrapped_${Date.now()}.png`;
    a.click();
}

function exportFullInventory(fmt) {
    window.location.href = `/api/inventory/export?fmt=${encodeURIComponent(fmt)}`;
}

async function refreshActivityTicker() {
    const bar = document.getElementById('live-activity-ticker');
    if (!bar) return;
    try {
        const res = await api('/api/activity/ticker');
        if (!res.ok) return;
        const evs = (await res.json()).events || [];
        bar.innerHTML = evs.length ? `📡 <b>Пульс:</b> ` + evs.slice(0, 4).map(e => `<span class="badge badge-pause">[${e.time}] ${escapeHtml(e.text)}</span>`).join(' ') : '📡 <b>Пульс:</b> ожидание событий...';
    } catch (e) {}
}

async function loadInspectorPhase4(tHash, page = 1) {
    _inspFilesPage = page;
    const [noteRes, timeRes, filesRes] = await Promise.all([
        api(`/api/torrent/notes?hash=${encodeURIComponent(tHash)}`),
        api(`/api/torrent/timeline?hash=${encodeURIComponent(tHash)}`),
        api(`/api/torrents/files?hash=${encodeURIComponent(tHash)}&page=${page}`)
    ]);
    if (noteRes.ok) document.getElementById('insp-note-inp').value = (await noteRes.json()).note || '';
    if (timeRes.ok) {
        const evs = (await timeRes.json()).events || [];
        document.getElementById('insp-timeline-box').innerHTML = evs.map(e => `<div class="lbl-xs"><b>[${escapeHtml(e.date)}]</b> ${escapeHtml(e.title)}</div>`).join('') || '<span class="muted-text lbl-xs">Событий по UID пока нет</span>';
    }
    if (filesRes.ok) {
        const fd = await filesRes.json();
        document.getElementById('insp-files-tbody').innerHTML = (fd.files || []).map(f => `
            <tr>
                <td style="white-space:normal; word-break:break-all;">${escapeHtml(f.name)}</td>
                <td>${escapeHtml(f.size_fmt)}</td>
                <td>${f.progress}%</td>
                <td><select class="form-control" style="padding:2px; font-size:11px;" onchange="setInspectorFilePrio('${escapeHtml(tHash)}', ${f.id}, this.value)"><option value="0" ${f.priority===0?'selected':''}>Пропуск</option><option value="1" ${f.priority===1?'selected':''}>Обычн.</option><option value="6" ${f.priority===6?'selected':''}>Высок.</option><option value="7" ${f.priority===7?'selected':''}>Макс.</option></select></td>
            </tr>
        `).join('') || '<tr><td colspan="4" class="center-msg">Файлы недоступны</td></tr>';
    }
}

async function saveInspectorNote() {
    if (!selectedHash) return;
    await api('/api/torrent/notes', 'POST', { hash: selectedHash, note: document.getElementById('insp-note-inp').value });
    alert('📝 Заметка сохранена (привязана к UID)');
}

async function setInspectorFilePrio(hash, id, prio) {
    await api('/api/torrents/file_prio', 'POST', { hash, id, priority: parseInt(prio) });
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('heatmap-grid')?.addEventListener('click', (e) => {
        const cell = e.target.closest('.hm-cell');
        if (cell?.title?.includes(':')) {
            const dStr = cell.title.split(':')[0].trim();
            if (/^\d{4}-\d{2}-\d{2}$/.test(dStr)) loadDayHourlyBreakdown(dStr);
        }
    });
    document.querySelector('[data-tab="analytics"]')?.addEventListener('click', () => setTimeout(loadDeepAnalyticsWidgets, 150));
    document.querySelector('button[onclick*="openTorrentInspectorModal"]')?.addEventListener('click', () => setTimeout(() => { if (selectedHash) loadInspectorPhase4(selectedHash, 1); }, 100));
});