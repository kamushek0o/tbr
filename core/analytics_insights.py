# core/analytics_insights.py
import time
import datetime
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.config import cfg
from utils.helpers import format_file_size
from core.qb_api import get_torrent_peers, get_transfer_info
from core.scheduler import MIN_DELTA_SEC
from core.widget_service import build_detailed_speed_series

_CLIENTS_LOCK = threading.Lock()
_CLIENTS_CACHE = {'ts': 0.0, 'data': None}
_CLIENTS_TTL = 900.0
_ISP_TIERS_MBPS = (10, 20, 25, 30, 50, 75, 100, 150, 200, 250, 300, 500, 1000)


def fetch_torrent_peers_safe(ip, port, t_hash):
    if not port or not t_hash:
        return []
    raw = get_torrent_peers(ip, port, t_hash)
    peers = raw.get('peers') or {}
    if not isinstance(peers, dict):
        return []

    out = []
    for p in peers.values():
        if not isinstance(p, dict):
            continue
        up = int(p.get('up_speed', 0) or 0)
        dl = int(p.get('dl_speed', 0) or 0)
        prog = round(float(p.get('progress', 0.0) or 0.0) * 100.0, 1)
        out.append({
            'client': str(p.get('client') or 'Unknown').strip() or 'Unknown',
            'progress': prog,
            'up_speed': up,
            'up_speed_fmt': f"{format_file_size(up)}/s",
            'dl_speed': dl,
            'dl_speed_fmt': f"{format_file_size(dl)}/s",
            'flags': str(p.get('flags') or ''),
            'country_code': str(p.get('country_code') or '').upper()[:4]
        })
    out.sort(key=lambda x: x['up_speed'], reverse=True)
    return out


def _classify_peer_client(raw_client):
    low = str(raw_client or '').lower()
    if 'qbittorrent' in low:
        return 'qBittorrent'
    if 'transmission' in low:
        return 'Transmission'
    if 'utorrent' in low or 'µtorrent' in low:
        return 'uTorrent'
    if 'deluge' in low:
        return 'Deluge'
    if 'biglybt' in low:
        return 'BiglyBT'
    if 'aria2' in low:
        return 'Aria2'
    if 'tixati' in low:
        return 'Tixati'
    if 'vuze' in low or 'azureus' in low:
        return 'Vuze'
    if 'bittorrent' in low:
        return 'BitTorrent'
    if 'libtorrent' in low:
        return 'libtorrent'
    return 'Прочие'


def get_peer_clients_breakdown(ip, port, live, force=False):
    now = time.time()
    with _CLIENTS_LOCK:
        if not force and _CLIENTS_CACHE['data'] is not None and (now - _CLIENTS_CACHE['ts']) < _CLIENTS_TTL:
            return dict(_CLIENTS_CACHE['data'])

    if not port or not live:
        return {'labels': [], 'values': [], 'total_peers': 0, 'cached_at': int(now)}

    active_hashes = [
        h for h, inf in sorted(
            live.items(),
            key=lambda kv: int(kv[1].get('num_leechs', 0) or 0) + int(kv[1].get('num_seeds', 0) or 0),
            reverse=True
        )
        if int(inf.get('num_leechs', 0) or 0) + int(inf.get('num_seeds', 0) or 0) > 0
    ][:40]

    counts = {}
    total_peers = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(fetch_torrent_peers_safe, ip, port, h) for h in active_hashes]
        for fut in as_completed(futs):
            try:
                for p in fut.result():
                    fam = _classify_peer_client(p['client'])
                    counts[fam] = counts.get(fam, 0) + 1
                    total_peers += 1
            except Exception:
                pass

    sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    res = {
        'labels': [k for k, _ in sorted_items],
        'values': [v for _, v in sorted_items],
        'total_peers': total_peers,
        'cached_at': int(now)
    }
    with _CLIENTS_LOCK:
        _CLIENTS_CACHE['ts'] = now
        _CLIENTS_CACHE['data'] = dict(res)
    return res


