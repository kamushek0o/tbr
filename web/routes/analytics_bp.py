# web/routes/analytics_bp.py
import os
import io
import csv
import datetime
import urllib.parse
from flask import Blueprint, request, jsonify, Response, g

from utils.helpers import sanitize_csv_cell, format_file_size, LOG_FOLDER
from core.torrent_parser import get_global_torrent_summaries
from core.summary_tracker import summary_tracker
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


@analytics_bp.route('/api/summary')
def api_summary():
    summaries = get_global_torrent_summaries()
    return jsonify(summary_tracker.get_stats(summaries))


@analytics_bp.route('/api/analytics/history')
def api_analytics_history():
    t_hash = request.args.get('hash', 'all')
    if t_hash != 'all' and not HASH_RE.fullmatch(t_hash):
        return jsonify([])
    limit = min(100, max(1, request.args.get('limit', 36, type=int)))
    return jsonify(summary_tracker.get_torrent_hourly_history(t_hash, limit_hours=limit))


@analytics_bp.route('/api/analytics/charts')
def api_analytics_charts():
    hours = request.args.get('hours', 24, type=int)
    top_n = request.args.get('top_n', 5, type=int)
    summaries = get_global_torrent_summaries()
    return jsonify(summary_tracker.get_charts_data(summaries, hours=hours, top_n=top_n))


@analytics_bp.route('/api/smart_calc', methods=['POST'])
def api_smart_calc():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Неверный формат JSON'}), 400
    target_type = str(data.get('target_type', 'torrent'))
    target_hash = str(data.get('hash', ''))
    target_str = str(data.get('target', ''))[:64]
    speed_str = str(data.get('speed', ''))[:64]

    summaries = get_global_torrent_summaries()
    result = summary_tracker.calculate_smart_forecast(target_type, target_hash, target_str, speed_str, summaries)
    return jsonify(result)


@analytics_bp.route('/api/smart_calc/export', methods=['POST'])
def api_smart_calc_export():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Ожидался JSON объект'}), 400
    forecast_data = data.get('forecast_data')
    if not isinstance(forecast_data, dict):
        return jsonify({'success': False, 'error': 'Отсутствует forecast_data'}), 400
    rows = forecast_data.get('forecast_rows')
    if not isinstance(rows, list) or len(rows) > 100 or not all(isinstance(r, dict) for r in rows):
        return jsonify({'success': False, 'error': 'Некорректные строки прогноза'}), 400

    filepath, filename = summary_tracker.export_forecast_csv(forecast_data)
    if not filepath:
        return jsonify({'success': False, 'error': 'Ошибка создания файла'}), 500

    with open(filepath, 'rb') as f:
        file_bytes = f.read()

    return Response(
        file_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(filename)}"}
    )


@analytics_bp.route('/api/export_csv', methods=['GET', 'POST'])
def api_export_csv():
    if request.method == 'POST':
        req_data = request.get_json(silent=True)
        if not isinstance(req_data, dict):
            return jsonify({'error': 'Некорректный JSON'}), 400
        items = req_data.get('items')
        if not isinstance(items, list) or len(items) > 5000 or not all(isinstance(x, dict) for x in items):
            return jsonify({'error': 'Некорректный список или превышен лимит 5000 строк'}), 400
    else:
        summaries = get_global_torrent_summaries()
        items = summary_tracker.get_stats(summaries)['items']

    summary_tracker.save_manual_csv(items)

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        'Имя', 'Хэш', 'Размер (байт)', 'Размер (ГБ)', 'Отдано (байт)', 'Отдано (ГБ)',
        'Ratio', 'Ср. скорость (всё время)', 'Скорость за 1ч', 'Скорость за 24ч',
        'МБ/ч', 'МБ/день', 'Ratio/ч (всего)', 'Ratio/ч (1ч)', 'Ratio/ч (24ч)', 'Дата создания'
    ])
    for s in items:
        sz = int(s.get('size', 0)) if isinstance(s.get('size'), (int, float)) else 0
        up = int(s.get('uploaded', 0)) if isinstance(s.get('uploaded'), (int, float)) else 0
        rt = float(s.get('ratio', 0.0)) if isinstance(s.get('ratio'), (int, float)) else 0.0
        writer.writerow([
            sanitize_csv_cell(s.get('name', '')),
            sanitize_csv_cell(s.get('hash_id', '')),
            sz, f"{sz / (1024 ** 3):.2f}",
            up, f"{up / (1024 ** 3):.2f}",
            f"{rt:.2f}",
            sanitize_csv_cell(s.get('speed_all_time_fmt', '0 B/s')),
            sanitize_csv_cell(s.get('speed_1h_fmt', '0 B/s')),
            sanitize_csv_cell(s.get('speed_24h_fmt', '0 B/s')),
            sanitize_csv_cell(s.get('vol_hour_fmt', '0.00 МБ/ч')),
            sanitize_csv_cell(s.get('vol_day_fmt', '0.00 МБ/день')),
            sanitize_csv_cell(s.get('ratio_h_all_fmt', '0.000 /ч')),
            sanitize_csv_cell(s.get('ratio_h_hour_fmt', '0.000 /ч')),
            sanitize_csv_cell(s.get('ratio_h_day_fmt', '0.000 /ч')),
            sanitize_csv_cell(s.get('created', ''))
        ])
    filename = f"summary_manual_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@analytics_bp.route('/api/logs/can_open_folder')
def api_logs_can_open_folder():
    if g.get('role') != 'admin':
        return jsonify({'can_open': False}), 403
    return jsonify({'can_open': _is_strict_localhost() and os.name == 'nt'})


@analytics_bp.route('/api/logs/open_folder', methods=['POST'])
def api_logs_open_folder():
    if g.get('role') != 'admin' or not _is_strict_localhost() or os.name != 'nt':
        return jsonify({'success': False, 'error': 'Доступно только локально с localhost (не в Docker)'}), 403
    try:
        os.startfile(LOG_FOLDER)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@analytics_bp.route('/api/logs/day')
def api_logs_by_day():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    date_str, start_ts, end_ts = _parse_day_bounds(request.args.get('date', ''))
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)
    res = summary_tracker.db.get_snapshots_by_day_paginated(start_ts, end_ts, page=page, per_page=per_page)
    for it in res['items']:
        it['uploaded_fmt'] = format_file_size(it.get('total_uploaded', 0))
        it['size_fmt'] = format_file_size(it.get('total_size', 0))
    res['date'] = date_str
    return jsonify(res)


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
        writer.writerow([
            sanitize_csv_cell(r.get('datetime', '')),
            r.get('total_uploaded', 0),
            sanitize_csv_cell(format_file_size(r.get('total_uploaded', 0))),
            r.get('total_size', 0),
            r.get('count', 0)
        ])
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=snapshots_{date_str}.csv"}
    )