// web/static/analytics_insights.js
let chartPeerClients = null;
let chartTrackers = null;
let chartTorrentPersonal = null;
let _inspHash = null;

async function loadAnalyticsInsights(forceClients = false) {
    try {
        const trPer = document.getElementById('chart-trackers-period')?.value || '7d';
        const res = await api(`/api/analytics/insights?tracker_period=${encodeURIComponent(trPer)}&force_clients=${forceClients ? '1' : '0'}`);
        if (!res.ok) return;
        const d = await res.json();
        _renderRecords(d.records || {});
        _renderThrottleBadge(d.throttle || {});
        _renderHeatmap365(d.heatmap || []);
        _renderPeerClientsChart(d.clients || {});
        _renderTrackersChart(d.trackers || {});
    } catch (e) {
        console.error(e);
    }
}

function _renderRecords(r) {
    const pctFmt = p => (p === null || p === undefined) ? 'мало данных' : `${p >= 0 ? '+' : ''}${p}% к пред.`;
    document.getElementById('rec-today-val').textContent = r.today_fmt || '—';
    document.getElementById('rec-today-cmp').textContent = `Вчера: ${r.yesterday_fmt || '—'} (${pctFmt(r.day_pct)})`;
    document.getElementById('rec-week-val').textContent = r.this_week_fmt || '—';
    document.getElementById('rec-week-cmp').textContent = `Прошлая: ${r.prev_week_fmt || '—'} (${pctFmt(r.week_pct)})`;
    document.getElementById('rec-peak-val').textContent = r.peak_speed_fmt || '—';
    document.getElementById('rec-peak-date').textContent = r.peak_speed_date || '—';
    document.getElementById('rec-best-val').textContent = r.best_day_fmt || '—';
    document.getElementById('rec-best-date').textContent = r.best_day_date || '—';
}

function _renderThrottleBadge(th) {
    const b = document.getElementById('isp-throttle-badge');
    if (!b) return;
    b.classList.toggle('hidden', !th.throttled);
    if (th.throttled) {
        b.textContent = `🚧 Полка скорости ~${th.tier_mbps} Мбит/с (${th.plateau_mbs} MiB/s)`;
    }
}

function _renderHeatmap365(cells) {
    const grid = document.getElementById('heatmap-grid');
    const wrap = document.getElementById('heatmap-scroll-wrap');
    if (!grid || !cells.length) return;
    grid.innerHTML = '';
    const frag = document.createDocumentFragment();

    const firstWd = cells[0].weekday || 0;
    for (let i = 0; i < firstWd; i++) {
        const emp = document.createElement('span');
        emp.className = 'hm-cell hm-empty';
        frag.appendChild(emp);
    }
    cells.forEach(c => {
        const sp = document.createElement('span');
        sp.className = `hm-cell hm-l${c.level}`;
        sp.title = `${c.date}: ${c.fmt}`;
        frag.appendChild(sp);
    });
    grid.appendChild(frag);
    if (wrap) wrap.scrollLeft = wrap.scrollWidth;
}

function _renderPeerClientsChart(c) {
    const tot = document.getElementById('peer-clients-total');
    if (tot) tot.textContent = `${c.total_peers || 0} пиров`;
    if (typeof Chart === 'undefined') return;
    const ctx = document.getElementById('chart-peer-clients');
    if (!ctx) return;
    if (chartPeerClients) chartPeerClients.destroy();
    const cs = getComputedStyle(document.documentElement);
    const txtColor = cs.getPropertyValue('--text-muted').trim() || '#95a5a6';

    chartPeerClients = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: c.labels?.length ? c.labels : ['Нет пиров'],
            datasets: [{
                data: c.values?.length ? c.values : [1],
                backgroundColor: c.values?.length
                    ? ['#2ecc71', '#3498db', '#e67e22', '#9b59b6', '#e74c3c', '#1abc9c', '#95a5a6']
                    : ['rgba(149,165,166,0.2)'],
                borderWidth: 0
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { position: 'right', labels: { color: txtColor, boxWidth: 12, font: { size: 11 } } } }
        }
    });
}

