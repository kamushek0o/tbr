# core/forecaster.py
import os
import time
import csv
import datetime
from utils.config import cfg
from utils.helpers import format_file_size, parse_bytes, parse_speed, sanitize_csv_cell, write_error_log


def fmt_ratio_h(val):
    if val is None or val <= 0:
        return "0.000 /ч"
    if val < 0.001:
        return f"{val:.4f} /ч"
    if val < 1.0:
        return f"{val:.3f} /ч"
    return f"{val:.2f} /ч"


def fmt_speed(bps):
    if bps is None or bps <= 0:
        return "0 B/s"
    return f"{format_file_size(bps)}/s"


def calculate_smart_forecast(db, target_type, target_hash, target_str, speed_str, summaries):
    try:
        is_seedbox = (target_type == 'all' or not target_hash)
        t_hash_lower = (target_hash or '').lower()

        if is_seedbox:
            current_up = sum(s.get('uploaded', 0) for s in summaries)
            total_sz = sum(s.get('size', 0) for s in summaries)
            name = "🌐 Весь сидбокс (суммарно)"
            target_bytes = parse_bytes(target_str, torrent_size=total_sz)
        else:
            t_item = next(
                (s for s in summaries if (str(s.get('hash_id', '')).lower() == t_hash_lower or
                                         str(s.get('hash', '')).lower() == t_hash_lower)),
                None
            )
            if not t_item:
                return {'success': False, 'error': "Выбранная раздача не найдена!"}
            current_up = t_item.get('uploaded', 0)
            total_sz = t_item.get('size', 0)
            name = t_item.get('name', target_hash)
            target_bytes = parse_bytes(target_str, torrent_size=total_sz)

        remaining_bytes = max(0, target_bytes - current_up)
        if remaining_bytes == 0:
            return {
                'success': True, 'achieved': True, 'name': name,
                'current_up_fmt': format_file_size(current_up),
                'target_fmt': format_file_size(target_bytes),
                'message': "Цель уже достигнута!"
            }

        is_manual = bool(speed_str and speed_str.strip().lower() not in ('авто', 'auto', ''))
        manual_speed = 0
        if is_manual:
            manual_speed = parse_speed(speed_str)
            if manual_speed <= 0:
                return {'success': False, 'error': "Скорость должна быть больше 0!"}

        raw_w1 = max(0, cfg.getint('Weight_W1', 70))
        raw_w2 = max(0, cfg.getint('Weight_W2', 30))
        raw_w3 = max(0, cfg.getint('Weight_W3', 0))
        total_w = raw_w1 + raw_w2 + raw_w3

        if not is_manual and total_w <= 0:
            return {'success': False, 'error': "Все веса расчёта равны 0! Задайте их в ⚙️ Настройки."}

        nw1 = raw_w1 / total_w if total_w > 0 else 0.0
        nw2 = raw_w2 / total_w if total_w > 0 else 0.0
        nw3 = raw_w3 / total_w if total_w > 0 else 0.0

        req_days = 21 if raw_w3 > 0 else (14 if raw_w2 > 0 else 7)
        now_ts = time.time()

        cnt, min_ts = db.get_snapshot_range_info()
        days_available = (now_ts - min_ts) / 86400.0 if (cnt and min_ts) else 0.0

        if not is_manual and (cnt < 2 or days_available < (req_days - 0.15)):
            return {
                'success': False, 'need_manual': True,
                'days_available': round(days_available, 1),
                'req_days': req_days,
                'error': f"Недостаточно данных (накоплено {days_available:.1f} из {req_days} дн.). Укажите скорость вручную."
            }

        forecast_24h_rows = []
        projected_24h_volume = 0

        for i in range(24):
            h_start = now_ts + (i * 3600)
            h_end = h_start + 3600
            s_dt = datetime.datetime.fromtimestamp(h_start)
            e_dt = datetime.datetime.fromtimestamp(h_end)

            if is_manual:
                vol_hour = int(manual_speed * 3600)
                speed_hour = manual_speed
                basis_text = "Ручной ввод скорости"
            else:
                d1 = db.get_hist_delta(h_start - (168 * 3600), h_end - (168 * 3600), is_seedbox, t_hash_lower) if nw1 > 0 else 0
                d2 = db.get_hist_delta(h_start - (336 * 3600), h_end - (336 * 3600), is_seedbox, t_hash_lower) if nw2 > 0 else 0
                d3 = db.get_hist_delta(h_start - (504 * 3600), h_end - (504 * 3600), is_seedbox, t_hash_lower) if nw3 > 0 else 0
                vol_hour = int((nw1 * d1) + (nw2 * d2) + (nw3 * d3))
                speed_hour = vol_hour / 3600.0
                parts = []
                if nw1 > 0: parts.append(f"1нед: {d1/(1024**2):.1f}МБ ({nw1*100:.0f}%)")
                if nw2 > 0: parts.append(f"2нед: {d2/(1024**2):.1f}МБ ({nw2*100:.0f}%)")
                if nw3 > 0: parts.append(f"3нед: {d3/(1024**2):.1f}МБ ({nw3*100:.0f}%)")
                basis_text = " + ".join(parts)

            projected_24h_volume += vol_hour
            forecast_24h_rows.append({
                'date': s_dt.strftime('%d.%m'),
                'hour': f"{s_dt.strftime('%H:00')} – {e_dt.strftime('%H:00')}",
                'volume_bytes': vol_hour,
                'volume_mb': f"{vol_hour / (1024 * 1024):.2f} МБ",
                'speed_fmt': fmt_speed(speed_hour),
                'basis': basis_text
            })

        max_seconds = 3650 * 86400
        eta_dt = None
        eta_str = ""

        if is_manual:
            seconds_needed = int(remaining_bytes / manual_speed) if manual_speed > 0 else max_seconds + 1
            if seconds_needed <= max_seconds:
                eta_dt = datetime.datetime.fromtimestamp(now_ts + seconds_needed)
            else:
                eta_str = f"Более 10 лет (~{seconds_needed // (365*86400)} лет)"
        else:
            simulated_ts = now_ts
            simulated_rem = remaining_bytes
            idx = 0
            while simulated_rem > 0 and (simulated_ts - now_ts) < (365 * 86400):
                hour_vol = forecast_24h_rows[idx % 24]['volume_bytes']
                if hour_vol <= 0:
                    hour_vol = max(1, int(projected_24h_volume / 24)) if projected_24h_volume > 0 else 1024
                if simulated_rem <= hour_vol:
                    simulated_ts += int((simulated_rem / hour_vol) * 3600)
                    simulated_rem = 0
                    break
                simulated_rem -= hour_vol
                simulated_ts += 3600
                idx += 1
            if simulated_rem == 0:
                eta_dt = datetime.datetime.fromtimestamp(simulated_ts)
            else:
                eta_str = "Более 1 года при текущем темпе"

        if eta_dt:
            eta_str = eta_dt.strftime('%A, %d.%m.%Y в %H:%M')
            ru_days = {'Monday': 'Понедельник', 'Tuesday': 'Вторник', 'Wednesday': 'Среда',
                       'Thursday': 'Четверг', 'Friday': 'Пятница', 'Saturday': 'Суббота', 'Sunday': 'Воскресенье'}
            for eng, ru in ru_days.items():
                eta_str = eta_str.replace(eng, ru)

        weights_desc = f"{nw1*100:.0f}% / {nw2*100:.0f}% / {nw3*100:.0f}% ({req_days} дн.)"

        return {
            'success': True, 'achieved': False, 'name': name,
            'target_type': target_type, 'is_seedbox': is_seedbox, 'is_manual': is_manual,
            'weights_desc': weights_desc,
            'current_up_fmt': format_file_size(current_up),
            'target_fmt': format_file_size(target_bytes),
            'remaining_fmt': format_file_size(remaining_bytes),
            'forecast_24h_vol_fmt': format_file_size(projected_24h_volume),
            'ratio_current': round(current_up / total_sz, 2) if total_sz > 0 else 0.0,
            'ratio_after_24h': round((current_up + projected_24h_volume) / total_sz, 2) if total_sz > 0 else 0.0,
            'eta_str': eta_str,
            'forecast_rows': forecast_24h_rows
        }
    except Exception as e:
        write_error_log("SmartCalc Error", e)
        return {'success': False, 'error': str(e)}


