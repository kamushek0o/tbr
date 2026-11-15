# core/summary_tracker.py
import os
import time
import json
import csv
import sqlite3
import datetime
import threading
from utils.config import cfg
from utils.helpers import (
    LOG_FOLDER, format_file_size, parse_bytes, parse_speed,
    sanitize_csv_cell, write_log, write_error_log
)

AUTO_FOLDER = os.path.join(LOG_FOLDER, "auto_hourly")
MANUAL_FOLDER = os.path.join(LOG_FOLDER, "manual_exports")

os.makedirs(AUTO_FOLDER, exist_ok=True)
os.makedirs(MANUAL_FOLDER, exist_ok=True)


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


class SummaryTracker:
    def __init__(self, log_folder=LOG_FOLDER):
        self.log_folder = log_folder
        self.auto_folder = AUTO_FOLDER
        self.manual_folder = MANUAL_FOLDER
        self.db_file = os.path.join(self.auto_folder, "summary_history.db")
        self.old_json_file = os.path.join(self.auto_folder, "summary_history.json")
        self._thread = None
        self._running = False
        self._lock = threading.Lock()

        self._init_db()
        self._migrate_json_if_needed()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_file, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock:
            try:
                with self._get_connection() as conn:
                    conn.executescript("""
                        CREATE TABLE IF NOT EXISTS snapshots (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            timestamp REAL NOT NULL,
                            datetime TEXT NOT NULL,
                            total_uploaded INTEGER NOT NULL,
                            total_size INTEGER NOT NULL,
                            count INTEGER NOT NULL
                        );
                        CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(timestamp);

                        CREATE TABLE IF NOT EXISTS torrent_snapshots (
                            snapshot_id INTEGER NOT NULL,
                            hash_id TEXT NOT NULL,
                            uploaded INTEGER NOT NULL,
                            FOREIGN KEY(snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE
                        );
                        CREATE INDEX IF NOT EXISTS idx_tor_snap ON torrent_snapshots(snapshot_id, hash_id);
                        CREATE INDEX IF NOT EXISTS idx_tor_hash ON torrent_snapshots(hash_id);
                    """)
            except Exception as e:
                write_error_log("Инициализация SQLite summary_history.db", e)

    def _migrate_json_if_needed(self):
        if not os.path.exists(self.old_json_file):
            return
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM snapshots")
                    if cur.fetchone()[0] > 0:
                        return

                    write_log("summary", "Обнаружен старый summary_history.json. Начинаем миграцию в SQLite...")
                    with open(self.old_json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    if isinstance(data, list):
                        for s in data:
                            ts = s.get('timestamp', 0)
                            dt = s.get('datetime', '')
                            tot_up = s.get('total_uploaded', 0)
                            tot_sz = s.get('total_size', 0)
                            count = s.get('count', 0)
                            torrents = s.get('torrents', {})

                            cur.execute(
                                "INSERT INTO snapshots (timestamp, datetime, total_uploaded, total_size, count) VALUES (?, ?, ?, ?, ?)",
                                (ts, dt, tot_up, tot_sz, count)
                            )
                            snap_id = cur.lastrowid
                            if torrents and isinstance(torrents, dict):
                                rows = [(snap_id, str(h).lower(), int(up)) for h, up in torrents.items()]
                                cur.executemany("INSERT INTO torrent_snapshots (snapshot_id, hash_id, uploaded) VALUES (?, ?, ?)", rows)

                    conn.commit()
                    write_log("summary", "Миграция в SQLite успешно завершена.")

                bak_file = self.old_json_file + ".migrated"
                if not os.path.exists(bak_file):
                    os.rename(self.old_json_file, bak_file)
            except Exception as e:
                write_error_log("Ошибка миграции summary_history.json в SQLite", e)

    def record_snapshot(self, summaries):
        with self._lock:
            try:
                now = time.time()
                dt_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                tot_up = sum(s.get('uploaded', 0) for s in summaries)
                tot_sz = sum(s.get('size', 0) for s in summaries)
                count = len(summaries)

                with self._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO snapshots (timestamp, datetime, total_uploaded, total_size, count) VALUES (?, ?, ?, ?, ?)",
                        (now, dt_str, tot_up, tot_sz, count)
                    )
                    snap_id = cur.lastrowid

                    tor_rows = []
                    for s in summaries:
                        h_id = (s.get('hash_id') or s.get('hash') or '').lower()
                        if h_id:
                            tor_rows.append((snap_id, h_id, int(s.get('uploaded', 0))))

                    if tor_rows:
                        cur.executemany(
                            "INSERT INTO torrent_snapshots (snapshot_id, hash_id, uploaded) VALUES (?, ?, ?)",
                            tor_rows
                        )

                    cutoff = now - (35 * 86400)
                    cur.execute("DELETE FROM snapshots WHERE timestamp < ?", (cutoff,))
                    conn.commit()
            except Exception as e:
                write_error_log("Ошибка записи record_snapshot в SQLite", e)

    def get_stats(self, summaries):
        now_ts = time.time()
        total_uploaded = sum(s.get('uploaded', 0) for s in summaries)
        total_size = sum(s.get('size', 0) for s in summaries)

        snap_1h = None
        dt_1h = 3600
        snap_24h = None
        dt_24h = 86400
        snap_1h_torrents = {}
        snap_24h_torrents = {}

        latest_snap = None
        prev_snap = None

        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, timestamp, total_uploaded FROM snapshots ORDER BY timestamp DESC LIMIT 2")
                    last_rows = cur.fetchall()
                    if last_rows:
                        latest_snap = dict(last_rows[0])
                        if len(last_rows) > 1:
                            prev_snap = dict(last_rows[1])

                    cur.execute("""
                        SELECT id, timestamp, total_uploaded FROM snapshots
                        WHERE timestamp BETWEEN ? AND ?
                        ORDER BY ABS((? - timestamp) - 3600) ASC LIMIT 1
                    """, (now_ts - 7200, now_ts - 1800, now_ts))
                    r_1h = cur.fetchone()
                    if r_1h:
                        snap_1h = dict(r_1h)
                        dt_1h = max(1, now_ts - snap_1h['timestamp'])
                        cur.execute("SELECT hash_id, uploaded FROM torrent_snapshots WHERE snapshot_id = ?", (snap_1h['id'],))
                        snap_1h_torrents = {row['hash_id']: row['uploaded'] for row in cur.fetchall()}

                    cur.execute("""
                        SELECT id, timestamp, total_uploaded FROM snapshots
                        WHERE timestamp BETWEEN ? AND ?
                        ORDER BY ABS((? - timestamp) - 86400) ASC LIMIT 1
                    """, (now_ts - 100000, now_ts - 72000, now_ts))
                    r_24h = cur.fetchone()
                    if r_24h:
                        snap_24h = dict(r_24h)
                        dt_24h = max(1, now_ts - snap_24h['timestamp'])
                        cur.execute("SELECT hash_id, uploaded FROM torrent_snapshots WHERE snapshot_id = ?", (snap_24h['id'],))
                        snap_24h_torrents = {row['hash_id']: row['uploaded'] for row in cur.fetchall()}
            except Exception as e:
                write_error_log("Ошибка get_stats из SQLite", e)

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

            delta_1h = 0
            if h_id in snap_1h_torrents:
                delta_1h = max(0, up - snap_1h_torrents[h_id])
                sp_1h = delta_1h / dt_1h
            else:
                sp_1h = 0
            item['speed_1h'] = sp_1h
            item['speed_1h_fmt'] = fmt_speed(sp_1h)

            delta_24h = 0
            if h_id in snap_24h_torrents:
                delta_24h = max(0, up - snap_24h_torrents[h_id])
                sp_24h = delta_24h / dt_24h
            else:
                sp_24h = 0
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
        """Собирает данные из SQLite для графиков: по дням, по часам суток и топ-5 за 24ч."""
        now_ts = time.time()
        cutoff_14d = now_ts - (14 * 86400)

        rows = []
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT timestamp, datetime, total_uploaded FROM snapshots WHERE timestamp >= ? ORDER BY timestamp ASC",
                        (cutoff_14d,)
                    )
                    rows = [dict(r) for r in cur.fetchall()]
            except Exception as e:
                write_error_log("Ошибка get_charts_data из SQLite", e)

        daily_map = {}
        hourly_buckets = {h: [] for h in range(24)}
        prev_up = None

        for r in rows:
            up = r['total_uploaded']
            dt_str = r['datetime'] or ''
            if prev_up is not None and len(dt_str) >= 13:
                delta = max(0, up - prev_up)
                day_key = dt_str[:10]
                daily_map[day_key] = daily_map.get(day_key, 0) + delta
                try:
                    hour_key = int(dt_str[11:13])
                    if 0 <= hour_key <= 23:
                        hourly_buckets[hour_key].append(delta)
                except ValueError:
                    pass
            prev_up = up

        sorted_days = sorted(daily_map.keys())[-14:]
        daily_labels = [f"{d[8:10]}.{d[5:7]}" for d in sorted_days]
        daily_values_gb = [round(daily_map[d] / (1024 ** 3), 3) for d in sorted_days]

        hourly_labels = [f"{h:02d}:00" for h in range(24)]
        hourly_values_mb = [
            round((sum(hourly_buckets[h]) / len(hourly_buckets[h])) / (1024 ** 2), 1)
            if hourly_buckets[h] else 0.0
            for h in range(24)
        ]

        # Топ-5 раздач за последние 24 часа (с фолбэком, если база свежая <20ч)
        stats = self.get_stats(summaries)
        items = stats.get('items', [])
        top_items = sorted(items, key=lambda x: x.get('delta_24h', 0), reverse=True)[:5]

        if all(it.get('delta_24h', 0) <= 0 for it in top_items):
            oldest_24h_torrents = {}
            with self._lock:
                try:
                    with self._get_connection() as conn:
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT id FROM snapshots WHERE timestamp >= ? ORDER BY timestamp ASC LIMIT 1",
                            (now_ts - 86400,)
                        )
                        r_old = cur.fetchone()
                        if r_old:
                            cur.execute(
                                "SELECT hash_id, uploaded FROM torrent_snapshots WHERE snapshot_id = ?",
                                (r_old['id'],)
                            )
                            oldest_24h_torrents = {row['hash_id']: row['uploaded'] for row in cur.fetchall()}
                except Exception:
                    pass

            if oldest_24h_torrents:
                for it in items:
                    h_id = (it.get('hash_id') or it.get('hash') or '').lower()
                    if h_id in oldest_24h_torrents:
                        it['delta_24h'] = max(0, it.get('uploaded', 0) - oldest_24h_torrents[h_id])
                top_items = sorted(items, key=lambda x: x.get('delta_24h', 0), reverse=True)[:5]

        top_labels = []
        top_values_gb = []
        if any(it.get('delta_24h', 0) > 0 for it in top_items):
            for it in top_items:
                if it.get('delta_24h', 0) > 0:
                    nm = str(it.get('name', ''))
                    top_labels.append((nm[:28] + '…') if len(nm) > 29 else nm)
                    top_values_gb.append(round(it['delta_24h'] / (1024 ** 3), 3))
        else:
            # Крайний фолбэк (если снимков ещё мало или раздачи стояли): топ-5 по общей отдаче
            top_all = sorted(items, key=lambda x: x.get('uploaded', 0), reverse=True)[:5]
            for it in top_all:
                if it.get('uploaded', 0) > 0:
                    nm = str(it.get('name', ''))
                    top_labels.append((nm[:28] + '…') if len(nm) > 29 else nm)
                    top_values_gb.append(round(it['uploaded'] / (1024 ** 3), 2))

        return {
            'daily': {'labels': daily_labels, 'values': daily_values_gb},
            'hourly': {'labels': hourly_labels, 'values': hourly_values_mb},
            'top5': {'labels': top_labels, 'values': top_values_gb}
        }

    def calculate_smart_forecast(self, target_type, target_hash, target_str, speed_str, summaries):
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

            with self._lock:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*), MIN(timestamp) FROM snapshots")
                    cnt, min_ts = cur.fetchone()

            days_available = (now_ts - min_ts) / 86400.0 if (cnt and min_ts) else 0.0

            if not is_manual and (cnt < 2 or days_available < (req_days - 0.15)):
                return {
                    'success': False, 'need_manual': True,
                    'days_available': round(days_available, 1),
                    'req_days': req_days,
                    'error': f"Недостаточно данных (накоплено {days_available:.1f} из {req_days} дн.). Укажите скорость вручную."
                }

            def get_hist_delta(t_start, t_end):
                with self._lock:
                    with self._get_connection() as conn:
                        cur = conn.cursor()
                        cur.execute("SELECT id, total_uploaded FROM snapshots ORDER BY ABS(timestamp - ?) ASC LIMIT 1", (t_start,))
                        r1 = cur.fetchone()
                        cur.execute("SELECT id, total_uploaded FROM snapshots ORDER BY ABS(timestamp - ?) ASC LIMIT 1", (t_end,))
                        r2 = cur.fetchone()

                        if not r1 or not r2:
                            return 0

                        if is_seedbox:
                            return max(0, r2['total_uploaded'] - r1['total_uploaded'])

                        cur.execute("SELECT uploaded FROM torrent_snapshots WHERE snapshot_id = ? AND hash_id = ? LIMIT 1", (r1['id'], t_hash_lower))
                        u1_row = cur.fetchone()
                        u1 = u1_row['uploaded'] if u1_row else 0

                        cur.execute("SELECT uploaded FROM torrent_snapshots WHERE snapshot_id = ? AND hash_id = ? LIMIT 1", (r2['id'], t_hash_lower))
                        u2_row = cur.fetchone()
                        u2 = u2_row['uploaded'] if u2_row else 0

                        return max(0, u2 - u1)

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
                    d1 = get_hist_delta(h_start - (168 * 3600), h_end - (168 * 3600)) if nw1 > 0 else 0
                    d2 = get_hist_delta(h_start - (336 * 3600), h_end - (336 * 3600)) if nw2 > 0 else 0
                    d3 = get_hist_delta(h_start - (504 * 3600), h_end - (504 * 3600)) if nw3 > 0 else 0
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

    def export_forecast_csv(self, forecast_data):
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        raw_name = str(forecast_data.get('name', 'forecast'))
        clean_name = "".join(c for c in raw_name if c.isalnum() or c in (' ', '_', '-')).strip()[:30] or 'forecast'
        filename = f"forecast_24h_{clean_name}_{ts}.csv"
        filepath = os.path.join(self.manual_folder, filename)

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

    def export_hourly_csv(self, summaries):
        if not summaries:
            return None
        self.record_snapshot(summaries)
        stats = self.get_stats(summaries)

        ts = datetime.datetime.now().strftime('%Y%m%d_%H00')
        filename = f"summary_hourly_{ts}.csv"
        filepath = os.path.join(self.auto_folder, filename)
        latest_path = os.path.join(self.auto_folder, "summary_auto_latest.csv")

        header_lines = [
            f"# === ПОЧАСОВАЯ ВЫГРУЗКА СВОДКИ РАЗДАЧ (АВТО) ===",
            f"# Дата выгрузки: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Всего раздач: {stats['total_torrents']}",
            f"# Общий объем: {stats['total_size_fmt']}",
            f"# Всего отдано: {stats['total_uploaded_fmt']}",
            f"# Сумма за 1 час: {stats['global_hour_volume_fmt']} ({stats['global_hour_speed_fmt']})",
            f"# Объем в день: {stats['global_day_volume_fmt']} ({stats['global_day_speed_fmt']})",
            f"# Ratio/ч: {stats['global_ratio_h_all_fmt']} (всего) | {stats['global_ratio_h_day_fmt']} (день) | {stats['global_ratio_h_hour_fmt']} (час)",
            f"# =========================================="
        ]

        for target in [filepath, latest_path]:
            try:
                with open(target, 'w', encoding='utf-8-sig', newline='') as f:
                    f.write('\n'.join(header_lines) + '\n')
                    w = csv.writer(f, delimiter=';')
                    w.writerow([
                        'Имя', 'Хэш', 'Размер (байт)', 'Отдано (байт)', 'Ratio',
                        'Ср. скорость (всё время)', 'Скорость за 1ч', 'Скорость за 24ч',
                        'МБ/ч', 'МБ/день',
                        'Ratio/ч (всего)', 'Ratio/ч (1ч)', 'Ratio/ч (24ч)',
                        'Активно (сек)', 'Дата создания'
                    ])
                    for s in stats['items']:
                        w.writerow([
                            sanitize_csv_cell(s.get('name', '')),
                            sanitize_csv_cell(s.get('hash_id', '')),
                            s.get('size', 0),
                            s.get('uploaded', 0),
                            f"{s.get('ratio', 0.0):.2f}",
                            sanitize_csv_cell(s.get('speed_all_time_fmt', '0 B/s')),
                            sanitize_csv_cell(s.get('speed_1h_fmt', '0 B/s')),
                            sanitize_csv_cell(s.get('speed_24h_fmt', '0 B/s')),
                            sanitize_csv_cell(s.get('vol_hour_fmt', '0.00 МБ/ч')),
                            sanitize_csv_cell(s.get('vol_day_fmt', '0.00 МБ/день')),
                            sanitize_csv_cell(s.get('ratio_h_all_fmt', '0.000 /ч')),
                            sanitize_csv_cell(s.get('ratio_h_hour_fmt', '0.000 /ч')),
                            sanitize_csv_cell(s.get('ratio_h_day_fmt', '0.000 /ч')),
                            s.get('active_seconds', 0),
                            sanitize_csv_cell(s.get('created', ''))
                        ])
            except Exception as e:
                write_error_log("Ошибка экспорта почасового CSV", e)

        write_log("summary", f"Авто-сводка выгружена в {filename}")
        return filepath

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
                    'МБ/ч', 'МБ/день',
                    'Ratio/ч (всего)', 'Ratio/ч (1ч)', 'Ratio/ч (24ч)', 'Дата создания'
                ])
                for s in items:
                    w.writerow([
                        sanitize_csv_cell(s.get('name', '')),
                        sanitize_csv_cell(s.get('hash_id', '')),
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
        t_hash_lower = (t_hash or '').lower()
        rows = []
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    if t_hash == 'all':
                        cur.execute("""
                            SELECT datetime, timestamp, total_uploaded AS uploaded
                            FROM snapshots
                            ORDER BY timestamp DESC
                            LIMIT ?
                        """, (limit_hours,))
                    else:
                        cur.execute("""
                            SELECT s.datetime, s.timestamp, ts.uploaded
                            FROM snapshots s
                            JOIN torrent_snapshots ts ON s.id = ts.snapshot_id
                            WHERE ts.hash_id = ?
                            ORDER BY s.timestamp DESC
                            LIMIT ?
                        """, (t_hash_lower, limit_hours))
                    rows = [dict(r) for r in cur.fetchall()]
            except Exception as e:
                write_error_log("Ошибка get_torrent_hourly_history из SQLite", e)

        rows.reverse()
        result = []
        prev_up = None
        for snap in rows:
            up = snap.get('uploaded')
            if up is not None:
                delta = max(0, up - prev_up) if prev_up is not None else 0
                result.append({
                    'datetime': snap.get('datetime', ''),
                    'timestamp': snap.get('timestamp', 0),
                    'uploaded': up,
                    'uploaded_fmt': format_file_size(up),
                    'delta_bytes': delta,
                    'delta_mb': f"{delta / (1024*1024):.2f} МБ",
                    'speed_fmt': fmt_speed(delta / 3600) if delta > 0 else "0 B/s"
                })
                prev_up = up
        result.reverse()
        return result

    def start_auto_export(self, get_summaries_fn):
        if self._running:
            return
        self._running = True

        def loop():
            try:
                sums = get_summaries_fn()
                if sums:
                    self.export_hourly_csv(sums)
            except Exception as e:
                write_error_log("Ошибка начальной выгрузки сводки", e)

            while self._running:
                now = datetime.datetime.now()
                seconds_until_next_hour = (60 - now.minute - 1) * 60 + (60 - now.second)
                if seconds_until_next_hour <= 0:
                    seconds_until_next_hour = 3600

                for _ in range(seconds_until_next_hour):
                    if not self._running:
                        return
                    time.sleep(1)

                try:
                    sums = get_summaries_fn()
                    if sums:
                        self.export_hourly_csv(sums)
                except Exception as e:
                    write_error_log("Ошибка циклической выгрузки сводки", e)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()


summary_tracker = SummaryTracker()