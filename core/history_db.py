# core/history_db.py
import os
import re
import csv
import json
import time
import sqlite3
import datetime
import threading
from utils.helpers import LOG_FOLDER, write_log, write_error_log

AUTO_FOLDER = os.path.join(LOG_FOLDER, "auto_hourly")
MANUAL_FOLDER = os.path.join(LOG_FOLDER, "manual_exports")

os.makedirs(AUTO_FOLDER, exist_ok=True)
os.makedirs(MANUAL_FOLDER, exist_ok=True)

_DATE_COMMENT_RE = re.compile(r'^#\s*Дата выгрузки:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})')
_FNAME_DATE_RE = re.compile(r'summary_hourly_(\d{8})_(\d{4})\.csv$', re.IGNORECASE)


class HistoryDB:
    def __init__(self, auto_folder=AUTO_FOLDER):
        self.auto_folder = auto_folder
        self.db_file = os.path.join(self.auto_folder, "summary_history.db")
        self.old_json_file = os.path.join(self.auto_folder, "summary_history.json")
        self._lock = threading.Lock()

        self._init_db()
        self._migrate_json_if_needed()
        self._migrate_old_csvs_if_needed()

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
                                cur.executemany(
                                    "INSERT INTO torrent_snapshots (snapshot_id, hash_id, uploaded) VALUES (?, ?, ?)",
                                    rows
                                )

                    conn.commit()
                    write_log("summary", "Миграция JSON в SQLite успешно завершена.")

                bak_file = self.old_json_file + ".migrated"
                if not os.path.exists(bak_file):
                    os.rename(self.old_json_file, bak_file)
            except Exception as e:
                write_error_log("Ошибка миграции summary_history.json в SQLite", e)

    def _migrate_old_csvs_if_needed(self):
        candidates = []
        for folder in (LOG_FOLDER, self.auto_folder):
            if not os.path.exists(folder):
                continue
            for fname in os.listdir(folder):
                low = fname.lower()
                if low.startswith('summary_hourly_') and low.endswith('.csv'):
                    candidates.append(os.path.join(folder, fname))

        if not candidates:
            return

        imported = 0
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    for path in sorted(candidates):
                        try:
                            with open(path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                                lines = f.readlines()

                            snap_dt_str = None
                            data_lines = []
                            for line in lines:
                                if line.startswith('#'):
                                    m = _DATE_COMMENT_RE.match(line.strip())
                                    if m:
                                        snap_dt_str = m.group(1)
                                elif line.strip():
                                    data_lines.append(line)

                            if not data_lines:
                                continue

                            if snap_dt_str:
                                snap_ts = datetime.datetime.strptime(snap_dt_str, '%Y-%m-%d %H:%M:%S').timestamp()
                            else:
                                mf = _FNAME_DATE_RE.search(os.path.basename(path))
                                if mf:
                                    dt_obj = datetime.datetime.strptime(mf.group(1) + mf.group(2), '%Y%m%d%H%M')
                                    snap_ts = dt_obj.timestamp()
                                    snap_dt_str = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
                                else:
                                    snap_ts = os.path.getmtime(path)
                                    snap_dt_str = datetime.datetime.fromtimestamp(snap_ts).strftime('%Y-%m-%d %H:%M:%S')

                            cur.execute("SELECT 1 FROM snapshots WHERE ABS(timestamp - ?) < 180 LIMIT 1", (snap_ts,))
                            if cur.fetchone():
                                continue

                            reader = csv.DictReader(data_lines, delimiter=';')
                            tor_rows = []
                            tot_up = 0
                            tot_sz = 0
                            for row in reader:
                                h_id = (row.get('Хэш') or row.get('hash_id') or '').strip().lstrip("'").lower()
                                if not h_id:
                                    continue
                                try:
                                    up = int(float(row.get('Отдано (байт)') or row.get('uploaded') or 0))
                                    sz = int(float(row.get('Размер (байт)') or row.get('size') or 0))
                                except (ValueError, TypeError):
                                    continue
                                tot_up += up
                                tot_sz += sz
                                tor_rows.append((h_id, up))

                            if not tor_rows:
                                continue

                            cur.execute(
                                "INSERT INTO snapshots (timestamp, datetime, total_uploaded, total_size, count) VALUES (?, ?, ?, ?, ?)",
                                (snap_ts, snap_dt_str, tot_up, tot_sz, len(tor_rows))
                            )
                            snap_id = cur.lastrowid
                            cur.executemany(
                                "INSERT INTO torrent_snapshots (snapshot_id, hash_id, uploaded) VALUES (?, ?, ?)",
                                [(snap_id, h, u) for h, u in tor_rows]
                            )
                            imported += 1
                        except Exception as e:
                            write_error_log(f"Импорт старого CSV {os.path.basename(path)}", e)

                    if imported > 0:
                        conn.commit()
                        write_log("summary", f"Импортировано старых почасовых CSV-снимков в SQLite: {imported}")
            except Exception as e:
                write_error_log("Ошибка _migrate_old_csvs_if_needed", e)

    def get_last_snapshot_ts(self):
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT MAX(timestamp) FROM snapshots")
                    row = cur.fetchone()
                    return row[0] if row and row[0] is not None else None
            except Exception:
                return None

    def record_snapshot(self, summaries, min_delta_sec=60):
        with self._lock:
            try:
                now = time.time()
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT MAX(timestamp) FROM snapshots")
                    row = cur.fetchone()
                    last_ts = row[0] if row and row[0] is not None else None
                    if last_ts is not None and (now - last_ts) < min_delta_sec:
                        return False

                    dt_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    tot_up = sum(s.get('uploaded', 0) for s in summaries)
                    tot_sz = sum(s.get('size', 0) for s in summaries)
                    count = len(summaries)

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
                    conn.commit()
                    return True
            except Exception as e:
                write_error_log("Ошибка записи record_snapshot в SQLite", e)
                return False

    def downsample_old_snapshots(self):
        now = time.time()
        cutoff_hourly = now - (30 * 86400)
        cutoff_daily = now - (365 * 86400)

        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT id, timestamp, datetime FROM snapshots WHERE timestamp < ? ORDER BY timestamp ASC",
                        (cutoff_hourly,)
                    )
                    rows = cur.fetchall()
                    if not rows:
                        return 0

                    buckets = {}
                    for r in rows:
                        ts = r['timestamp']
                        dt_str = r['datetime'] or datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
                        if ts < cutoff_daily:
                            key = ('day', dt_str[:10])
                        else:
                            key = ('hour', dt_str[:13])
                        buckets.setdefault(key, []).append((ts, r['id']))

                    delete_ids = []
                    for items in buckets.values():
                        if len(items) > 1:
                            items.sort(key=lambda x: x[0])
                            delete_ids.extend(item[1] for item in items[:-1])

                    if delete_ids:
                        for i in range(0, len(delete_ids), 500):
                            chunk = delete_ids[i:i + 500]
                            placeholders = ','.join('?' for _ in chunk)
                            cur.execute(f"DELETE FROM snapshots WHERE id IN ({placeholders})", chunk)
                        conn.commit()
                        write_log("summary", f"Даунсэмплинг SQLite: сжато старых снимков: {len(delete_ids)}")
                    return len(delete_ids)
            except Exception as e:
                write_error_log("Ошибка downsample_old_snapshots", e)
                return 0

    def get_stats_snapshots(self, now_ts):
        latest_snap = None
        prev_snap = None
        snap_1h = None
        snap_24h = None
        snap_1h_torrents = {}
        snap_24h_torrents = {}

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
                        cur.execute("SELECT hash_id, uploaded FROM torrent_snapshots WHERE snapshot_id = ?", (snap_24h['id'],))
                        snap_24h_torrents = {row['hash_id']: row['uploaded'] for row in cur.fetchall()}
            except Exception as e:
                write_error_log("Ошибка get_stats_snapshots из SQLite", e)

        return latest_snap, prev_snap, snap_1h, snap_1h_torrents, snap_24h, snap_24h_torrents

    def get_snapshots_since(self, since_ts):
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT timestamp, datetime, total_uploaded FROM snapshots WHERE timestamp >= ? ORDER BY timestamp ASC",
                        (since_ts,)
                    )
                    return [dict(r) for r in cur.fetchall()]
            except Exception as e:
                write_error_log("Ошибка get_snapshots_since из SQLite", e)
                return []

    def get_oldest_torrents_since(self, since_ts):
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT id FROM snapshots WHERE timestamp >= ? ORDER BY timestamp ASC LIMIT 1",
                        (since_ts,)
                    )
                    r_old = cur.fetchone()
                    if not r_old:
                        return {}
                    cur.execute(
                        "SELECT hash_id, uploaded FROM torrent_snapshots WHERE snapshot_id = ?",
                        (r_old['id'],)
                    )
                    return {row['hash_id']: row['uploaded'] for row in cur.fetchall()}
            except Exception:
                return {}

    def get_snapshot_range_info(self):
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*), MIN(timestamp) FROM snapshots")
                return cur.fetchone()

    def get_hist_delta(self, t_start, t_end, is_seedbox, t_hash_lower=''):
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

    def get_torrent_history_rows(self, t_hash, limit_hours=36):
        t_hash_lower = (t_hash or '').lower()
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
                    return [dict(r) for r in cur.fetchall()]
            except Exception as e:
                write_error_log("Ошибка get_torrent_history_rows из SQLite", e)
                return []

    def get_torrent_window_bounds(self, t_hash, since_ts, until_ts):
        t_hash_lower = (t_hash or '').lower()
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT s.timestamp, ts.uploaded
                        FROM snapshots s
                        JOIN torrent_snapshots ts ON s.id = ts.snapshot_id
                        WHERE ts.hash_id = ? AND s.timestamp BETWEEN ? AND ?
                        ORDER BY s.timestamp ASC
                    """, (t_hash_lower, since_ts, until_ts))
                    rows = cur.fetchall()
                    if not rows:
                        return None, None, 0
                    first = (rows[0]['timestamp'], rows[0]['uploaded'])
                    last = (rows[-1]['timestamp'], rows[-1]['uploaded'])
                    return first, last, len(rows)
            except Exception:
                return None, None, 0

    def get_snapshots_by_day_paginated(self, start_ts, end_ts, page=1, per_page=15):
        page = max(1, int(page))
        per_page = max(1, min(100, int(per_page)))
        offset = (page - 1) * per_page
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM snapshots WHERE timestamp BETWEEN ? AND ?", (start_ts, end_ts))
                    total = cur.fetchone()[0]
                    cur.execute(
                        """SELECT id, timestamp, datetime, total_uploaded, total_size, count
                           FROM snapshots
                           WHERE timestamp BETWEEN ? AND ?
                           ORDER BY timestamp DESC
                           LIMIT ? OFFSET ?""",
                        (start_ts, end_ts, per_page, offset)
                    )
                    rows = [dict(r) for r in cur.fetchall()]
                    total_pages = max(1, (total + per_page - 1) // per_page)
                    return {'items': rows, 'total': total, 'page': page, 'per_page': per_page, 'total_pages': total_pages}
            except Exception as e:
                write_error_log("Ошибка get_snapshots_by_day_paginated", e)
                return {'items': [], 'total': 0, 'page': 1, 'per_page': per_page, 'total_pages': 1}

    def get_snapshots_by_day_all(self, start_ts, end_ts):
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        """SELECT datetime, total_uploaded, total_size, count
                           FROM snapshots
                           WHERE timestamp BETWEEN ? AND ?
                           ORDER BY timestamp ASC""",
                        (start_ts, end_ts)
                    )
                    return [dict(r) for r in cur.fetchall()]
            except Exception:
                return []