def get_tracker_analytics(db, summaries, live=None, period='7d', allowed_hashes=None):
    per = period if period in ('7d', '30d', 'all') else '7d'
    live_lower = {k.lower(): v for k, v in (live or {}).items()}
    allowed = {h.lower() for h in allowed_hashes} if allowed_hashes is not None else None

    domain_by_hash = {}
    all_up_by_hash = {}
    for s in summaries:
        hl = (s.get('hash_id') or s.get('hash') or '').lower()
        if not hl or (allowed is not None and hl not in allowed):
            continue
        lv = live_lower.get(hl, {})
        tr_url = str(lv.get('tracker') or '').strip()
        if not tr_url and s.get('trackers'):
            tr_url = str(s['trackers'][0] or '').strip()
        host = urllib.parse.urlparse(tr_url).netloc.lower().split(':')[0] if tr_url else ''
        domain_by_hash[hl] = host or 'Без трекера / DHT'
        all_up_by_hash[hl] = int(lv.get('uploaded', s.get('uploaded', 0)) or 0)

    if per == 'all':
        vol_map = all_up_by_hash
    else:
        days = 30 if per == '30d' else 7
        vol_map = db.get_torrents_positive_deltas(time.time() - days * 86400, allowed_hashes=domain_by_hash.keys())

    by_domain = {}
    for hl, dom in domain_by_hash.items():
        val = int(vol_map.get(hl, 0) or 0)
        if val > 0:
            by_domain[dom] = by_domain.get(dom, 0) + val

    sorted_dom = sorted(by_domain.items(), key=lambda x: x[1], reverse=True)
    top = sorted_dom[:9]
    if len(sorted_dom) > 9:
        top.append(('Другие', sum(v for _, v in sorted_dom[9:])))

    return {
        'period': per,
        'labels': [k for k, _ in top],
        'values': [round(v / (1024 ** 3), 2) for _, v in top]
    }


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
                        WHERE timestamp >= ? AND length(datetime) >= 10
                    )
                    SELECT day, SUM(delta) AS up_bytes
                    FROM diffs
                    GROUP BY day
                    ORDER BY day ASC
                """, (since_ts,)).fetchall()
                for r in rows:
                    day_bytes[r['day']] = int(r['up_bytes'] or 0)
        except Exception:
            pass

    today = datetime.date.today()
    cells = []
    max_val = max(day_bytes.values(), default=0)
    for offset in range(364, -1, -1):
        d = today - datetime.timedelta(days=offset)
        ds = d.strftime('%Y-%m-%d')
        b = day_bytes.get(ds, 0)
        lvl = 0 if (b <= 0 or max_val <= 0) else (4 if (b / max_val) >= 0.75 else (3 if (b / max_val) >= 0.45 else (2 if (b / max_val) >= 0.15 else 1)))
        cells.append({'date': ds, 'weekday': d.weekday(), 'bytes': b, 'gb': round(b / (1024 ** 3), 2), 'fmt': format_file_size(b), 'level': lvl})
    return cells


def _sum_range_deltas(rows, start_ts, end_ts):
    total, prev = 0, None
    for r in rows:
        ts = float(r['timestamp'])
        if prev is not None and start_ts <= ts <= end_ts:
            dt = ts - float(prev['timestamp'])
            d = max(0, int(r['total_uploaded']) - int(prev['total_uploaded']))
            if dt >= MIN_DELTA_SEC and d > 0:
                total += d
        prev = r
    return total


def get_records_and_comparisons(db, heatmap_cells=None, force_recalc=False):
    now_dt = datetime.datetime.now()
    now_ts = now_dt.timestamp()

    # Начало сегодняшних суток и симметричный отрезок вчера (до той же секунды)
    today_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    yest_start = today_start - 86400
    yest_same_end = now_ts - 86400

    # Начало текущей недели (понедельник 00:00) и симметричный отрезок прошлой недели
    week_start = (now_dt - datetime.timedelta(days=now_dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    prev_week_start = week_start - (7 * 86400)
    prev_week_same_end = now_ts - (7 * 86400)

    _, min_ts = db.get_snapshot_range_info()
    rows_15d = db.get_snapshots_since(prev_week_start - 3600)

    # Честный Like-for-Like расчёт
    today_b = _sum_range_deltas(rows_15d, today_start, now_ts)
    yest_b = _sum_range_deltas(rows_15d, yest_start, yest_same_end)
    this_w_b = _sum_range_deltas(rows_15d, week_start, now_ts)
    prev_w_b = _sum_range_deltas(rows_15d, prev_week_start, prev_week_same_end)

    day_pct = round(((today_b - yest_b) / yest_b) * 100.0, 1) if (min_ts and min_ts <= yest_start + 3600 and yest_b > 0) else None
    week_pct = round(((this_w_b - prev_w_b) / prev_w_b) * 100.0, 1) if (min_ts and min_ts <= prev_week_start + 3600 and prev_w_b > 0) else None

    # Порог канала для отсечения аномальных пиков
    max_mbps = max(10, cfg.getint('Max_Channel_Mbps', 1000))
    max_physical_bps = (max_mbps * 1024 * 1024) / 8.0

    all_rows = db.get_snapshots_since(0)
    peak_bps, peak_date, prev_r = 0.0, '—', None
    for r in all_rows:
        if prev_r is not None:
            dt = float(r['timestamp']) - float(prev_r['timestamp'])
            d = max(0, int(r['total_uploaded']) - int(prev_r['total_uploaded']))
            if dt >= MIN_DELTA_SEC and d > 0:
                bps = d / dt
                if bps <= max_physical_bps and bps > peak_bps:
                    peak_bps = bps
                    dt_raw = str(r.get('datetime') or '').replace('|', '').strip()
                    peak_date = dt_raw[:16] if dt_raw else '—'
        prev_r = r

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