def export_forecast_csv(manual_folder, forecast_data):
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    raw_name = str(forecast_data.get('name', 'forecast'))
    clean_name = "".join(c for c in raw_name if c.isalnum() or c in (' ', '_', '-')).strip()[:30] or 'forecast'
    filename = f"forecast_24h_{clean_name}_{ts}.csv"
    filepath = os.path.join(manual_folder, filename)

    lines = [
        f"# === ПОЧАСОВОЙ ПРОГНОЗ ОТДАЧИ НА 24 ЧАСА ===",
        f"# Объект: {sanitize_csv_cell(forecast_data.get('name', ''))}",
        f"# Дата расчета: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"# Цель: {forecast_data.get('target_fmt', '')} | Осталось: {forecast_data.get('remaining_fmt', '')}",
        f"# Ожидаемая отдача за следующие 24ч: {forecast_data.get('forecast_24h_vol_fmt', '')}",
        f"# Ожидаемое время достижения цели: {forecast_data.get('eta_str', '')}",
        f"# =========================================="
    ]

    try:
        with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
            f.write('\n'.join(lines) + '\n')
            w = csv.writer(f, delimiter=';')
            w.writerow(['Дата', 'Интервал (час)', 'Ожидаемый объём (МБ)', 'Ожидаемая скорость', 'Обоснование расчёта'])
            for r in forecast_data.get('forecast_rows', [])[:100]:
                w.writerow([
                    sanitize_csv_cell(r.get('date', '')),
                    sanitize_csv_cell(r.get('hour', '')),
                    sanitize_csv_cell(r.get('volume_mb', '')),
                    sanitize_csv_cell(r.get('speed_fmt', '')),
                    sanitize_csv_cell(r.get('basis', ''))
                ])
        return filepath, filename
    except Exception as e:
        write_error_log("Ошибка экспорта прогноза в CSV", e)
        return None, None