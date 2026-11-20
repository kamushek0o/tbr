# core/history_db.py
import os
import time
import sqlite3
import datetime
import threading
from utils.helpers import LOG_FOLDER, write_log, write_error_log
from core.history_migrations import migrate_json_if_needed, migrate_old_csvs_if_needed

AUTO_FOLDER = os.path.join(LOG_FOLDER, "auto_hourly")
MANUAL_FOLDER = os.path.join(LOG_FOLDER, "manual_exports")

os.makedirs(AUTO_FOLDER, exist_ok=True)
os.makedirs(MANUAL_FOLDER, exist_ok=True)


class HistoryDB:
    def __init__(self, auto_folder=AUTO_FOLDER):
        self.auto_folder = auto_folder
        self.db_file = os.path.join(self.auto_folder, "summary_history.db")
        self.old_json_file = os.path.join(self.auto_folder, "summary_history.json")
        self._lock = threading.Lock()

        self._init_db()
        with self._lock:
            migrate_json_if_needed(self._get_connection, self.old_json_file)
            migrate_old_csvs_if_needed(self._get_connection, self.auto_folder)

    def _get_connection(self):
        conn = sqlite3.connect(self.db_file, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout = 30000;")
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
                            count INTEGER NOT NULL,
                            ignore_in_stats INTEGER NOT NULL DEFAULT 0
                        );
                        CREATE TABLE IF NOT EXISTS torrent_snapshots (
                            snapshot_id INTEGER NOT NULL,
                            hash_id TEXT NOT NULL,
                            uploaded INTEGER NOT NULL,
                            FOREIGN KEY(snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE
                        );
                    """)
                    cur = conn.cursor()
                    cur.execute("PRAGMA table_info(snapshots)")
                    cols = {r['name'] for r in cur.fetchall()}
                    if 'ignore_in_stats' not in cols:
                        cur.execute("ALTER TABLE snapshots ADD COLUMN ignore_in_stats INTEGER NOT NULL DEFAULT 0")

                    conn.executescript("""
                        CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(timestamp);
                        CREATE INDEX IF NOT EXISTS idx_snapshots_ts_up ON snapshots(timestamp, id, total_uploaded);
                        CREATE INDEX IF NOT EXISTS idx_tor_snap ON torrent_snapshots(snapshot_id, hash_id);
                        CREATE INDEX IF NOT EXISTS idx_tor_hash ON torrent_snapshots(hash_id);
                        CREATE INDEX IF NOT EXISTS idx_tor_hash_snap ON torrent_snapshots(hash_id, snapshot_id, uploaded);
                    """)
                    conn.commit()
            except Exception as e:
                write_error_log("Инициализация SQLite summary_history.db", e)

    def set_snapshot_ignored(self, snap_id, ignored=True):
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.execute(
                        "UPDATE snapshots SET ignore_in_stats = ? WHERE id = ?",
                        (1 if ignored else 0, int(snap_id))
                    )
                    conn.commit()
                    return cur.rowcount > 0
            except Exception as e:
                write_error_log("set_snapshot_ignored", e)
                return False

    def get_last_snapshot_ts(self):
        with self._lock:
            try:
                with self._get_connection() as conn:
                    row = conn.execute("SELECT MAX(timestamp) FROM snapshots WHERE COALESCE(ignore_in_stats, 0) = 0").fetchone()
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
                    cur.execute(
                        "INSERT INTO snapshots (timestamp, datetime, total_uploaded, total_size, count, ignore_in_stats) VALUES (?, ?, ?, ?, ?, 0)",
                        (now, dt_str, tot_up, tot_sz, len(summaries))
                    )
                    snap_id = cur.lastrowid

                    tor_rows = [
                        (snap_id, (s.get('hash_id') or s.get('hash') or '').lower(), int(s.get('uploaded', 0)))
                        for s in summaries if (s.get('hash_id') or s.get('hash'))
                    ]
                    if tor_rows:
                        cur.executemany("INSERT INTO torrent_snapshots (snapshot_id, hash_id, uploaded) VALUES (?, ?, ?)", tor_rows)
                    conn.commit()
                    return True
            except Exception as e:
                write_error_log("Ошибка записи record_snapshot в SQLite", e)
                return False

    def downsample_old_snapshots(self):
        now = time.time()
        cutoff_hourly = now - (31 * 86400)
        cutoff_daily = now - (365 * 86400)

        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, timestamp, datetime FROM snapshots WHERE timestamp < ? ORDER BY timestamp ASC", (cutoff_hourly,))
                    rows = cur.fetchall()
                    if not rows:
                        return 0

                    buckets = {}
                    for r in rows:
                        ts = r['timestamp']
                        dt_str = r['datetime'] or datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
                        key = ('day', dt_str[:10]) if ts < cutoff_daily else ('hour', dt_str[:13])
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
        latest_snap = prev_snap = snap_1h = snap_24h = None
        snap_1h_torrents, snap_24h_torrents = {}, {}

        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, timestamp, total_uploaded FROM snapshots WHERE COALESCE(ignore_in_stats, 0) = 0 ORDER BY timestamp DESC LIMIT 2")
                    last_rows = cur.fetchall()
                    if last_rows:
                        latest_snap = dict(last_rows[0])
                        if len(last_rows) > 1:
                            prev_snap = dict(last_rows[1])

                    cur.execute("SELECT id, timestamp, total_uploaded FROM snapshots WHERE COALESCE(ignore_in_stats, 0) = 0 AND timestamp BETWEEN ? AND ? ORDER BY ABS((? - timestamp) - 3600) ASC LIMIT 1", (now_ts - 7200, now_ts - 1800, now_ts))
                    r_1h = cur.fetchone()
                    if r_1h:
                        snap_1h = dict(r_1h)
                        cur.execute("SELECT hash_id, uploaded FROM torrent_snapshots WHERE snapshot_id = ?", (snap_1h['id'],))
                        snap_1h_torrents = {row['hash_id']: row['uploaded'] for row in cur.fetchall()}

                    cur.execute("SELECT id, timestamp, total_uploaded FROM snapshots WHERE COALESCE(ignore_in_stats, 0) = 0 AND timestamp BETWEEN ? AND ? ORDER BY ABS((? - timestamp) - 86400) ASC LIMIT 1", (now_ts - 100000, now_ts - 72000, now_ts))
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
                    cur.execute("SELECT id, timestamp, datetime, total_uploaded, count FROM snapshots WHERE COALESCE(ignore_in_stats, 0) = 0 AND timestamp >= ? ORDER BY timestamp ASC", (since_ts,))
                    return [dict(r) for r in cur.fetchall()]
            except Exception as e:
                write_error_log("Ошибка get_snapshots_since из SQLite", e)
                return []

    def get_torrents_positive_deltas(self, since_ts, allowed_hashes=None):
        totals = {}
        allowed = {h.lower() for h in allowed_hashes} if allowed_hashes is not None else None
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT ts.hash_id, s.timestamp, ts.uploaded
                        FROM torrent_snapshots ts
                        JOIN snapshots s ON s.id = ts.snapshot_id
                        WHERE COALESCE(s.ignore_in_stats, 0) = 0 AND s.timestamp >= ?
                        ORDER BY ts.hash_id ASC, s.timestamp ASC
                    """, (since_ts,))
                    cur_hash = prev_up = prev_ts = None
                    for row in cur:
                        h = row['hash_id']
                        if allowed is not None and h not in allowed:
                            continue
                        up, ts = int(row['uploaded'] or 0), float(row['timestamp'] or 0)
                        if h != cur_hash:
                            cur_hash, prev_up, prev_ts = h, up, ts
                            continue
                        d, dt = up - prev_up, max(1.0, ts - prev_ts)
                        if d > 0:
                            bps = d / dt
                            if not ((bps > 1073741824) or (prev_up < 104857600 and d > 5368709120 and bps > 314572800)):
                                totals[h] = totals.get(h, 0) + d
                        prev_up, prev_ts = up, ts
            except Exception as e:
                write_error_log("Ошибка get_torrents_positive_deltas", e)
        return totals

    def get_snapshot_range_info(self):
        with self._lock:
            with self._get_connection() as conn:
                return conn.execute("SELECT COUNT(*), MIN(timestamp) FROM snapshots WHERE COALESCE(ignore_in_stats, 0) = 0").fetchone()

    def get_hist_delta(self, t_start, t_end, is_seedbox, t_hash_lower=''):
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT id, total_uploaded FROM snapshots WHERE COALESCE(ignore_in_stats, 0) = 0 ORDER BY ABS(timestamp - ?) ASC LIMIT 1", (t_start,))
                r1 = cur.fetchone()
                cur.execute("SELECT id, total_uploaded FROM snapshots WHERE COALESCE(ignore_in_stats, 0) = 0 ORDER BY ABS(timestamp - ?) ASC LIMIT 1", (t_end,))
                r2 = cur.fetchone()
                if not r1 or not r2:
                    return 0
                if is_seedbox:
                    return max(0, r2['total_uploaded'] - r1['total_uploaded'])
                u1_row = cur.execute("SELECT uploaded FROM torrent_snapshots WHERE snapshot_id = ? AND hash_id = ? LIMIT 1", (r1['id'], t_hash_lower)).fetchone()
                u2_row = cur.execute("SELECT uploaded FROM torrent_snapshots WHERE snapshot_id = ? AND hash_id = ? LIMIT 1", (r2['id'], t_hash_lower)).fetchone()
                return max(0, (u2_row['uploaded'] if u2_row else 0) - (u1_row['uploaded'] if u1_row else 0))

    def get_torrent_history_rows(self, t_hash, limit_hours=36):
        t_hash_lower = (t_hash or '').lower()
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.cursor()
                    if t_hash == 'all':
                        cur.execute("SELECT datetime, timestamp, total_uploaded AS uploaded FROM snapshots WHERE COALESCE(ignore_in_stats, 0) = 0 ORDER BY timestamp DESC LIMIT ?", (limit_hours,))
                    else:
                        cur.execute("SELECT s.datetime, s.timestamp, ts.uploaded FROM snapshots s JOIN torrent_snapshots ts ON s.id = ts.snapshot_id WHERE COALESCE(s.ignore_in_stats, 0) = 0 AND ts.hash_id = ? ORDER BY s.timestamp DESC LIMIT ?", (t_hash_lower, limit_hours))
                    return [dict(r) for r in cur.fetchall()]
            except Exception as e:
                write_error_log("Ошибка get_torrent_history_rows из SQLite", e)
                return []

    def get_torrent_window_bounds(self, t_hash, since_ts, until_ts):
        t_hash_lower = (t_hash or '').lower()
        with self._lock:
            try:
                with self._get_connection() as conn:
                    rows = conn.execute("SELECT s.timestamp, ts.uploaded FROM snapshots s JOIN torrent_snapshots ts ON s.id = ts.snapshot_id WHERE COALESCE(s.ignore_in_stats, 0) = 0 AND ts.hash_id = ? AND s.timestamp BETWEEN ? AND ? ORDER BY s.timestamp ASC", (t_hash_lower, since_ts, until_ts)).fetchall()
                    if not rows:
                        return None, None, 0
                    return (rows[0]['timestamp'], rows[0]['uploaded']), (rows[-1]['timestamp'], rows[-1]['uploaded']), len(rows)
            except Exception:
                return None, None, 0

    def get_available_snapshot_days(self, limit=90):
        with self._lock:
            try:
                with self._get_connection() as conn:
                    rows = conn.execute("SELECT DISTINCT substr(datetime, 1, 10) AS day FROM snapshots WHERE length(datetime) >= 10 ORDER BY day DESC LIMIT ?", (int(limit),)).fetchall()
                    return [r['day'] for r in rows if r['day']]
            except Exception:
                return []

    def get_snapshots_by_day_paginated(self, start_ts, end_ts, page=1, per_page=15):
        page, per_page = max(1, int(page)), max(1, min(100, int(per_page)))
        offset = (page - 1) * per_page
        with self._lock:
            try:
                with self._get_connection() as conn:
                    total = conn.execute("SELECT COUNT(*) FROM snapshots WHERE timestamp BETWEEN ? AND ?", (start_ts, end_ts)).fetchone()[0]
                    rows = conn.execute("SELECT id, timestamp, datetime, total_uploaded, total_size, count, COALESCE(ignore_in_stats, 0) AS ignore_in_stats FROM snapshots WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp DESC LIMIT ? OFFSET ?", (start_ts, end_ts, per_page, offset)).fetchall()
                    return {'items': [dict(r) for r in rows], 'total': total, 'page': page, 'per_page': per_page, 'total_pages': max(1, (total + per_page - 1) // per_page)}
            except Exception as e:
                write_error_log("Ошибка get_snapshots_by_day_paginated", e)
                return {'items': [], 'total': 0, 'page': 1, 'per_page': per_page, 'total_pages': 1}

    def get_snapshots_by_day_all(self, start_ts, end_ts):
        with self._lock:
            try:
                with self._get_connection() as conn:
                    rows = conn.execute("SELECT datetime, total_uploaded, total_size, count FROM snapshots WHERE COALESCE(ignore_in_stats, 0) = 0 AND timestamp BETWEEN ? AND ? ORDER BY timestamp ASC", (start_ts, end_ts)).fetchall()
                    return [dict(r) for r in rows]
            except Exception:
                return []