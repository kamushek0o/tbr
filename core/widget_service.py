# core/widget_service.py
import io
import time
import datetime
from PIL import Image, ImageDraw, ImageFont
from utils.config import cfg
from utils.helpers import format_file_size
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info, is_qb_running
from core.torrent_parser import get_all_torrents
from core.scheduler import MIN_DELTA_SEC
from core.disk_monitor import get_monitored_disk_info
from core.private_vault import get_hidden_hashes, get_vault_settings

_ICON_CACHE = {}
PERIOD_DAYS = {'1d': 1, '7d': 7, '30d': 30}


def _smooth_anomalies(points):
    if len(points) >= 3:
        for i in range(1, len(points) - 1):
            p_prev, p_cur, p_next = points[i - 1]['speed_mbs'], points[i]['speed_mbs'], points[i + 1]['speed_mbs']
            avg_n = (p_prev + p_next) / 2.0
            if p_cur > 15.0 and p_cur > (avg_n * 5.0):
                points[i]['speed_mbs'] = round(avg_n, 3)
                points[i]['speed_bps'] = round(avg_n * 1024 * 1024, 2)
                points[i]['delta_bytes'] = int(points[i]['speed_bps'] * points[i]['dt_sec'])
                points[i]['delta_fmt'] = format_file_size(points[i]['delta_bytes'])
    return points


def build_detailed_speed_series(db, hours=24):
    since_ts = time.time() - (max(1, int(hours)) * 3600)
    rows = db.get_snapshots_since(since_ts)
    points, prev = [], None
    for r in rows:
        if prev is not None:
            t1, t2 = float(prev['timestamp']), float(r['timestamp'])
            dt_sec = t2 - t1
            if dt_sec >= MIN_DELTA_SEC:
                delta = max(0, int(r['total_uploaded']) - int(prev['total_uploaded']))
                bps = delta / dt_sec
                if int(r.get('count', 0) or 0) > int(prev.get('count', 0) or 0) and bps > (200 * 1024 * 1024):
                    bps = points[-1]['speed_bps'] if points else 0.0
                dt_obj = datetime.datetime.fromtimestamp(t2)
                points.append({
                    'ts': int(t2),
                    'label': dt_obj.strftime('%H:%M') if hours <= 24 else dt_obj.strftime('%d.%m %H:%M'),
                    'speed_bps': round(bps, 2),
                    'speed_mbs': round(bps / (1024 * 1024), 3),
                    'delta_bytes': delta,
                    'delta_fmt': format_file_size(delta),
                    'dt_sec': int(dt_sec),
                    'interval_min': int(round(dt_sec / 60.0))
                })
        prev = r
    return _smooth_anomalies(points)


def build_hourly_aggregated_speed_series(db, hours=72):
    since_ts = time.time() - (max(24, int(hours)) * 3600)
    rows = db.get_snapshots_since(since_ts)
    buckets, prev = {}, None
    for r in rows:
        if prev is not None:
            t1, t2 = float(prev['timestamp']), float(r['timestamp'])
            dt_sec = t2 - t1
            delta = max(0, int(r['total_uploaded']) - int(prev['total_uploaded']))
            if dt_sec >= MIN_DELTA_SEC and delta > 0:
                if int(r.get('count', 0) or 0) > int(prev.get('count', 0) or 0) and (delta / dt_sec) > (200 * 1024 * 1024):
                    delta = 0
                cur_ts = datetime.datetime.fromtimestamp(t1).replace(minute=0, second=0, microsecond=0).timestamp()
                while cur_ts < t2:
                    b_end = cur_ts + 3600.0
                    overlap = min(t2, b_end) - max(t1, cur_ts)
                    if overlap > 0:
                        b = buckets.setdefault(int(cur_ts), {'bytes': 0.0, 'sec': 0.0})
                        b['bytes'] += delta * (overlap / dt_sec)
                        b['sec'] += overlap
                    cur_ts = b_end
        prev = r

    points = []
    for h_ts in sorted(buckets.keys()):
        b = buckets[h_ts]
        sec = max(1.0, b['sec'])
        bps = b['bytes'] / sec
        delta_i = int(b['bytes'])
        points.append({
            'ts': h_ts,
            'label': datetime.datetime.fromtimestamp(h_ts).strftime('%d.%m %H:00'),
            'speed_bps': round(bps, 2),
            'speed_mbs': round(bps / (1024 * 1024), 3),
            'delta_bytes': delta_i,
            'delta_fmt': format_file_size(delta_i),
            'dt_sec': int(sec),
            'interval_min': int(round(sec / 60.0))
        })
    return _smooth_anomalies(points)


def compute_top_n_torrents(db, summaries, live=None, top_n=5, period='1d', with_others=False):
    n = max(1, min(25, int(top_n or 5)))
    per = period if period in ('1d', '7d', '30d', 'all') else '1d'

    active_map = {}
    if live:
        by_hash = {(s.get('hash_id') or '').lower(): s for s in summaries}
        for h_raw, info in live.items():
            h = h_raw.lower()
            st_name = (by_hash.get(h) or {}).get('name', '')
            nm = str(info.get('name') or st_name or h)
            active_map[h] = {'name': nm, 'uploaded': int(info.get('uploaded', 0) or 0)}
    else:
        for s in summaries:
            h = (s.get('hash_id') or s.get('hash') or '').lower()
            if h:
                active_map[h] = {'name': str(s.get('name') or h), 'uploaded': int(s.get('uploaded', 0) or 0)}

    if not active_map:
        return ([], {'gb': 0.0, 'count': 0}) if with_others else []

    if per == 'all':
        scored = [(h, v['name'], v['uploaded']) for h, v in active_map.items() if v['uploaded'] > 0]
    else:
        since_ts = time.time() - (PERIOD_DAYS[per] * 86400)
        deltas = db.get_torrents_positive_deltas(since_ts, allowed_hashes=active_map.keys())
        scored = [(h, active_map[h]['name'], deltas.get(h, 0)) for h in active_map if deltas.get(h, 0) > 0]

    scored.sort(key=lambda x: x[2], reverse=True)
    prec = 3 if per != 'all' else 2
    top_items = [
        {'hash': h, 'full_name': nm, 'short_name': (nm[:26] + '…') if len(nm) > 27 else nm, 'gb': round(val / (1024 ** 3), prec)}
        for h, nm, val in scored[:n]
    ]
    if not with_others:
        return top_items

    rest = scored[n:]
    rest_bytes = max(0, sum(x[2] for x in rest))
    others = {'gb': round(rest_bytes / (1024 ** 3), prec), 'count': len(rest)}
    return top_items, others


def get_widget_summary(db, ui_settings=None, top_period=None, top_scale=None, role='admin'):
    now_ts = time.time()
    torrents = list(get_all_torrents(use_cache=True).values())
    ip, port = detect_qbittorrent_port(cfg.config)
    qb_up = is_qb_running()
    live = get_live_torrent_info(ip, port) if (qb_up and port) else {}

    hidden = get_hidden_hashes(live) if role != 'admin' else set()
    vault_mode = get_vault_settings().get('aggregate_mode', 'exclude') if hidden else 'anonymize'

    vis_live = {h: v for h, v in live.items() if h.lower() not in hidden} if hidden else live
    vis_torrents = [t for t in torrents if (t.get('hash_id') or '').lower() not in hidden] if hidden else torrents

    agg_live = vis_live if (hidden and vault_mode == 'exclude') else live
    agg_torrents = vis_torrents if (hidden and vault_mode == 'exclude') else torrents

    if agg_live:
        total_uploaded = sum(int(t.get('uploaded', 0) or 0) for t in agg_live.values())
        cur_bps = sum(int(t.get('upspeed', 0) or 0) for t in agg_live.values())
        active_cnt = sum(1 for t in agg_live.values() if str(t.get('state', '')).lower() not in ('pausedup', 'pauseddl', 'stoppedup', 'stoppeddl', 'error', 'missingfiles'))
        total_cnt = len(agg_live)
    else:
        total_uploaded = sum(int(t.get('uploaded', 0) or 0) for t in agg_torrents)
        active_cnt, total_cnt = len(agg_torrents), len(agg_torrents)
        s6 = build_detailed_speed_series(db, hours=6)
        cur_bps = s6[-1]['speed_bps'] if s6 else 0.0

    rows_24h = db.get_snapshots_since(now_ts - 86400)
    up_24h = max(0, total_uploaded - int(rows_24h[0]['total_uploaded'])) if rows_24h else 0
    midnight_ts = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    rows_today = db.get_snapshots_since(midnight_ts)
    up_today = max(0, total_uploaded - int(rows_today[0]['total_uploaded'])) if rows_today else 0

    ch_cfg = (ui_settings or {}).get('charts') or {}
    per = top_period or ch_cfg.get('top_period', '1d')
    scale = top_scale or ch_cfg.get('top_scale', 'lin')
    if per not in ('1d', '7d', '30d', 'all'):
        per = '1d'
    if scale not in ('lin', 'log10'):
        scale = 'lin'

    speed_pts = build_detailed_speed_series(db, hours=24)
    if len(speed_pts) > 48:
        speed_pts = speed_pts[::max(1, len(speed_pts) // 48)]

    rows_7d = db.get_snapshots_since(now_ts - 7 * 86400)
    daily_map, prev_r = {}, None
    for r in rows_7d:
        if prev_r is not None:
            dt = float(r['timestamp']) - float(prev_r['timestamp'])
            delta = max(0, int(r['total_uploaded']) - int(prev_r['total_uploaded']))
            if dt >= MIN_DELTA_SEC and delta > 0:
                dk = datetime.datetime.fromtimestamp(r['timestamp']).strftime('%d.%m')
                daily_map[dk] = daily_map.get(dk, 0.0) + delta / (1024 ** 3)
        prev_r = r

    # В Топ-5 никогда не раскрываем названия скрытых раздач Private Vault
    top_items = compute_top_n_torrents(db, vis_torrents, live=vis_live, top_n=5, period=per)
    disk = get_monitored_disk_info(live)

    return {
        'qb_running': qb_up, 'total_torrents': total_cnt, 'active_torrents': active_cnt,
        'current_speed_bps': int(cur_bps), 'current_speed_fmt': f"{format_file_size(cur_bps)}/s",
        'uploaded_24h_bytes': up_24h, 'uploaded_24h_fmt': format_file_size(up_24h),
        'uploaded_today_bytes': up_today, 'uploaded_today_fmt': format_file_size(up_today),
        'total_uploaded_bytes': total_uploaded, 'total_uploaded_fmt': format_file_size(total_uploaded),
        'disk_free_bytes': disk.get('free_bytes', 0), 'disk_free_fmt': disk.get('free_fmt', '0 B'),
        'timestamp': int(now_ts),
        'charts': {
            'top_period': per, 'top_scale': scale,
            'speed_24h': [{'label': p['label'], 'speed_mbs': p['speed_mbs']} for p in speed_pts],
            'daily_7d': [{'label': k, 'gb': round(v, 2)} for k, v in list(daily_map.items())[-7:]],
            'top_5': [{'name': x['full_name'][:40], 'gb': x['gb']} for x in top_items]
        }
    }


def render_widget_chart_png(db, ui_settings, hours=24, width=560, height=200, chart_type='speed'):
    w, h = max(240, min(1200, int(width))), max(100, min(600, int(height)))
    img = Image.new('RGB', (w, h), (26, 26, 32))
    draw = ImageDraw.Draw(img)
    series = build_detailed_speed_series(db, hours=hours)
    if len(series) >= 2:
        t_min, t_span = series[0]['ts'], max(1, series[-1]['ts'] - series[0]['ts'])
        v_max = max(max(p['speed_mbs'] for p in series), 0.1)
        pts = [(14 + int(((p['ts'] - t_min) / t_span) * (w - 28)), h - 18 - int((p['speed_mbs'] / v_max) * (h - 36))) for p in series]
        draw.line(pts, fill=(52, 152, 219), width=2)
    else:
        draw.text((20, h // 2 - 6), "No data", fill=(149, 165, 166), font=ImageFont.load_default())
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def get_pwa_icon_png(size=192):
    sz = int(size)
    if sz in _ICON_CACHE:
        return _ICON_CACHE[sz]
    img = Image.new('RGBA', (sz, sz), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, sz - 1, sz - 1], radius=max(8, sz // 5), fill=(26, 26, 32, 255))
    s = sz / 48.0
    draw.polygon([(26 * s, 6 * s), (12 * s, 26 * s), (24 * s, 26 * s), (20 * s, 42 * s), (36 * s, 22 * s), (24 * s, 22 * s)], fill=(46, 204, 113, 255))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    _ICON_CACHE[sz] = buf.getvalue()
    return _ICON_CACHE[sz]