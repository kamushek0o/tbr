# core/widget_service.py
import io
import os
import time
import shutil
import datetime
from PIL import Image, ImageDraw, ImageFont
from utils.config import cfg
from utils.helpers import BT_BACKUP_PATH, APP_DATA_DIR, format_file_size
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info, is_qb_running
from core.torrent_parser import get_all_torrents
from core.scheduler import MIN_DELTA_SEC

_ICON_CACHE = {}


def _smooth_anomalies(points):
    if len(points) >= 3:
        for i in range(1, len(points) - 1):
            p_prev = points[i - 1]['speed_mbs']
            p_cur = points[i]['speed_mbs']
            p_next = points[i + 1]['speed_mbs']
            avg_neighbor = (p_prev + p_next) / 2.0
            if p_cur > 15.0 and p_cur > (avg_neighbor * 5.0):
                points[i]['speed_mbs'] = round(avg_neighbor, 3)
                points[i]['speed_bps'] = round(avg_neighbor * 1024 * 1024, 2)
                dt = points[i]['dt_sec']
                points[i]['delta_bytes'] = int(points[i]['speed_bps'] * dt)
                points[i]['delta_fmt'] = format_file_size(points[i]['delta_bytes'])
    return points


def build_detailed_speed_series(db, hours=24):
    now_ts = time.time()
    since_ts = now_ts - (max(1, int(hours)) * 3600)
    rows = db.get_snapshots_since(since_ts)
    points = []
    prev = None

    for r in rows:
        if prev is not None:
            t1, t2 = float(prev['timestamp']), float(r['timestamp'])
            dt_sec = t2 - t1
            if dt_sec >= MIN_DELTA_SEC:
                delta = max(0, int(r['total_uploaded']) - int(prev['total_uploaded']))
                bps = delta / dt_sec
                prev_cnt = int(prev.get('count', 0) or 0)
                cur_cnt = int(r.get('count', 0) or 0)
                if cur_cnt > prev_cnt and bps > (200 * 1024 * 1024):
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
    now_ts = time.time()
    since_ts = now_ts - (max(24, int(hours)) * 3600)
    rows = db.get_snapshots_since(since_ts)
    buckets = {}
    prev = None

    for r in rows:
        if prev is not None:
            t1, t2 = float(prev['timestamp']), float(r['timestamp'])
            dt_sec = t2 - t1
            delta = max(0, int(r['total_uploaded']) - int(prev['total_uploaded']))
            prev_cnt = int(prev.get('count', 0) or 0)
            cur_cnt = int(r.get('count', 0) or 0)
            if dt_sec >= MIN_DELTA_SEC and delta > 0:
                if cur_cnt > prev_cnt and (delta / dt_sec) > (200 * 1024 * 1024):
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
        dt_obj = datetime.datetime.fromtimestamp(h_ts)
        points.append({
            'ts': h_ts,
            'label': dt_obj.strftime('%d.%m %H:00'),
            'speed_bps': round(bps, 2),
            'speed_mbs': round(bps / (1024 * 1024), 3),
            'delta_bytes': delta_i,
            'delta_fmt': format_file_size(delta_i),
            'dt_sec': int(sec),
            'interval_min': int(round(sec / 60.0))
        })
    return _smooth_anomalies(points)


def _get_disk_free_bytes(live_info):
    candidates = []
    if live_info:
        for info in live_info.values():
            sp = info.get('save_path')
            if sp and os.path.exists(sp):
                candidates.append(sp)
                break
    candidates.extend([BT_BACKUP_PATH, APP_DATA_DIR])
    for path in candidates:
        try:
            if path and os.path.exists(path):
                return shutil.disk_usage(path).free
        except Exception:
            continue
    return 0


