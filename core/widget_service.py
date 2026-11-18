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

                # Защита от фантомных всплесков при мердже/добавлении раздач
                prev_cnt = int(prev.get('count', 0) or 0)
                cur_cnt = int(r.get('count', 0) or 0)
                if cur_cnt > prev_cnt and bps > (200 * 1024 * 1024):
                    bps = points[-1]['speed_bps'] if points else 0.0

                dt_obj = datetime.datetime.fromtimestamp(t2)
                points.append({
                    'ts': int(t2),
                    'label': dt_obj.strftime('%H:%M') if hours <= 48 else dt_obj.strftime('%d.%m %H:%M'),
                    'speed_bps': round(bps, 2),
                    'speed_mbs': round(bps / (1024 * 1024), 3),
                    'mb_h': round((bps * 3600.0) / (1024 * 1024), 1)
                })
        prev = r

    # Сглаживание одиночных импульсных выбросов (аномалия > 5x от соседних)
    if len(points) >= 3:
        for i in range(1, len(points) - 1):
            p_prev = points[i - 1]['speed_mbs']
            p_cur = points[i]['speed_mbs']
            p_next = points[i + 1]['speed_mbs']
            avg_neighbor = (p_prev + p_next) / 2.0
            if p_cur > 15.0 and p_cur > (avg_neighbor * 5.0):
                points[i]['speed_mbs'] = round(avg_neighbor, 3)
                points[i]['speed_bps'] = round(avg_neighbor * 1024 * 1024, 2)

    return points


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
        'timestamp': int(now_ts)
    }


def _hex_rgb(hex_str, default=(46, 204, 113)):
    s = str(hex_str or '').strip().lstrip('#')
    if len(s) == 6:
        try:
            return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    return default


