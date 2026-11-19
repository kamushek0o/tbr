# core/summary_tracker.py
import os
import time
import csv
import datetime
from utils.config import cfg
from utils.helpers import LOG_FOLDER, format_file_size, sanitize_csv_cell, write_error_log
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info
from core.history_db import HistoryDB, AUTO_FOLDER, MANUAL_FOLDER
from core.forecaster import fmt_ratio_h, fmt_speed, calculate_smart_forecast, export_forecast_csv
from core.scheduler import SnapshotScheduler, MIN_DELTA_SEC
from core.widget_service import build_detailed_speed_series, build_hourly_aggregated_speed_series, compute_top_n_torrents


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

        global_hour_volume, global_hour_note = 0, "ожидание замера"
        if latest_snap:
            elapsed_sec = now_ts - latest_snap.get('timestamp', now_ts)
            if 300 <= elapsed_sec <= 7200:
                global_hour_volume = int((max(0, total_uploaded - latest_snap.get('total_uploaded', total_uploaded)) / elapsed_sec) * 3600)
                global_hour_note = f"прошло {int(elapsed_sec // 60)} мин с техлога"
            elif elapsed_sec < 300 and prev_snap:
                dt_prev = max(1, latest_snap['timestamp'] - prev_snap['timestamp'])
                global_hour_volume = int((max(0, latest_snap.get('total_uploaded', 0) - prev_snap.get('total_uploaded', 0)) / dt_prev) * 3600)
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

        enhanced_items = []
        for s in summaries:
            item = dict(s)
            h_id = (s.get('hash_id') or s.get('hash') or '').lower()
            up, act, sz = s.get('uploaded', 0), s.get('active_seconds', 0), s.get('size', 0)
            item['ratio'] = round(up / sz, 2) if sz > 0 else 0.0
            avg_all = (up / act) if act > 0 else 0
            item['speed_all_time'], item['speed_all_time_fmt'] = avg_all, fmt_speed(avg_all)

            delta_1h = max(0, up - snap_1h_torrents[h_id]) if h_id in snap_1h_torrents else 0
            sp_1h = (delta_1h / dt_1h) if h_id in snap_1h_torrents else 0
            item['speed_1h'], item['speed_1h_fmt'] = sp_1h, fmt_speed(sp_1h)

            delta_24h = max(0, up - snap_24h_torrents[h_id]) if h_id in snap_24h_torrents else 0
            sp_24h = (delta_24h / dt_24h) if h_id in snap_24h_torrents else 0
            item['speed_24h'], item['speed_24h_fmt'], item['delta_24h'] = sp_24h, fmt_speed(sp_24h), delta_24h

            vol_1h = delta_1h if delta_1h > 0 else int(avg_all * 3600)
            vol_24h = delta_24h if delta_24h > 0 else int(avg_all * 86400)
            item['vol_hour'], item['vol_hour_fmt'] = vol_1h, f"{vol_1h / (1024 * 1024):.2f} МБ/ч"
            item['vol_day'], item['vol_day_fmt'] = vol_24h, f"{vol_24h / (1024 * 1024):.2f} МБ/день"

            r_h_all = (avg_all * 3600.0 / sz) if sz > 0 else 0.0
            item['ratio_h_all'], item['ratio_h_all_fmt'] = r_h_all, fmt_ratio_h(r_h_all)
            item['ratio_h_hour'] = (sp_1h * 3600.0 / sz) if sz > 0 else 0.0
            item['ratio_h_hour_fmt'] = fmt_ratio_h(item['ratio_h_hour'])
            item['ratio_h_day'] = (sp_24h * 3600.0 / sz) if sz > 0 else 0.0
            item['ratio_h_day_fmt'] = fmt_ratio_h(item['ratio_h_day'])
            enhanced_items.append(item)

        return {
            'total_torrents': len(summaries), 'total_size': total_size,
            'total_size_fmt': format_file_size(total_size), 'total_uploaded': total_uploaded,
            'total_uploaded_fmt': format_file_size(total_uploaded), 'global_hour_volume': global_hour_volume,
            'global_hour_volume_fmt': f"{format_file_size(global_hour_volume)} / час",
            'global_hour_speed_fmt': fmt_speed(global_hour_speed_bps), 'global_hour_note': global_hour_note,
            'global_day_volume': global_day_volume, 'global_day_volume_fmt': f"{format_file_size(global_day_volume)} / день",
            'global_day_speed_fmt': fmt_speed(global_day_speed_bps),
            'global_ratio_h_all_fmt': fmt_ratio_h((total_uploaded / max(1, max_act_global) * 3600.0 / total_size) if total_size > 0 else 0.0),
            'global_ratio_h_day_fmt': fmt_ratio_h((global_day_volume / 24.0 / total_size) if total_size > 0 else 0.0),
            'global_ratio_h_hour_fmt': fmt_ratio_h((global_hour_volume / total_size) if total_size > 0 else 0.0),
            'items': enhanced_items
        }

    def get_charts_data(self, summaries, hours=24, top_n=5, top_period='1d'):
        now_ts = time.time()
        win_hours = hours if hours in (6, 12, 24, 72, 168) else 24
        top_limit = max(1, min(25, int(top_n or 5)))
        per = top_period if top_period in ('1d', '7d', '30d', 'all') else '1d'

        rows = self.db.get_snapshots_since(now_ts - (14 * 86400))
        daily_map, prev_row = {}, None
        for r in rows:
            if prev_row is not None:
                t1, t2 = prev_row['timestamp'], r['timestamp']
                dt_sec = t2 - t1
                delta = max(0, r['total_uploaded'] - prev_row['total_uploaded'])
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

        sorted_days = sorted(daily_map.keys())[-14:]
        speed_series = build_detailed_speed_series(self.db, hours=win_hours) if win_hours <= 24 else build_hourly_aggregated_speed_series(self.db, hours=win_hours)

        ip, port = detect_qbittorrent_port(cfg.config)
        live = get_live_torrent_info(ip, port) if port else {}
        top_items = compute_top_n_torrents(self.db, summaries, live=live, top_n=top_limit, period=per)

        return {
            'daily': {'labels': [f"{d[8:10]}.{d[5:7]}" for d in sorted_days], 'values': [round(daily_map[d] / (1024 ** 3), 3) for d in sorted_days]},
            'hourly': {'hours': win_hours, 'labels': [p['label'] for p in speed_series], 'values': [p['speed_mbs'] for p in speed_series], 'meta': speed_series},
            'detailed': speed_series,
            'top5': {
                'n': top_limit,
                'period': per,
                'labels': [x['short_name'] for x in top_items],
                'full_labels': [x['full_name'] for x in top_items],
                'values': [x['gb'] for x in top_items]
            }
        }

    def get_torrent_chart_series(self, t_hash, period='24h'):
        hours = {'24h': 24, '7d': 168, '30d': 720}.get(period, 24)
        since_ts = time.time() - (hours * 3600)
        hl = (t_hash or '').lower()
        points = []
        with self.db._lock:
            try:
                with self.db._get_connection() as conn:
                    rows = conn.execute("""
                        SELECT s.timestamp, s.datetime, ts.uploaded
                        FROM snapshots s
                        JOIN torrent_snapshots ts ON s.id = ts.snapshot_id
                        WHERE ts.hash_id = ? AND s.timestamp >= ?
                        ORDER BY s.timestamp ASC
                    """, (hl, since_ts)).fetchall()
            except Exception:
                rows = []

        prev = None
        for r in rows:
            if prev is not None:
                dt = float(r['timestamp']) - float(prev['timestamp'])
                delta = max(0, int(r['uploaded']) - int(prev['uploaded']))
                if dt >= MIN_DELTA_SEC:
                    bps = delta / dt
                    lbl = str(r['datetime'] or '')[11:16] if hours <= 24 else str(r['datetime'] or '')[5:16]
                    points.append({
                        'label': lbl,
                        'speed_mbs': round(bps / (1024 * 1024), 3),
                        'delta_fmt': format_file_size(delta)
                    })
            prev = r
        return points

    def calculate_smart_forecast(self, target_type, target_hash, target_str, speed_str, summaries):
        return calculate_smart_forecast(self.db, target_type, target_hash, target_str, speed_str, summaries)

    def export_forecast_csv(self, forecast_data):
        return export_forecast_csv(self.manual_folder, forecast_data)

    def save_manual_csv(self, items):
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath = os.path.join(self.manual_folder, f"summary_manual_{ts}.csv")
        try:
            with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
                f.write(f"# === РУЧНАЯ ВЫГРУЗКА СВОДКИ ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===\n# Раздач: {len(items)}\n")
                w = csv.writer(f, delimiter=';')
                w.writerow(['Имя', 'Хэш', 'Размер (байт)', 'Размер (ГБ)', 'Отдано (байт)', 'Отдано (ГБ)', 'Ratio', 'Ср. скорость (всё время)', 'Скорость за 1ч', 'Скорость за 24ч', 'МБ/ч', 'МБ/день', 'Ratio/ч (всего)', 'Ratio/ч (1ч)', 'Ratio/ч (24ч)', 'Дата создания'])
                for s in items:
                    w.writerow([
                        sanitize_csv_cell(s.get('name', '')), sanitize_csv_cell(s.get('hash_id', '')),
                        s.get('size', 0), f"{s.get('size', 0) / (1024 ** 3):.2f}",
                        s.get('uploaded', 0), f"{s.get('uploaded', 0) / (1024 ** 3):.2f}", f"{s.get('ratio', 0.0):.2f}",
                        sanitize_csv_cell(s.get('speed_all_time_fmt', '0 B/s')), sanitize_csv_cell(s.get('speed_1h_fmt', '0 B/s')),
                        sanitize_csv_cell(s.get('speed_24h_fmt', '0 B/s')), sanitize_csv_cell(s.get('vol_hour_fmt', '0.00 МБ/ч')),
                        sanitize_csv_cell(s.get('vol_day_fmt', '0.00 МБ/день')), sanitize_csv_cell(s.get('ratio_h_all_fmt', '0.000 /ч')),
                        sanitize_csv_cell(s.get('ratio_h_hour_fmt', '0.000 /ч')), sanitize_csv_cell(s.get('ratio_h_day_fmt', '0.000 /ч')),
                        sanitize_csv_cell(s.get('created', ''))
                    ])
        except Exception as e:
            write_error_log("Ошибка ручного сохранения CSV", e)
        return filepath

    def get_torrent_hourly_history(self, t_hash, limit_hours=36):
        rows = self.db.get_torrent_history_rows(t_hash, limit_hours=limit_hours)
        rows.reverse()
        result, prev_snap = [], None
        for snap in rows:
            up, ts = snap.get('uploaded'), float(snap.get('timestamp', 0) or 0)
            if up is not None:
                if prev_snap is not None:
                    dt_sec = max(1.0, ts - float(prev_snap.get('timestamp', ts) or ts))
                    delta = max(0, up - prev_snap.get('uploaded', up))
                    bps, interval_min = delta / dt_sec, int(round(dt_sec / 60.0))
                else:
                    delta, bps, interval_min = 0, 0.0, 0
                result.append({'datetime': snap.get('datetime', ''), 'timestamp': int(ts), 'interval_min': interval_min, 'uploaded': up, 'uploaded_fmt': format_file_size(up), 'delta_bytes': delta, 'delta_mb': f"{delta / (1024*1024):.2f} МБ", 'speed_fmt': fmt_speed(bps)})
                prev_snap = snap
        result.reverse()
        return result

    def start_auto_export(self, get_summaries_fn):
        self._get_summaries_fn = get_summaries_fn
        self.scheduler.start(get_summaries_fn)


summary_tracker = SummaryTracker()