def _build_widget_charts_json(db, torrents, live):
    now_ts = time.time()
    speed_pts = build_detailed_speed_series(db, hours=24)
    if len(speed_pts) > 48:
        step = max(1, len(speed_pts) // 48)
        speed_pts = speed_pts[::step]

    rows_7d = db.get_snapshots_since(now_ts - 7 * 86400)
    daily_map = {}
    prev_r = None
    for r in rows_7d:
        if prev_r is not None:
            dt = float(r['timestamp']) - float(prev_r['timestamp'])
            delta = max(0, int(r['total_uploaded']) - int(prev_r['total_uploaded']))
            if dt >= MIN_DELTA_SEC and delta > 0:
                dk = datetime.datetime.fromtimestamp(r['timestamp']).strftime('%d.%m')
                daily_map[dk] = daily_map.get(dk, 0.0) + delta / (1024 ** 3)
        prev_r = r

    oldest_24h = db.get_oldest_torrents_since(now_ts - 86400)
    top_src = []
    for t in torrents:
        h = (t.get('hash_id') or '').lower()
        up = int((live.get(h) or {}).get('uploaded', t.get('uploaded', 0)) or 0)
        d24 = max(0, up - oldest_24h[h]) if h in oldest_24h else 0
        top_src.append({'name': str(t.get('name', h)), 'd24': d24, 'up': up})

    use_24 = any(x['d24'] > 0 for x in top_src)
    top_src.sort(key=lambda x: x['d24'] if use_24 else x['up'], reverse=True)
    top_5 = [
        {'name': x['name'][:40], 'gb': round((x['d24'] if use_24 else x['up']) / (1024 ** 3), 2)}
        for x in top_src[:5] if (x['d24'] if use_24 else x['up']) > 0
    ]

    return {
        'speed_24h': [{'label': p['label'], 'speed_mbs': p['speed_mbs']} for p in speed_pts],
        'daily_7d': [{'label': k, 'gb': round(v, 2)} for k, v in list(daily_map.items())[-7:]],
        'top_5': top_5
    }


def get_widget_summary(db):
    now_ts = time.time()
    torrents = list(get_all_torrents(use_cache=True).values())
    ip, port = detect_qbittorrent_port(cfg.config)
    qb_up = is_qb_running()
    live = get_live_torrent_info(ip, port) if (qb_up and port) else {}

    if live:
        total_uploaded = sum(int(t.get('uploaded', 0) or 0) for t in live.values())
        cur_bps = sum(int(t.get('upspeed', 0) or 0) for t in live.values())
        active_cnt = sum(1 for t in live.values() if str(t.get('state', '')).lower() not in ('pausedup', 'pauseddl', 'stoppedup', 'stoppeddl', 'error', 'missingfiles'))
        total_cnt = len(live)
    else:
        total_uploaded = sum(int(t.get('uploaded', 0) or 0) for t in torrents)
        active_cnt = len(torrents)
        total_cnt = len(torrents)
        series = build_detailed_speed_series(db, hours=6)
        cur_bps = series[-1]['speed_bps'] if series else 0.0

    rows_24h = db.get_snapshots_since(now_ts - 86400)
    up_24h = max(0, total_uploaded - int(rows_24h[0]['total_uploaded'])) if rows_24h else 0
    midnight_ts = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    rows_today = db.get_snapshots_since(midnight_ts)
    up_today = max(0, total_uploaded - int(rows_today[0]['total_uploaded'])) if rows_today else 0
    free_bytes = _get_disk_free_bytes(live)

    return {
        'qb_running': qb_up,
        'total_torrents': total_cnt,
        'active_torrents': active_cnt,
        'current_speed_bps': int(cur_bps),
        'current_speed_fmt': f"{format_file_size(cur_bps)}/s",
        'uploaded_24h_bytes': up_24h,
        'uploaded_24h_fmt': format_file_size(up_24h),
        'uploaded_today_bytes': up_today,
        'uploaded_today_fmt': format_file_size(up_today),
        'total_uploaded_bytes': total_uploaded,
        'total_uploaded_fmt': format_file_size(total_uploaded),
        'disk_free_bytes': free_bytes,
        'disk_free_fmt': format_file_size(free_bytes),
        'timestamp': int(now_ts),
        'charts': _build_widget_charts_json(db, torrents, live)
    }


def _hex_rgb(hex_str, default=(46, 204, 113)):
    s = str(hex_str or '').strip().lstrip('#')
    if len(s) == 6:
        try:
            return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    return default


def render_widget_chart_png(db, ui_settings, hours=24, width=560, height=200, chart_type='speed'):
    w, h = max(240, min(1200, int(width))), max(100, min(600, int(height)))
    scale = 2
    sw, sh = w * scale, h * scale
    bg_c, grid_c, txt_c = (26, 26, 32), (45, 45, 56), (149, 165, 166)
    ch_cfg = ((ui_settings or {}).get('charts') or {}).get('hourly') or {}
    line_c = _hex_rgb(ch_cfg.get('color'), (52, 152, 219))

    img = Image.new('RGBA', (sw, sh), bg_c + (255,))
    draw = ImageDraw.Draw(img, 'RGBA')
    font = ImageFont.load_default()
    pad_l, pad_r, pad_t, pad_b = 18 * scale, 14 * scale, 18 * scale, 22 * scale
    plot_w, plot_h = max(10, sw - pad_l - pad_r), max(10, sh - pad_t - pad_b)

    for i in range(4):
        gy = pad_t + int(plot_h * (i / 3.0))
        draw.line([(pad_l, gy), (sw - pad_r, gy)], fill=grid_c + (255,), width=1 * scale)

    series = build_detailed_speed_series(db, hours=hours)
    if len(series) < 2:
        draw.text((pad_l + 10, sh // 2 - 8), "No data", fill=txt_c + (255,), font=font)
    else:
        t_min, t_max = series[0]['ts'], series[-1]['ts']
        t_span = max(1, t_max - t_min)
        v_max = max(max(p['speed_mbs'] for p in series), 0.1)
        pts = [(pad_l + int(((p['ts'] - t_min) / t_span) * plot_w), pad_t + plot_h - int((p['speed_mbs'] / v_max) * plot_h)) for p in series]
        draw.polygon([(pts[0][0], pad_t + plot_h)] + pts + [(pts[-1][0], pad_t + plot_h)], fill=line_c + (55,))
        draw.line(pts, fill=line_c + (255,), width=2 * scale, joint='curve')

    out = img.resize((w, h), Image.Resampling.LANCZOS).convert('RGB')
    buf = io.BytesIO()
    out.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def get_pwa_icon_png(size=192):
    sz = int(size)
    if sz in _ICON_CACHE:
        return _ICON_CACHE[sz]
    img = Image.new('RGBA', (sz, sz), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, sz - 1, sz - 1], radius=max(8, sz // 5), fill=(26, 26, 32, 255))
    s = sz / 48.0
    bolt = [(26 * s, 6 * s), (12 * s, 26 * s), (24 * s, 26 * s), (20 * s, 42 * s), (36 * s, 22 * s), (24 * s, 22 * s)]
    draw.polygon(bolt, fill=(46, 204, 113, 255))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    _ICON_CACHE[sz] = buf.getvalue()
    return _ICON_CACHE[sz]