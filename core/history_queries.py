# core/history_queries.py
from utils.helpers import write_error_log


def query_snapshot_range_info(db):
    with db._lock:
        with db._get_connection() as conn:
            return conn.execute("SELECT COUNT(*), MIN(timestamp) FROM snapshots WHERE COALESCE(ignore_in_stats, 0) = 0").fetchone()


def query_hist_delta(db, t_start, t_end, is_seedbox, t_hash_lower=''):
    with db._lock:
        with db._get_connection() as conn:
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


def query_torrent_history_rows(db, t_hash, limit_hours=36):
    t_hash_lower = (t_hash or '').lower()
    with db._lock:
        try:
            with db._get_connection() as conn:
                cur = conn.cursor()
                if t_hash == 'all':
                    cur.execute("SELECT datetime, timestamp, total_uploaded AS uploaded FROM snapshots WHERE COALESCE(ignore_in_stats, 0) = 0 ORDER BY timestamp DESC LIMIT ?", (limit_hours,))
                else:
                    cur.execute("SELECT s.datetime, s.timestamp, ts.uploaded FROM snapshots s JOIN torrent_snapshots ts ON s.id = ts.snapshot_id WHERE COALESCE(s.ignore_in_stats, 0) = 0 AND ts.hash_id = ? ORDER BY s.timestamp DESC LIMIT ?", (t_hash_lower, limit_hours))
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            write_error_log("Ошибка get_torrent_history_rows из SQLite", e)
            return []


def query_torrent_window_bounds(db, t_hash, since_ts, until_ts):
    t_hash_lower = (t_hash or '').lower()
    with db._lock:
        try:
            with db._get_connection() as conn:
                rows = conn.execute("SELECT s.timestamp, ts.uploaded FROM snapshots s JOIN torrent_snapshots ts ON s.id = ts.snapshot_id WHERE COALESCE(s.ignore_in_stats, 0) = 0 AND ts.hash_id = ? AND s.timestamp BETWEEN ? AND ? ORDER BY s.timestamp ASC", (t_hash_lower, since_ts, until_ts)).fetchall()
                if not rows:
                    return None, None, 0
                return (rows[0]['timestamp'], rows[0]['uploaded']), (rows[-1]['timestamp'], rows[-1]['uploaded']), len(rows)
        except Exception:
            return None, None, 0


def query_available_snapshot_days(db, limit=90):
    with db._lock:
        try:
            with db._get_connection() as conn:
                rows = conn.execute("SELECT DISTINCT substr(datetime, 1, 10) AS day FROM snapshots WHERE length(datetime) >= 10 ORDER BY day DESC LIMIT ?", (int(limit),)).fetchall()
                return [r['day'] for r in rows if r['day']]
        except Exception:
            return []


def query_snapshots_by_day_paginated(db, start_ts, end_ts, page=1, per_page=15):
    page, per_page = max(1, int(page)), max(1, min(100, int(per_page)))
    offset = (page - 1) * per_page
    with db._lock:
        try:
            with db._get_connection() as conn:
                total = conn.execute("SELECT COUNT(*) FROM snapshots WHERE timestamp BETWEEN ? AND ?", (start_ts, end_ts)).fetchone()[0]
                rows = conn.execute("SELECT id, timestamp, datetime, total_uploaded, total_size, count, COALESCE(ignore_in_stats, 0) AS ignore_in_stats FROM snapshots WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp DESC LIMIT ? OFFSET ?", (start_ts, end_ts, per_page, offset)).fetchall()
                return {'items': [dict(r) for r in rows], 'total': total, 'page': page, 'per_page': per_page, 'total_pages': max(1, (total + per_page - 1) // per_page)}
        except Exception as e:
            write_error_log("Ошибка get_snapshots_by_day_paginated", e)
            return {'items': [], 'total': 0, 'page': 1, 'per_page': per_page, 'total_pages': 1}


def query_snapshots_by_day_all(db, start_ts, end_ts):
    with db._lock:
        try:
            with db._get_connection() as conn:
                rows = conn.execute("SELECT datetime, total_uploaded, total_size, count FROM snapshots WHERE COALESCE(ignore_in_stats, 0) = 0 AND timestamp BETWEEN ? AND ? ORDER BY timestamp ASC", (start_ts, end_ts)).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []