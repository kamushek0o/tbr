# core/records_service.py
import time
import datetime
from utils.config import cfg
from utils.helpers import format_file_size, write_error_log
from core.qb_api import get_transfer_info
from core.scheduler import MIN_DELTA_SEC
from core.widget_service import build_detailed_speed_series
from core.app_state_db import app_state_db

_ISP_TIERS_MBPS = (10, 20, 25, 30, 50, 75, 100, 150, 200, 250, 300, 500, 1000)


def _ensure_records_table():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS records_state (
                        id INTEGER PRIMARY KEY CHECK(id = 1),
                        peak_speed_bps REAL NOT NULL DEFAULT 0,
                        peak_speed_date TEXT NOT NULL DEFAULT '—',
                        peak_snapshot_id INTEGER,
                        updated_at REAL NOT NULL DEFAULT 0
                    )
                """)
        except Exception as e:
            write_error_log("records_state init", e)


_ensure_records_table()


def get_heatmap_365(db):
    since_ts = time.time() - (365 * 86400)
    day_bytes = {}
    with db._lock:
        try:
            with db._get_connection() as conn:
                rows = conn.execute("""
                    WITH diffs AS (
                        SELECT substr(datetime, 1, 10) AS day,
                               MAX(0, total_uploaded - LAG(total_uploaded, 1, total_uploaded) OVER (ORDER BY timestamp ASC)) AS delta
                        FROM snapshots
                        WHERE COALESCE(ignore_in_stats, 0) = 0 AND timestamp >= ? AND length(datetime) >= 10
                    )
                    SELECT day, SUM(delta) AS up_bytes FROM diffs GROUP BY day ORDER BY day ASC
                """, (since_ts,)).fetchall()
                for r in rows:
                    day_bytes[r['day']] = int(r['up_bytes'] or 0)
        except Exception:
            pass

    today = datetime.date.today()
    cells, max_val = [], max(day_bytes.values(), default=0)
    for offset in range(364, -1, -1):
        d = today - datetime.timedelta(days=offset)
        ds = d.strftime('%Y-%m-%d')
        b = day_bytes.get(ds, 0)
        lvl = 0 if (b <= 0 or max_val <= 0) else (4 if (b / max_val) >= 0.75 else (3 if (b / max_val) >= 0.45 else (2 if (b / max_val) >= 0.15 else 1)))
        cells.append({'date': ds, 'weekday': d.weekday(), 'bytes': b, 'gb': round(b / (1024 ** 3), 2), 'fmt': format_file_size(b), 'level': lvl})
    return cells


def _sum_range_deltas(rows, start_ts, end_ts, max_physical_bps=None):
    total, prev = 0, None
    for r in rows:
        ts = float(r['timestamp'])
        if prev is not None and start_ts <= ts <= end_ts:
            dt = ts - float(prev['timestamp'])
            d = max(0, int(r['total_uploaded']) - int(prev['total_uploaded']))
            if dt >= MIN_DELTA_SEC and d > 0:
                if max_physical_bps is None or (d / dt) <= max_physical_bps:
                    total += d
        prev = r
    return total


def _recompute_and_save_peak(db):
    max_mbps = max(10, cfg.getint('Max_Channel_Mbps', 1000))
    max_physical_bps = ((max_mbps * 1_000_000) / 8.0) * 1.05
    all_rows = db.get_snapshots_since(0)
    peak_bps, peak_date, peak_snap_id, prev_r = 0.0, '—', None, None

    for r in all_rows:
        if prev_r is not None:
            dt = float(r['timestamp']) - float(prev_r['timestamp'])
            d = max(0, int(r['total_uploaded']) - int(prev_r['total_uploaded']))
            if dt >= MIN_DELTA_SEC and d > 0:
                bps = d / dt
                if bps <= max_physical_bps and bps > peak_bps:
                    peak_bps = bps
                    peak_snap_id = r.get('id')
                    dt_raw = str(r.get('datetime') or '').replace('|', '').strip()
                    peak_date = dt_raw[:16] if dt_raw else '—'
        prev_r = r

    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO records_state
                       (id, peak_speed_bps, peak_speed_date, peak_snapshot_id, updated_at)
                       VALUES (1, ?, ?, ?, ?)""",
                    (peak_bps, peak_date, peak_snap_id, time.time())
                )
        except Exception as e:
            write_error_log("save records_state", e)
    return peak_bps, peak_date, peak_snap_id


