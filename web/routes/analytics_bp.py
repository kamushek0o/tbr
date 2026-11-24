# web/routes/analytics_bp.py
import os
import io
import csv
import time
import datetime
import urllib.parse
from flask import Blueprint, request, jsonify, Response, g

from utils.config import cfg
from utils.helpers import sanitize_csv_cell, format_file_size, LOG_FOLDER
from core.torrent_parser import get_global_torrent_summaries, get_live_merged_summaries
from core.summary_tracker import summary_tracker
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info
from core.private_vault import get_hidden_hashes, filter_summary_stats_for_role
from core.torrent_targets import list_targets
from core.health_score import enrich_live_metrics
from core.scheduler import MIN_DELTA_SEC
from core.widget_service import build_detailed_speed_series, build_hourly_aggregated_speed_series, compute_top_n_torrents
from core.analytics_insights import invalidate_insights_cache, get_heatmap_365, get_records_and_comparisons
from web.security import HASH_RE

analytics_bp = Blueprint('analytics_bp', __name__)


def _parse_day_bounds(date_str):
    try:
        d = datetime.datetime.strptime(str(date_str).strip(), '%Y-%m-%d')
    except ValueError:
        d = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_ts = d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    end_ts = d.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp()
    return d.strftime('%Y-%m-%d'), start_ts, end_ts


def _is_strict_localhost():
    if os.path.exists('/.dockerenv') or bool(os.environ.get('TBR_DATA_DIR', '').strip()):
        return False
    if request.headers.get('X-Forwarded-For') or request.headers.get('X-Real-IP'):
        return False
    return (request.remote_addr or '').strip() in ('127.0.0.1', '::1')


def _get_live_dict():
    ip, port = detect_qbittorrent_port(cfg.config)
    return get_live_torrent_info(ip, port) if port else {}


@analytics_bp.route('/api/summary')
def api_summary():
    summaries = get_live_merged_summaries()
    stats = summary_tracker.get_stats(summaries)
    live = _get_live_dict()
    targets = list_targets()
    live_lower = {k.lower(): v for k, v in live.items()}

    for it in stats.get('items', []):
        hl = (it.get('hash_id') or it.get('hash') or '').lower()
        enrich_live_metrics(it, live_lower.get(hl), targets.get(hl))

    role = g.get('role') or 'viewer'
    if role != 'admin':
        stats = filter_summary_stats_for_role(stats, role, get_hidden_hashes(live))
    return jsonify(stats)


@analytics_bp.route('/api/analytics/history')
def api_analytics_history():
    t_hash = request.args.get('hash', 'all')
    if t_hash != 'all' and not HASH_RE.fullmatch(t_hash):
        return jsonify([])
    if t_hash != 'all' and g.get('role') != 'admin':
        if t_hash.lower() in get_hidden_hashes(_get_live_dict()):
            return jsonify([])
    limit = min(100, max(1, request.args.get('limit', 36, type=int)))
    return jsonify(summary_tracker.get_torrent_hourly_history(t_hash, limit_hours=limit))


@analytics_bp.route('/api/analytics/charts')
def api_analytics_charts():
    chart = request.args.get('chart', 'all')
    hours = request.args.get('hours', 24, type=int)
    top_n = max(1, min(25, request.args.get('top_n', 5, type=int)))
    top_period = request.args.get('top_period', '1d')
    win_hours = hours if hours in (6, 12, 24, 72, 168) else 24

    if chart == 'hourly':
        series = build_detailed_speed_series(summary_tracker.db, hours=win_hours) if win_hours <= 24 else build_hourly_aggregated_speed_series(summary_tracker.db, hours=win_hours)
        return jsonify({'hourly': {'hours': win_hours, 'labels': [p['label'] for p in series], 'values': [p['speed_mbs'] for p in series], 'meta': series}})

    if chart == 'daily':
        rows = summary_tracker.db.get_snapshots_since(time.time() - (14 * 86400))
        daily_map, prev_row = {}, None
        for r in rows:
            if prev_row is not None:
                t1, t2 = prev_row['timestamp'], r['timestamp']
                dt_sec, delta = t2 - t1, max(0, r['total_uploaded'] - prev_row['total_uploaded'])
                if dt_sec >= MIN_DELTA_SEC and delta > 0:
                    cur_ts = datetime.datetime.fromtimestamp(t1).replace(minute=0, second=0, microsecond=0).timestamp()
                    while cur_ts < t2:
                        b_end = cur_ts + 3600.0
                        overlap = min(t2, b_end) - max(t1, cur_ts)
                        if overlap > 0:
                            dk = datetime.datetime.fromtimestamp(cur_ts).strftime('%Y-%m-%d')
                            daily_map[dk] = daily_map.get(dk, 0.0) + delta * (overlap / dt_sec)
                        cur_ts = b_end
            prev_row = r
        s_days = sorted(daily_map.keys())[-14:]
        return jsonify({'daily': {'labels': [f"{d[8:10]}.{d[5:7]}" for d in s_days], 'values': [round(daily_map[d] / (1024 ** 3), 3) for d in s_days]}})

    summaries = get_global_torrent_summaries()
    live = _get_live_dict()
    if g.get('role') != 'admin':
        hidden = get_hidden_hashes(live)
        if hidden:
            summaries = [s for s in summaries if (s.get('hash_id') or s.get('hash') or '').lower() not in hidden]

    if chart == 'top5':
        per = top_period if top_period in ('1d', '7d', '30d', 'all') else '1d'
        top_items, others = compute_top_n_torrents(summary_tracker.db, summaries, live=live, top_n=top_n, period=per, with_others=True)
        return jsonify({'top5': {'n': top_n, 'period': per, 'labels': [x['short_name'] for x in top_items], 'full_labels': [x['full_name'] for x in top_items], 'values': [x['gb'] for x in top_items], 'others': others}})

    return jsonify(summary_tracker.get_charts_data(summaries, hours=hours, top_n=top_n, top_period=top_period))


@analytics_bp.route('/api/smart_calc', methods=['POST'])
def api_smart_calc():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Неверный формат JSON'}), 400
    return jsonify(summary_tracker.calculate_smart_forecast(
        str(data.get('target_type', 'torrent')), str(data.get('hash', '')),
        str(data.get('target', ''))[:64], str(data.get('speed', ''))[:64], get_live_merged_summaries()
    ))


@analytics_bp.route('/api/smart_calc/export', methods=['POST'])
def api_smart_calc_export():
    data = request.get_json(silent=True) or {}
    forecast_data = data.get('forecast_data')
    rows = forecast_data.get('forecast_rows') if isinstance(forecast_data, dict) else None
    if not isinstance(rows, list) or len(rows) > 100 or not all(isinstance(r, dict) for r in rows):
        return jsonify({'success': False, 'error': 'Некорректные строки прогноза'}), 400
    filepath, filename = summary_tracker.export_forecast_csv(forecast_data)
    if not filepath:
        return jsonify({'success': False, 'error': 'Ошибка создания файла'}), 500
    with open(filepath, 'rb') as f:
        file_bytes = f.read()
    return Response(file_bytes, mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(filename)}"})


@analytics_bp.route('/api/export_csv', methods=['GET', 'POST'])
def api_export_csv():
    role = g.get('role') or 'viewer'
    if request.method == 'POST':
        req_data = request.get_json(silent=True)
        items = req_data.get('items') if isinstance(req_data, dict) else None
        if not isinstance(items, list) or len(items) > 5000 or not all(isinstance(x, dict) for x in items):
            return jsonify({'error': 'Некорректный список или превышен лимит 5000 строк'}), 400
        summary_tracker.save_manual_csv(items)
    else:
        stats = summary_tracker.get_stats(get_live_merged_summaries())
        if role != 'admin':
            stats = filter_summary_stats_for_role(stats, role, get_hidden_hashes(_get_live_dict()))
        items = stats.get('items', [])

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Имя', 'Хэш', 'Размер (байт)', 'Размер (ГБ)', 'Отдано (байт)', 'Отдано (ГБ)', 'Ratio', 'Ср. скорость (всё время)', 'Скорость за 1ч', 'Скорость за 24ч', 'МБ/ч', 'МБ/день', 'Ratio/ч (всего)', 'Ratio/ч (1ч)', 'Ratio/ч (24ч)', 'Дата создания'])
    for s in items:
        sz = int(s.get('size', 0)) if isinstance(s.get('size'), (int, float)) else 0
        up = int(s.get('uploaded', 0)) if isinstance(s.get('uploaded'), (int, float)) else 0
        rt = float(s.get('ratio', 0.0)) if isinstance(s.get('ratio'), (int, float)) else 0.0
        writer.writerow([
            sanitize_csv_cell(s.get('name', '')), sanitize_csv_cell(s.get('hash_id', '')),
            sz, f"{sz / (1024 ** 3):.2f}", up, f"{up / (1024 ** 3):.2f}", f"{rt:.2f}",
            sanitize_csv_cell(s.get('speed_all_time_fmt', '0 B/s')), sanitize_csv_cell(s.get('speed_1h_fmt', '0 B/s')),
            sanitize_csv_cell(s.get('speed_24h_fmt', '0 B/s')), sanitize_csv_cell(s.get('vol_hour_fmt', '0.00 МБ/ч')),
            sanitize_csv_cell(s.get('vol_day_fmt', '0.00 МБ/день')), sanitize_csv_cell(s.get('ratio_h_all_fmt', '0.000 /ч')),
            sanitize_csv_cell(s.get('ratio_h_hour_fmt', '0.000 /ч')), sanitize_csv_cell(s.get('ratio_h_day_fmt', '0.000 /ч')),
            sanitize_csv_cell(s.get('created', ''))
        ])
    filename = f"summary_manual_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(output.getvalue().encode('utf-8-sig'), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})