function _renderTrackersChart(tr) {
    if (typeof Chart === 'undefined') return;
    const ctx = document.getElementById('chart-trackers');
    if (!ctx) return;
    if (chartTrackers) chartTrackers.destroy();
    const cs = getComputedStyle(document.documentElement);
    const tickColor = cs.getPropertyValue('--text-muted').trim() || '#95a5a6';
    const gridColor = cs.getPropertyValue('--border').trim() || 'rgba(255,255,255,0.08)';

    chartTrackers = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: tr.labels || [],
            datasets: [{
                data: tr.values || [],
                backgroundColor: 'rgba(155, 89, 182, 0.72)',
                borderColor: '#9b59b6',
                borderWidth: 1,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false, indexAxis: 'y',
            scales: {
                x: { beginAtZero: true, ticks: { color: tickColor, font: { size: 10 } }, grid: { color: gridColor } },
                y: { ticks: { color: tickColor, font: { size: 10 } }, grid: { color: gridColor } }
            },
            plugins: { legend: { display: false } }
        }
    });
}

function openTorrentInspectorModal() {
    if (typeof selectedHash === 'undefined' || !selectedHash) return alert(t('err_select_torrent'));
    _inspHash = selectedHash;
    const item = (typeof torrentsData !== 'undefined' ? torrentsData : []).find(x => x.hash === _inspHash);
    document.getElementById('insp-title').textContent = item ? item.name : _inspHash;
    document.getElementById('inspector-modal').style.display = 'flex';
    loadInspectorChart('24h');
    loadInspectorPeers();
}

function closeInspectorModal() {
    document.getElementById('inspector-modal').style.display = 'none';
}

async function loadInspectorChart(period = '24h') {
    if (!_inspHash || typeof Chart === 'undefined') return;
    const res = await api(`/api/torrents/chart?hash=${encodeURIComponent(_inspHash)}&period=${encodeURIComponent(period)}`);
    if (!res.ok) return;
    const d = await res.json();
    const pts = d.points || [];
    const ctx = document.getElementById('chart-torrent-personal');
    if (!ctx) return;
    if (chartTorrentPersonal) chartTorrentPersonal.destroy();

    const cs = getComputedStyle(document.documentElement);
    const tickColor = cs.getPropertyValue('--text-muted').trim() || '#95a5a6';
    const gridColor = cs.getPropertyValue('--border').trim() || 'rgba(255,255,255,0.08)';

    chartTorrentPersonal = new Chart(ctx, {
        type: 'line',
        data: {
            labels: pts.map(p => p.label),
            datasets: [{
                data: pts.map(p => p.speed_mbs),
                borderColor: '#2ecc71',
                backgroundColor: 'rgba(46, 204, 113, 0.2)',
                fill: true, tension: 0.3, pointRadius: pts.length <= 40 ? 2.5 : 0
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
                tooltip: {
                    callbacks: {
                        label: ctxItem => `⚡ ${ctxItem.parsed.y} MiB/s (+${pts[ctxItem.dataIndex]?.delta_fmt || '0 B'})`
                    }
                }
            }
        }
    });
}

async function loadInspectorPeers() {
    if (!_inspHash) return;
    const tbody = document.getElementById('insp-peers-tbody');
    tbody.innerHTML = '<tr><td colspan="5" class="center-msg">⏳ Загрузка пиров...</td></tr>';
    const res = await api(`/api/torrents/peers?hash=${encodeURIComponent(_inspHash)}`);
    const d = await res.json();
    if (!res.ok || !d.success) {
        tbody.innerHTML = `<tr><td colspan="5" class="center-msg" style="color:var(--danger);">${escapeHtml(d.error || 'Ошибка')}</td></tr>`;
        return;
    }
    const peers = d.peers || [];
    if (!peers.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="center-msg">Активных пиров сейчас нет</td></tr>';
        return;
    }
    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    peers.forEach(p => {
        const tr = document.createElement('tr');
        const ctry = p.country_code ? `[${escapeHtml(p.country_code)}] ` : '';
        tr.innerHTML = `
            <td>${ctry}<b>${escapeHtml(p.client)}</b></td>
            <td>${p.progress}%</td>
            <td class="accent-txt">${escapeHtml(p.up_speed_fmt)}</td>
            <td class="blue-txt">${escapeHtml(p.dl_speed_fmt)}</td>
            <td class="muted-text">${escapeHtml(p.flags || '—')}</td>
        `;
        frag.appendChild(tr);
    });
    tbody.appendChild(frag);
}