def get_records_and_comparisons(db, heatmap_cells=None, force_recalc=False):
    now_dt = datetime.datetime.now()
    now_ts = now_dt.timestamp()
    today_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    yest_start, yest_same_end = today_start - 86400, now_ts - 86400
    week_start = (now_dt - datetime.timedelta(days=now_dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    prev_week_start, prev_week_same_end = week_start - (7 * 86400), now_ts - (7 * 86400)

    max_mbps = max(10, cfg.getint('Max_Channel_Mbps', 1000))
    max_physical_bps = ((max_mbps * 1_000_000) / 8.0) * 1.05

    _, min_ts = db.get_snapshot_range_info()
    rows_15d = db.get_snapshots_since(prev_week_start - 3600)
    today_b = _sum_range_deltas(rows_15d, today_start, now_ts, max_physical_bps)
    yest_b = _sum_range_deltas(rows_15d, yest_start, yest_same_end, max_physical_bps)
    this_w_b = _sum_range_deltas(rows_15d, week_start, now_ts, max_physical_bps)
    prev_w_b = _sum_range_deltas(rows_15d, prev_week_start, prev_week_same_end, max_physical_bps)

    day_pct = round(((today_b - yest_b) / yest_b) * 100.0, 1) if (min_ts and min_ts <= yest_start + 3600 and yest_b > 0) else None
    week_pct = round(((this_w_b - prev_w_b) / prev_w_b) * 100.0, 1) if (min_ts and min_ts <= prev_week_start + 3600 and prev_w_b > 0) else None

    if force_recalc:
        peak_bps, peak_date, peak_snap_id = _recompute_and_save_peak(db)
    else:
        saved = None
        with app_state_db._lock:
            try:
                with app_state_db._get_conn() as conn:
                    saved = conn.execute("SELECT * FROM records_state WHERE id = 1").fetchone()
            except Exception:
                pass
        if saved:
            peak_bps = float(saved['peak_speed_bps'] or 0.0)
            peak_date = str(saved['peak_speed_date'] or '—')
            peak_snap_id = saved['peak_snapshot_id']
        else:
            peak_bps, peak_date, peak_snap_id = _recompute_and_save_peak(db)

    cells = heatmap_cells if heatmap_cells is not None else get_heatmap_365(db)
    best_cell = max(cells, key=lambda c: c['bytes'], default=None)

    return {
        'today_fmt': format_file_size(today_b),
        'yesterday_fmt': format_file_size(yest_b) if (min_ts and min_ts <= yest_start + 3600) else '—',
        'day_pct': day_pct,
        'this_week_fmt': format_file_size(this_w_b),
        'prev_week_fmt': format_file_size(prev_w_b) if (min_ts and min_ts <= prev_week_start + 3600) else '—',
        'week_pct': week_pct,
        'peak_speed_fmt': f"{format_file_size(peak_bps)}/s" if peak_bps > 0 else '—',
        'peak_speed_date': peak_date,
        'peak_snapshot_id': peak_snap_id,
        'best_day_fmt': best_cell['fmt'] if (best_cell and best_cell['bytes'] > 0) else '—',
        'best_day_date': best_cell['date'] if (best_cell and best_cell['bytes'] > 0) else '—',
    }


def detect_isp_throttling(db, ip, port):
    if port:
        tr = get_transfer_info(ip, port)
        if int(tr.get('up_rate_limit') or 0) > 0:
            return {'throttled': False, 'reason': 'qb_limit_set'}
    pts = build_detailed_speed_series(db, hours=48)
    active = sorted([p['speed_mbs'] for p in pts if p['speed_mbs'] >= 1.0], reverse=True)
    if len(active) < 8:
        return {'throttled': False}
    top_slice = active[:6]
    hi, lo = top_slice[0], top_slice[-1]
    if hi < 1.0 or ((hi - lo) / hi) > 0.08:
        return {'throttled': False}
    avg_mbs = sum(top_slice) / len(top_slice)
    avg_mbps = (avg_mbs * 1024 * 1024 * 8) / 1_000_000.0
    for tier in _ISP_TIERS_MBPS:
        if abs(avg_mbps - tier) / tier <= 0.12:
            return {'throttled': True, 'tier_mbps': tier, 'plateau_mbs': round(avg_mbs, 2)}
    return {'throttled': False}