@analytics_bp.route('/api/logs/can_open_folder')
def api_logs_can_open_folder():
    if g.get('role') != 'admin':
        return jsonify({'can_open': False}), 403
    return jsonify({'can_open': _is_strict_localhost() and os.name == 'nt'})


@analytics_bp.route('/api/logs/open_folder', methods=['POST'])
def api_logs_open_folder():
    if g.get('role') != 'admin' or not _is_strict_localhost() or os.name != 'nt':
        return jsonify({'success': False, 'error': 'Доступно только локально с localhost'}), 403
    try:
        os.startfile(LOG_FOLDER)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@analytics_bp.route('/api/logs/days')
def api_logs_days():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    return jsonify({'days': summary_tracker.db.get_available_snapshot_days(limit=90)})


@analytics_bp.route('/api/logs/day')
def api_logs_by_day():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    date_str, start_ts, end_ts = _parse_day_bounds(request.args.get('date', ''))
    res = summary_tracker.db.get_snapshots_by_day_paginated(start_ts, end_ts, page=request.args.get('page', 1, type=int), per_page=request.args.get('per_page', 15, type=int))
    for it in res['items']:
        it['uploaded_fmt'] = format_file_size(it.get('total_uploaded', 0))
        it['size_fmt'] = format_file_size(it.get('total_size', 0))
    res['date'] = date_str
    return jsonify(res)


@analytics_bp.route('/api/logs/snapshot/ignore', methods=['POST'])
def api_logs_snapshot_ignore():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    data = request.get_json(silent=True) or {}
    snap_id = data.get('id')
    if not snap_id:
        return jsonify({'success': False, 'error': 'Не указан id снимка'}), 400
    ignored = bool(data.get('ignored', True))
    ok = summary_tracker.db.set_snapshot_ignored(int(snap_id), ignored=ignored)
    if not ok:
        return jsonify({'success': False, 'error': 'Снимок не найден'}), 404
    invalidate_insights_cache()
    hm = get_heatmap_365(summary_tracker.db)
    records = get_records_and_comparisons(summary_tracker.db, heatmap_cells=hm, force_recalc=True)
    return jsonify({'success': True, 'records': records})


@analytics_bp.route('/api/logs/day/download')
def api_logs_by_day_download():
    if g.get('role') != 'admin':
        return "Только для Admin", 403
    date_str, start_ts, end_ts = _parse_day_bounds(request.args.get('date', ''))
    rows = summary_tracker.db.get_snapshots_by_day_all(start_ts, end_ts)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Время снимка', 'Всего отдано (байт)', 'Всего отдано', 'Общий размер (байт)', 'Раздач'])
    for r in rows:
        writer.writerow([sanitize_csv_cell(r.get('datetime', '')), r.get('total_uploaded', 0), sanitize_csv_cell(format_file_size(r.get('total_uploaded', 0))), r.get('total_size', 0), r.get('count', 0)])
    return Response(output.getvalue().encode('utf-8-sig'), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=snapshots_{date_str}.csv"})