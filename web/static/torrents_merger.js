// web/static/torrents_merger.js
async function scanDeadTorrents() {
    const modal = document.getElementById('dead-torrents-modal');
    const tbody = document.getElementById('dead-torrents-tbody');
    const badges = document.getElementById('dead-summary-badges');
    const pauseAllBtn = document.getElementById('btn-pause-all-dead');
    modal.style.display = 'flex';
    badges.innerHTML = `<span class="badge badge-pause">${t('dead_scanning_badge')}</span>`;
    tbody.innerHTML = `<tr><td colspan="4" class="center-msg">${t('scanning')}</td></tr>`;
    pauseAllBtn.classList.add('hidden');
    lastDeadHashes = [];
    try {
        const res = await api('/api/torrents/scan_dead', 'POST');
        const d = await res.json();
        if (!res.ok || !d.success) { badges.innerHTML = ''; tbody.innerHTML = `<tr><td colspan="4" class="center-msg" style="color:var(--danger);">${escapeHtml(d.error || 'Error')}</td></tr>`; return; }
        badges.innerHTML = `<span class="badge badge-dl">${t('dead_scanned', { n: d.total_scanned })}</span><span class="badge ${d.dead_count > 0 ? 'badge-err' : 'badge-up'}">${t('dead_found', { n: d.dead_count })}</span>`;
        (d.groups || []).forEach(g => { const sp = document.createElement('span'); sp.className = 'badge badge-stall'; sp.textContent = `${g.error_msg}: ${g.count}`; badges.appendChild(sp); });
        if (!d.items || !d.items.length) { tbody.innerHTML = `<tr><td colspan="4" class="center-msg" style="color:var(--accent);">${t('dead_none')}</td></tr>`; return; }
        lastDeadHashes = d.items.map(i => i.hash);
        pauseAllBtn.classList.remove('hidden');
        tbody.innerHTML = '';
        const frag = document.createDocumentFragment();
        d.items.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `<td style="max-width:260px; overflow:hidden; text-overflow:ellipsis;" title="${escapeHtml(item.name)}"><strong>${escapeHtml(item.name)}</strong></td><td>${escapeHtml(item.size_fmt)}</td><td><span class="badge badge-err">${escapeHtml(item.error_msg)}</span></td><td><button class="btn btn-secondary btn-xs" onclick="pauseSingleDead('${escapeHtml(item.hash)}', this)">${t('btn_pause')}</button></td>`;
            frag.appendChild(tr);
        });
        tbody.appendChild(frag);
    } catch (e) { badges.innerHTML = ''; tbody.innerHTML = `<tr><td colspan="4" class="center-msg" style="color:var(--danger);">${escapeHtml(e.message)}</td></tr>`; }
}

async function pauseSingleDead(hash, btn) {
    const res = await api('/api/torrents/action', 'POST', { hash, action: 'stop' });
    const d = await res.json();
    if (d.success) { btn.textContent = t('dead_paused'); btn.disabled = true; loadTorrents(); } else alert(d.error || 'Error');
}

async function pauseAllDeadTorrents() {
    if (!lastDeadHashes.length || !confirm(t('dead_pause_confirm', { n: lastDeadHashes.length }))) return;
    const res = await api('/api/torrents/action', 'POST', { hash: lastDeadHashes.join('|'), action: 'stop' });
    const d = await res.json();
    if (d.success) { alert(t('dead_paused_msg', { n: lastDeadHashes.length })); closeDeadModal(); loadTorrents(); } else alert(d.error || 'Error');
}

function closeDeadModal() { document.getElementById('dead-torrents-modal').style.display = 'none'; }

function loadMergerLists() {
    const o = document.getElementById('merger-old'), n = document.getElementById('merger-new');
    if (!torrentsData.length) { loadTorrents().then(() => loadMergerLists()); return; }
    o.innerHTML = ''; n.innerHTML = '';
    torrentsData.forEach(item => {
        const opt1 = document.createElement('option');
        opt1.value = item.hash; opt1.textContent = `${item.name} [${item.hash.substring(0, 8)}]`;
        o.appendChild(opt1); n.appendChild(opt1.cloneNode(true));
    });
    if (torrentsData.length > 1) n.selectedIndex = 1;
    if (typeof onMergerSelectionChange === 'function') onMergerSelectionChange();
    if (typeof loadSmartMatchCandidates === 'function') loadSmartMatchCandidates();
}

function onMergerDeleteModeChange() {
    document.getElementById('merger-force-warn').classList.toggle('hidden', document.getElementById('merger-delete-mode').value !== 'force');
}

async function runMerger(forceDup = false) {
    const logBox = document.getElementById('merger-log');
    const old_hash = document.getElementById('merger-old').value;
    const new_hash = document.getElementById('merger-new').value;
    const delete_mode = document.getElementById('merger-delete-mode').value || 'none';
    const merge_mode = document.getElementById('merger-mode')?.value || 'add';

    if (!old_hash || !new_hash) return alert(t('err_select_both'));
    if (old_hash.toLowerCase() === new_hash.toLowerCase()) return alert(t('err_same_torrent'));

    logBox.textContent = t('merger_running');
    const res = await api('/api/merger/run', 'POST', {
        old_hash, new_hash, delete_mode, merge_mode, force_duplicate: forceDup
    });
    const d = await res.json();

    if (res.status === 409 && d.needs_duplicate_confirm) {
        if (confirm(d.warning || 'Эти раздачи уже объединялись! Сложить ещё раз?')) {
            return runMerger(true);
        }
        logBox.textContent = '❌ Операция отменена пользователем (защита от повторного сложения).';
        return;
    }

    logBox.textContent = (d.log || []).join('\n');
    if (d.success && d.needs_delete_confirm && d.confirm_info) {
        const ci = d.confirm_info;
        const srcTor = torrentsData.find(x => x.hash.toLowerCase() === old_hash.toLowerCase());
        if (srcTor && srcTor.is_last_seed && !confirm('🛡️ ПРЕДУПРЕЖДЕНИЕ: Вы единственный раздающий этот файл в сети! Точно удалить исходник?')) {
            logBox.textContent += '\n' + t('del_cancelled');
            return;
        }
        const msg = ci.method === 'disk_only' ? t('confirm_del_disk_only', { name: ci.old_name })
            : (ci.delete_files ? t('confirm_del_with_files', { name: ci.old_name })
                : (ci.downgraded ? t('confirm_del_downgraded', { name: ci.old_name }) : t('confirm_del_torrent_only', { name: ci.old_name })));
        if (confirm(msg)) {
            const delRes = await api('/api/merger/delete_source', 'POST', { old_hash, new_hash, delete_mode, confirmed: true });
            const delData = await delRes.json();
            logBox.textContent += '\n' + (delData.log || []).join('\n');
            loadTorrents(true);
        } else logBox.textContent += '\n' + t('del_cancelled');
    }
}