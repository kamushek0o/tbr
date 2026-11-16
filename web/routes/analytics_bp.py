# web/routes/analytics_bp.py
import os
import io
import csv
import datetime
import urllib.parse
from flask import Blueprint, request, jsonify, Response

from utils.helpers import sanitize_csv_cell, LOG_FOLDER
from core.torrent_parser import get_global_torrent_summaries
from core.summary_tracker import summary_tracker, AUTO_FOLDER, MANUAL_FOLDER
from web.security import HASH_RE, resolve_log_path

analytics_bp = Blueprint('analytics_bp', __name__)


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
    summaries = get_global_torrent_summaries()
    return jsonify(summary_tracker.get_charts_data(summaries))


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


@analytics_bp.route('/api/logs/list')
def api_logs_list():
    entries = []
    for folder, prefix, exts in [
        (LOG_FOLDER, '', ('.log', '.txt')),
        (AUTO_FOLDER, 'auto_hourly/', ('.csv',)),
        (MANUAL_FOLDER, 'manual_exports/', ('.csv',))
    ]:
        if os.path.exists(folder):
            for f in os.listdir(folder):
                if f.lower().endswith(exts):
                    full = os.path.join(folder, f)
                    try:
                        entries.append((os.path.getmtime(full), f"{prefix}{f}"))
                    except OSError:
                        pass
    entries.sort(key=lambda x: x[0], reverse=True)
    return jsonify([name for _, name in entries[:20]])


@analytics_bp.route('/api/logs/view')
def api_logs_view():
    filename = request.args.get('name', '')
    path = resolve_log_path(filename)
    if not path:
        return jsonify({'error': 'Файл не найден'}), 404
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            return jsonify({'content': "".join(lines[-300:])})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@analytics_bp.route('/api/logs/download')
def api_logs_download():
    filename = request.args.get('name', '')
    path = resolve_log_path(filename)
    if not path:
        return "Файл не найден на сервере", 404
    try:
        with open(path, 'rb') as f:
            data = f.read()
        base_name = os.path.basename(path)
        mime = "text/csv" if base_name.endswith('.csv') else "text/plain"
        return Response(
            data, mimetype=mime,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(base_name)}"}
        )
    except Exception as e:
        return f"Ошибка скачивания: {e}", 500