def _draw_speed_chart(draw, series, sw, sh, pad_l, pad_r, pad_t, pad_b, scale, line_c, txt_c, grid_c, hours):
    font = ImageFont.load_default()
    plot_w = max(10, sw - pad_l - pad_r)
    plot_h = max(10, sh - pad_t - pad_b)

    for i in range(4):
        gy = pad_t + int(plot_h * (i / 3.0))
        draw.line([(pad_l, gy), (sw - pad_r, gy)], fill=grid_c + (255,), width=1 * scale)

    if len(series) < 2:
        draw.text((pad_l + 10, sh // 2 - 8), "Waiting for snapshots...", fill=txt_c + (255,), font=font)
        return

    t_min, t_max = series[0]['ts'], series[-1]['ts']
    t_span = max(1, t_max - t_min)
    v_max = max(max(p['speed_mbs'] for p in series), 0.1)

    pts = []
    for p in series:
        x = pad_l + int(((p['ts'] - t_min) / t_span) * plot_w)
        y = pad_t + plot_h - int((p['speed_mbs'] / v_max) * plot_h)
        pts.append((x, y))

    fill_poly = [(pts[0][0], pad_t + plot_h)] + pts + [(pts[-1][0], pad_t + plot_h)]
    draw.polygon(fill_poly, fill=line_c + (55,))
    draw.line(pts, fill=line_c + (255,), width=2 * scale, joint='curve')

    draw.text((pad_l, 4 * scale), f"⚡ Скорость (макс: {v_max:.2f} MiB/s)", fill=txt_c + (255,), font=font)
    draw.text((pad_l, sh - 16 * scale), series[0]['label'], fill=txt_c + (255,), font=font)
    draw.text((sw - pad_r - 45 * scale, sh - 16 * scale), series[-1]['label'], fill=txt_c + (255,), font=font)


def _draw_daily_chart(draw, db, sw, sh, pad_l, pad_r, pad_t, pad_b, scale, bar_c, txt_c, grid_c):
    font = ImageFont.load_default()
    plot_w = max(10, sw - pad_l - pad_r)
    plot_h = max(10, sh - pad_t - pad_b)

    now_ts = time.time()
    rows = db.get_snapshots_since(now_ts - (7 * 86400))
    daily_map = {}
    prev_row = None
    for r in rows:
        if prev_row is not None:
            t1, t2 = prev_row['timestamp'], r['timestamp']
            dt = t2 - t1
            delta = max(0, r['total_uploaded'] - prev_row['total_uploaded'])
            if dt >= MIN_DELTA_SEC and delta > 0:
                day_key = datetime.datetime.fromtimestamp(t2).strftime('%d.%m')
                daily_map[day_key] = daily_map.get(day_key, 0.0) + (delta / (1024 ** 3))
        prev_row = r

    items = list(daily_map.items())[-7:]
    if not items:
        draw.text((pad_l + 10, sh // 2 - 8), "No daily data yet...", fill=txt_c + (255,), font=font)
        return

    v_max = max(max(v for _, v in items), 0.1)
    bar_w = max(6 * scale, (plot_w // len(items)) - (6 * scale))

    for i in range(4):
        gy = pad_t + int(plot_h * (i / 3.0))
        draw.line([(pad_l, gy), (sw - pad_r, gy)], fill=grid_c + (255,), width=1 * scale)

    for idx, (lbl, val) in enumerate(items):
        bx = pad_l + int((idx + 0.5) * (plot_w / len(items))) - (bar_w // 2)
        bh = int((val / v_max) * plot_h)
        by = pad_t + plot_h - bh
        draw.rounded_rectangle([bx, by, bx + bar_w, pad_t + plot_h], radius=3 * scale, fill=bar_c + (220,))
        draw.text((bx, sh - 16 * scale), lbl, fill=txt_c + (255,), font=font)

    draw.text((pad_l, 4 * scale), f"📅 Отдача по дням (макс: {v_max:.1f} GiB)", fill=txt_c + (255,), font=font)


def render_widget_chart_png(db, ui_settings, hours=24, width=600, height=220, chart_type='speed'):
    w = max(240, min(1400, int(width)))
    h = max(100, min(800, int(height)))
    scale = 2
    sw, sh = w * scale, h * scale

    theme = (ui_settings or {}).get('theme', 'dark')
    if theme == 'light':
        bg_c, grid_c, txt_c = (255, 255, 255), (215, 220, 226), (107, 114, 128)
    elif theme == 'oled':
        bg_c, grid_c, txt_c = (8, 8, 10), (30, 30, 36), (140, 140, 152)
    elif theme == 'custom':
        cc = (ui_settings or {}).get('custom_colors', {})
        bg_c = _hex_rgb(cc.get('bg_panel'), (26, 26, 32))
        grid_c = (55, 55, 68)
        txt_c = _hex_rgb(cc.get('text'), (220, 220, 225))
    else:
        bg_c, grid_c, txt_c = (26, 26, 32), (45, 45, 56), (149, 165, 166)

    charts_cfg = (ui_settings or {}).get('charts') or {}
    sp_color = _hex_rgb((charts_cfg.get('hourly') or {}).get('color'), (52, 152, 219))
    dl_color = _hex_rgb((charts_cfg.get('daily') or {}).get('color'), (46, 204, 113))

    img = Image.new('RGBA', (sw, sh), bg_c + (255,))
    draw = ImageDraw.Draw(img, 'RGBA')
    pad_l, pad_r, pad_t, pad_b = 18 * scale, 14 * scale, 18 * scale, 22 * scale

    c_type = str(chart_type or 'speed').lower()
    if c_type == 'daily':
        _draw_daily_chart(draw, db, sw, sh, pad_l, pad_r, pad_t, pad_b, scale, dl_color, txt_c, grid_c)
    else:
        series = build_detailed_speed_series(db, hours=hours)
        _draw_speed_chart(draw, series, sw, sh, pad_l, pad_r, pad_t, pad_b, scale, sp_color, txt_c, grid_c, hours)

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
    r = max(8, sz // 5)
    draw.rounded_rectangle([0, 0, sz - 1, sz - 1], radius=r, fill=(26, 26, 32, 255))
    s = sz / 48.0
    bolt = [(26 * s, 6 * s), (12 * s, 26 * s), (24 * s, 26 * s), (20 * s, 42 * s), (36 * s, 22 * s), (24 * s, 22 * s)]
    draw.polygon(bolt, fill=(46, 204, 113, 255))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    _ICON_CACHE[sz] = buf.getvalue()
    return _ICON_CACHE[sz]