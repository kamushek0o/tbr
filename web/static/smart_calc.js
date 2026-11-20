// web/static/smart_calc.js
let lastForecastData = null;

function populateAnalyticsSelectors() {
    const fill = (selId) => {
        const sel = document.getElementById(selId);
        if (!sel) return;
        const cur = sel.value;
        sel.innerHTML = '';
        const frag = document.createDocumentFragment();
        const def = document.createElement('option');
        def.value = 'all'; def.textContent = t('whole_seedbox');
        frag.appendChild(def);
        rawSummaryItems.forEach(item => {
            const opt = document.createElement('option');
            opt.value = item.hash_id; opt.textContent = `📦 ${item.name}`;
            frag.appendChild(opt);
        });
        sel.appendChild(frag);
        if (cur) sel.value = cur;
    };
    fill('smart-calc-target-type');
    fill('history-torrent-select');
}

function onSmartCalcTargetChange() {
    const val = document.getElementById('smart-calc-target-type').value;
    document.getElementById('smart-calc-goal-label').textContent = val === 'all' ? t('goal_lbl_all') : t('goal_lbl_one');
    document.getElementById('smart-calc-goal').placeholder = val === 'all' ? t('goal_ph_all') : t('goal_ph_one');
}

async function runSmartCalc() {
    const term = document.getElementById('smart-calc-terminal');
    const targetVal = document.getElementById('smart-calc-target-type').value;
    const isAll = (targetVal === 'all');
    const goal = document.getElementById('smart-calc-goal').value.trim();
    const speed = document.getElementById('smart-calc-speed').value.trim();
    if (!goal) { term.textContent = t('err_no_goal'); return; }
    term.textContent = t('calc_running');
    let d;
    try {
        const res = await api('/api/smart_calc', 'POST', { target_type: isAll ? 'all' : 'torrent', hash: isAll ? '' : targetVal, target: goal, speed });
        if (!res.ok) { term.textContent = t('http_err', { status: res.status }); return; }
        d = await res.json();
    } catch (err) { term.textContent = t('net_err', { msg: err.message }); return; }

    const btnTable = document.getElementById('btn-toggle-forecast-table');
    const btnCsv = document.getElementById('btn-export-forecast-csv');
    const wrapTable = document.getElementById('smart-res-table-wrap');
    if (!d.success) {
        btnTable.classList.add('hidden'); btnCsv.classList.add('hidden'); wrapTable.classList.add('hidden');
        term.textContent = d.need_manual ? `=================================================================\n${t('need_manual_msg', { avail: d.days_available, req: d.req_days })}\n=================================================================` : t('err_prefix', { msg: d.error });
        return;
    }

    lastForecastData = d;
    btnCsv.classList.remove('hidden');
    if (d.achieved) { btnTable.classList.add('hidden'); term.textContent = t('goal_achieved', { name: d.name, cur: d.current_up_fmt, tgt: d.target_fmt }); return; }

    btnTable.classList.remove('hidden');
    const modeTxt = d.is_manual ? t('mode_manual') : t('mode_smart', { w: d.weights_desc });
    let out = `=================================================================\n${t('res_header')}\n${t('obj_lbl')}        ${d.name}\n${t('up_now_lbl')} ${d.current_up_fmt}  -->  ${t('goal_lbl')} ${d.target_fmt}\n${t('rem_lbl')}      ${d.remaining_fmt}\n`;
    if (!d.is_seedbox) out += `${t('ratio_lbl', { cur: d.ratio_current, nxt: d.ratio_after_24h })}\n`;
    out += `-----------------------------------------------------------------\n${t('mode_lbl')} ${modeTxt}\n${t('f24_lbl')} +${d.forecast_24h_vol_fmt}\n${t('eta_lbl')}   ${d.eta_str}\n=================================================================`;
    term.textContent = out;

    const tbody = document.getElementById('smart-res-tbody');
    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    (d.forecast_rows || []).forEach(r => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${escapeHtml(r.date)}</td><td><strong>${escapeHtml(r.hour)}</strong></td><td class="purple-txt" style="font-weight:700;">+${escapeHtml(trBackend(r.volume_mb))}</td><td class="blue-txt" style="font-weight:600;">${escapeHtml(r.speed_fmt)}</td><td class="muted-text" style="font-size:11px;">${escapeHtml(r.basis)}</td>`;
        frag.appendChild(tr);
    });
    tbody.appendChild(frag);
}

function toggleForecastTable() {
    const isHidden = document.getElementById('smart-res-table-wrap').classList.toggle('hidden');
    document.getElementById('btn-toggle-forecast-table').textContent = isHidden ? t('btn_hourly_show') : t('btn_hourly_hide');
}

async function exportForecastCSV() {
    if (!lastForecastData) return;
    const res = await api('/api/smart_calc/export', 'POST', { forecast_data: lastForecastData });
    if (!res.ok) return alert(t('export_err'));
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = window.URL.createObjectURL(blob);
    a.download = `forecast_24h_${new Date().toLocaleString('sv-SE').replace(/[- :]/g, '_')}.csv`;
    a.click();
}