# core/summary_tracker.py
import os
import time
import csv
import datetime
from utils.helpers import LOG_FOLDER, format_file_size, sanitize_csv_cell, write_error_log
from core.history_db import HistoryDB, AUTO_FOLDER, MANUAL_FOLDER
from core.forecaster import fmt_ratio_h, fmt_speed, calculate_smart_forecast, export_forecast_csv
from core.scheduler import SnapshotScheduler, MIN_DELTA_SEC
from core.widget_service import build_detailed_speed_series


class SummaryTracker:
    def __init__(self, log_folder=LOG_FOLDER):
        self.log_folder = log_folder
        self.auto_folder = AUTO_FOLDER
        self.manual_folder = MANUAL_FOLDER
        self.db = HistoryDB(auto_folder=self.auto_folder)
        self._get_summaries_fn = None
        self.scheduler = SnapshotScheduler(
            db=self.db,
            on_record_fn=self.record_snapshot
        )

    def record_snapshot(self, summaries, min_delta_sec=MIN_DELTA_SEC):
        return self.db.record_snapshot(summaries, min_delta_sec=min_delta_sec)

    def notify_interval_changed(self):
        self.scheduler.notify_interval_changed()

    def flush_on_exit(self):
        if self._get_summaries_fn:
            self.scheduler.flush_on_exit(self._get_summaries_fn)

    def get_stats(self, summaries):
        now_ts = time.time()
        total_uploaded = sum(s.get('uploaded', 0) for s in summaries)
        total_size = sum(s.get('size', 0) for s in summaries)

        latest_snap, prev_snap, snap_1h, snap_1h_torrents, snap_24h, snap_24h_torrents = self.db.get_stats_snapshots(now_ts)
        dt_1h = max(1, now_ts - snap_1h['timestamp']) if snap_1h else 3600
        dt_24h = max(1, now_ts - snap_24h['timestamp']) if snap_24h else 86400

        global_hour_volume = 0
        global_hour_note = "ожидание замера"
        if latest_snap:
            elapsed_sec = now_ts - latest_snap.get('timestamp', now_ts)
            if 300 <= elapsed_sec <= 7200:
                delta_since_last = max(0, total_uploaded - latest_snap.get('total_uploaded', total_uploaded))
                global_hour_volume = int((delta_since_last / elapsed_sec) * 3600)
                global_hour_note = f"прошло {int(elapsed_sec // 60)} мин с техлога"
            elif elapsed_sec < 300 and prev_snap:
                dt_prev = max(1, latest_snap['timestamp'] - prev_snap['timestamp'])
                delta_prev = max(0, latest_snap.get('total_uploaded', 0) - prev_snap.get('total_uploaded', 0))
                global_hour_volume = int((delta_prev / dt_prev) * 3600)
                global_hour_note = "прошлый полный час (<5м нового)"
            elif snap_1h:
                global_hour_volume = max(0, total_uploaded - snap_1h.get('total_uploaded', total_uploaded))
                global_hour_note = "по снимку ~1ч назад"

        if snap_24h:
            global_day_volume = max(0, total_uploaded - snap_24h.get('total_uploaded', total_uploaded))
        else:
            active_times = [s.get('active_seconds', 0) for s in summaries if s.get('active_seconds', 0) > 0]
            max_act = max(active_times) if active_times else 0
            global_day_volume = int((total_uploaded / max_act) * 86400) if max_act > 0 else 0

        if global_hour_volume == 0 and global_day_volume > 0:
            global_hour_volume = int(global_day_volume / 24)
            global_hour_note = "расчётное от суток"

        global_hour_speed_bps = global_hour_volume / 3600.0 if global_hour_volume > 0 else 0.0
        global_day_speed_bps = global_day_volume / 86400.0 if global_day_volume > 0 else 0.0

        max_act_global = max((s.get('active_seconds', 1) for s in summaries), default=1)
        global_ratio_h_all = (total_uploaded / max(1, max_act_global) * 3600.0 / total_size) if total_size > 0 else 0.0
        global_ratio_h_day = (global_day_volume / 24.0 / total_size) if total_size > 0 else 0.0
        global_ratio_h_hour = (global_hour_volume / total_size) if total_size > 0 else 0.0

        enhanced_items = []
        for s in summaries:
            item = dict(s)
            h_id = (s.get('hash_id') or s.get('hash') or '').lower()
            up = s.get('uploaded', 0)
            act = s.get('active_seconds', 0)
            sz = s.get('size', 0)

            item['ratio'] = round(up / sz, 2) if sz > 0 else 0.0

            avg_all = (up / act) if act > 0 else 0
            item['speed_all_time'] = avg_all
            item['speed_all_time_fmt'] = fmt_speed(avg_all)

            delta_1h = max(0, up - snap_1h_torrents[h_id]) if h_id in snap_1h_torrents else 0
            sp_1h = (delta_1h / dt_1h) if h_id in snap_1h_torrents else 0
            item['speed_1h'] = sp_1h
            item['speed_1h_fmt'] = fmt_speed(sp_1h)

            delta_24h = max(0, up - snap_24h_torrents[h_id]) if h_id in snap_24h_torrents else 0
            sp_24h = (delta_24h / dt_24h) if h_id in snap_24h_torrents else 0
            item['speed_24h'] = sp_24h
            item['speed_24h_fmt'] = fmt_speed(sp_24h)
            item['delta_24h'] = delta_24h

            vol_1h_bytes = delta_1h if delta_1h > 0 else int(avg_all * 3600)
            vol_24h_bytes = delta_24h if delta_24h > 0 else int(avg_all * 86400)
            item['vol_hour'] = vol_1h_bytes
            item['vol_hour_fmt'] = f"{vol_1h_bytes / (1024 * 1024):.2f} МБ/ч"
            item['vol_day'] = vol_24h_bytes
            item['vol_day_fmt'] = f"{vol_24h_bytes / (1024 * 1024):.2f} МБ/день"

            r_h_all = (avg_all * 3600.0 / sz) if sz > 0 else 0.0
            item['ratio_h_all'] = r_h_all
            item['ratio_h_all_fmt'] = fmt_ratio_h(r_h_all)
            item['ratio_h_hour'] = (sp_1h * 3600.0 / sz) if sz > 0 else 0.0
            item['ratio_h_hour_fmt'] = fmt_ratio_h(item['ratio_h_hour'])
            item['ratio_h_day'] = (sp_24h * 3600.0 / sz) if sz > 0 else 0.0
            item['ratio_h_day_fmt'] = fmt_ratio_h(item['ratio_h_day'])

            enhanced_items.append(item)

        return {
            'total_torrents': len(summaries),
            'total_size': total_size,
            'total_size_fmt': format_file_size(total_size),
            'total_uploaded': total_uploaded,
            'total_uploaded_fmt': format_file_size(total_uploaded),
            'global_hour_volume': global_hour_volume,
            'global_hour_volume_fmt': f"{format_file_size(global_hour_volume)} / час",
            'global_hour_speed_fmt': fmt_speed(global_hour_speed_bps),
            'global_hour_note': global_hour_note,
            'global_day_volume': global_day_volume,
            'global_day_volume_fmt': f"{format_file_size(global_day_volume)} / день",
            'global_day_speed_fmt': fmt_speed(global_day_speed_bps),
            'global_ratio_h_all_fmt': fmt_ratio_h(global_ratio_h_all),
            'global_ratio_h_day_fmt': fmt_ratio_h(global_ratio_h_day),
            'global_ratio_h_hour_fmt': fmt_ratio_h(global_ratio_h_hour),
            'items': enhanced_items
        }

    def get_charts_data(self, summaries):
        now_ts = time.time()
        rows = self.db.get_snapshots_since(now_ts - (14 * 86400))

        daily_map = {}
        day_hour_totals = {}
        prev_row = None

        for r in rows:
            if prev_row is not None:
                t1, t2 = prev_row['timestamp'], r['timestamp']
                dt_sec = t2 - t1
                delta = max(0, r['total_uploaded'] - prev_row['total_uploaded'])

                if dt_sec >= MIN_DELTA_SEC and delta > 0:
                    cur_dt = datetime.datetime.fromtimestamp(t1).replace(minute=0, second=0, microsecond=0)
                    cur_ts = cur_dt.timestamp()
                    while cur_ts < t2:
                        bucket_end = cur_ts + 3600.0
                        overlap = min(t2, bucket_end) - max(t1, cur_ts)
                        if overlap > 0:
                            part = delta * (overlap / dt_sec)
                            b_dt = datetime.datetime.fromtimestamp(cur_ts)
                            day_key = b_dt.strftime('%Y-%m-%d')
                            daily_map[day_key] = daily_map.get(day_key, 0.0) + part
                            dh_key = (day_key, b_dt.hour)
                            day_hour_totals[dh_key] = day_hour_totals.get(dh_key, 0.0) + part
                        cur_ts = bucket_end
            prev_row = r

        sorted_days = sorted(daily_map.keys())[-14:]
        daily_labels = [f"{d[8:10]}.{d[5:7]}" for d in sorted_days]
        daily_values_gb = [round(daily_map[d] / (1024 ** 3), 3) for d in sorted_days]

        detailed_24h = build_detailed_speed_series(self.db, hours=24)

        stats = self.get_stats(summaries)
        items = stats.get('items', [])
        top_items = sorted(items, key=lambda x: x.get('delta_24h', 0), reverse=True)[:5]

        if all(it.get('delta_24h', 0) <= 0 for it in top_items):
            oldest_24h_torrents = self.db.get_oldest_torrents_since(now_ts - 86400)
            if oldest_24h_torrents:
                for it in items:
                    h_id = (it.get('hash_id') or it.get('hash') or '').lower()
                    if h_id in oldest_24h_torrents:
                        it['delta_24h'] = max(0, it.get('uploaded', 0) - oldest_24h_torrents[h_id])
                top_items = sorted(items, key=lambda x: x.get('delta_24h', 0), reverse=True)[:5]

        top_labels, top_values_gb = [], []
        if any(it.get('delta_24h', 0) > 0 for it in top_items):
            for it in top_items:
                if it.get('delta_24h', 0) > 0:
                    nm = str(it.get('name', ''))
                    top_labels.append((nm[:28] + '…') if len(nm) > 29 else nm)
                    top_values_gb.append(round(it['delta_24h'] / (1024 ** 3), 3))
        else:
            top_all = sorted(items, key=lambda x: x.get('uploaded', 0), reverse=True)[:5]
            for it in top_all:
                if it.get('uploaded', 0) > 0:
                    nm = str(it.get('name', ''))
                    top_labels.append((nm[:28] + '…') if len(nm) > 29 else nm)
                    top_values_gb.append(round(it['uploaded'] / (1024 ** 3), 2))

        return {
            'daily': {'labels': daily_labels, 'values': daily_values_gb},
            'hourly': {
                'labels': [p['label'] for p in detailed_24h],
                'values': [p['speed_mbs'] for p in detailed_24h]
            },
            'detailed': detailed_24h,
            'top5': {'labels': top_labels, 'values': top_values_gb}
        }

    def calculate_smart_forecast(self, target_type, target_hash, target_str, speed_str, summaries):
        return calculate_smart_forecast(self.db, target_type, target_hash, target_str, speed_str, summaries)

    def export_forecast_csv(self, forecast_data):
        return export_forecast_csv(self.manual_folder, forecast_data)

    def save_manual_csv(self, items):
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath = os.path.join(self.manual_folder, f"summary_manual_{ts}.csv")
        try:
            with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
                f.write(f"# === РУЧНАЯ ВЫГРУЗКА СВОДКИ ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===\n")
                f.write(f"# Раздач: {len(items)}\n")
                w = csv.writer(f, delimiter=';')
                w.writerow([
                    'Имя', 'Хэш', 'Размер (байт)', 'Размер (ГБ)', 'Отдано (байт)', 'Отдано (ГБ)',
                    'Ratio', 'Ср. скорость (всё время)', 'Скорость за 1ч', 'Скорость за 24ч',
                    'МБ/ч', 'МБ/день', 'Ratio/ч (всего)', 'Ratio/ч (1ч)', 'Ratio/ч (24ч)', 'Дата создания'
                ])
                for s in items:
                    w.writerow([
                        sanitize_csv_cell(s.get('name', '')), sanitize_csv_cell(s.get('hash_id', '')),
                        s.get('size', 0), f"{s.get('size', 0) / (1024 ** 3):.2f}",
                        s.get('uploaded', 0), f"{s.get('uploaded', 0) / (1024 ** 3):.2f}",
                        f"{s.get('ratio', 0.0):.2f}",
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
        except Exception as e:
            write_error_log("Ошибка ручного сохранения CSV", e)
        return filepath

    def get_torrent_hourly_history(self, t_hash, limit_hours=36):
        rows = self.db.get_torrent_history_rows(t_hash, limit_hours=limit_hours)
        rows.reverse()
        result = []
        prev_snap = None
        for snap in rows:
            up = snap.get('uploaded')
            ts = float(snap.get('timestamp', 0) or 0)
            if up is not None:
                if prev_snap is not None:
                    p_up = prev_snap.get('uploaded', up)
                    p_ts = float(prev_snap.get('timestamp', ts) or ts)
                    dt_sec = max(1.0, ts - p_ts)
                    delta = max(0, up - p_up)
                    bps = delta / dt_sec
                    interval_min = int(round(dt_sec / 60.0))
                else:
                    delta = 0
                    bps = 0.0
                    interval_min = 0

                result.append({
                    'datetime': snap.get('datetime', ''),
                    'timestamp': int(ts),
                    'interval_min': interval_min,
                    'uploaded': up,
                    'uploaded_fmt': format_file_size(up),
                    'delta_bytes': delta,
                    'delta_mb': f"{delta / (1024*1024):.2f} МБ",
                    'speed_fmt': fmt_speed(bps)
                })
                prev_snap = snap
        result.reverse()
        return result

    def start_auto_export(self, get_summaries_fn):
        self._get_summaries_fn = get_summaries_fn
        self.scheduler.start(get_summaries_fn)


summary_tracker = SummaryTracker()