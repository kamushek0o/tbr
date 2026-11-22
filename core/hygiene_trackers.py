# core/hygiene_trackers.py
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.config import cfg
from utils.helpers import format_file_size, write_error_log
from core.app_state_db import app_state_db
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info, get_torrent_trackers, add_torrent_tags
from core.health_score import compute_health_metrics

_FATAL_KEYWORDS = ('unregistered', 'not registered', 'deleted', 'banned', 'not found', 'не зарегистрирован', 'удален', 'удалён', 'запрещен', 'запрещён')
_PROTECTED_TAGS = {'keep', 'vip', 'protected', 'archive'}


def _ensure_quarantine_table():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS quarantine_tracker (
                        hash_id TEXT PRIMARY KEY,
                        first_error_at REAL NOT NULL,
                        error_msg TEXT NOT NULL,
                        tagged_at REAL
                    )
                """)
                conn.commit()
        except Exception as e:
            write_error_log("quarantine_tracker init", e)


_ensure_quarantine_table()


def _is_fatal_msg(msg):
    low = str(msg or '').lower()
    return any(k in low for k in _FATAL_KEYWORDS)


def scan_quarantine(hours_threshold=72, apply_tags=False):
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    if not live:
        return {'success': False, 'error': 'qBittorrent недоступен', 'items': []}

    now = time.time()
    thresh_sec = max(1, int(hours_threshold)) * 3600

    def check_tor(t_hash, info):
        trackers = get_torrent_trackers(ip, port, t_hash)
        real = [tr for tr in trackers if not str(tr.get('url', '')).startswith('**[') and tr.get('status', 0) != 0]
        if not real:
            return t_hash.lower(), None
        all_fatal = all(tr.get('status') == 4 and _is_fatal_msg(tr.get('msg')) for tr in real)
        if not all_fatal:
            return t_hash.lower(), None
        return t_hash.lower(), str(real[0].get('msg') or 'Fatal tracker error').strip()

    fatal_map = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        for fut in as_completed([pool.submit(check_tor, h, inf) for h, inf in live.items()]):
            try:
                hl, msg = fut.result()
                if msg:
                    fatal_map[hl] = msg
            except Exception:
                pass

    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            existing = {r['hash_id']: dict(r) for r in conn.execute("SELECT * FROM quarantine_tracker").fetchall()}
            for hl in list(existing.keys()):
                if hl not in fatal_map:
                    conn.execute("DELETE FROM quarantine_tracker WHERE hash_id = ?", (hl,))
            for hl, msg in fatal_map.items():
                if hl not in existing:
                    conn.execute("INSERT INTO quarantine_tracker (hash_id, first_error_at, error_msg, tagged_at) VALUES (?, ?, ?, NULL)", (hl, now, msg))
            conn.commit()
            rows = {r['hash_id']: dict(r) for r in conn.execute("SELECT * FROM quarantine_tracker").fetchall()}

    live_lower = {k.lower(): (k, v) for k, v in live.items()}
    out = []
    for hl, r in rows.items():
        if hl not in live_lower:
            continue
        raw_h, info = live_lower[hl]
        elapsed_h = round((now - float(r['first_error_at'])) / 3600.0, 1)
        ready = (now - float(r['first_error_at'])) >= thresh_sec
        cur_tags = {tg.strip().lower() for tg in str(info.get('tags', '') or '').split(',') if tg.strip()}
        if ready and apply_tags and 'quarantine' not in cur_tags:
            if add_torrent_tags(ip, port, raw_h, 'quarantine'):
                cur_tags.add('quarantine')
        out.append({
            'hash': raw_h, 'name': info.get('name', raw_h),
            'size': int(info.get('total_size', 0) or 0),
            'size_fmt': format_file_size(info.get('total_size', 0)),
            'content_path': info.get('content_path') or info.get('save_path') or '',
            'error_msg': r['error_msg'], 'elapsed_hours': elapsed_h,
            'ready': ready, 'in_quarantine': 'quarantine' in cur_tags
        })

    out.sort(key=lambda x: x['elapsed_hours'], reverse=True)
    return {'success': True, 'items': out, 'threshold_hours': hours_threshold}


def scan_stalled_incompletes(stalled_days=0):
    """#37 Кладбище недокачек: незавершённые раздачи (на паузе, зависшие, без сидов или avail < 1.0)."""
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    if not live:
        return {'success': False, 'error': 'qBittorrent недоступен', 'items': []}

    now = time.time()
    min_idle = max(0, int(stalled_days or 0)) * 86400
    items = []

    for h, info in live.items():
        progress = float(info.get('progress', 0.0) or 0.0)
        amt_left = int(info.get('amount_left', 0) or 0)
        state = str(info.get('state', '')).lower()

        # Полностью скачанные и отдающиеся раздачи отбрасываем
        if progress >= 0.9999 and amt_left == 0:
            continue
        if state in ('uploading', 'seeding', 'stalledup', 'forcedup', 'pausedup', 'stoppedup'):
            continue

        raw_avail = info.get('availability')
        avail = float(raw_avail) if raw_avail is not None else -1.0
        num_seeds = int(info.get('num_seeds', 0) or 0)
        num_complete = int(info.get('num_complete', 0) or 0)
        dlspeed = int(info.get('dlspeed', 0) or 0)

        # Любая недокачка, которая сейчас не качает на полной скорости
        is_stalled = (
            (0.0 <= avail < 1.0) or
            avail < 0 or
            (num_seeds == 0 and num_complete <= 0) or
            state in ('stalleddl', 'pauseddl', 'stoppeddl', 'queueddl', 'metadl') or
            dlspeed == 0
        )
        if not is_stalled:
            continue

        last_act = int(info.get('last_activity') or 0)
        added_on = int(info.get('added_on') or now)
        ref_ts = last_act if last_act > 0 else added_on
        idle_sec = max(0, now - ref_ts)

        if min_idle > 0 and idle_sec < min_idle:
            continue

        sz = int(info.get('total_size', 0) or 0)
        downloaded = int(info.get('downloaded', 0) or (sz - amt_left if sz > amt_left else 0))
        items.append({
            'hash': h,
            'name': info.get('name', h),
            'progress_pct': round(progress * 100.0, 1),
            'availability': round(avail, 2) if avail >= 0 else '—',
            'state': state,
            'idle_days': round(idle_sec / 86400.0, 1),
            'size': sz,
            'size_fmt': format_file_size(sz),
            'downloaded_fmt': format_file_size(downloaded),
            'content_path': info.get('content_path') or info.get('save_path') or ''
        })

    items.sort(key=lambda x: x['size'], reverse=True)
    return {'success': True, 'items': items}


def scan_dead_weight(idle_days=30, min_seeds=10):
    """#4 Рейтинг тунеядцев: защита Последнего сида, свежих и защищённых тегов."""
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    if not live:
        return {'success': False, 'error': 'qBittorrent недоступен', 'items': []}

    now = time.time()
    min_idle_sec = max(1, int(idle_days)) * 86400
    fresh_guard_sec = 14 * 86400
    items = []

    for h, info in live.items():
        if float(info.get('progress', 0.0) or 0.0) < 0.9999:
            continue
        hm = compute_health_metrics(info)
        if hm.get('is_last_seed') or hm.get('num_complete', 0) < int(min_seeds):
            continue
        tags = {tg.strip().lower() for tg in str(info.get('tags', '') or '').split(',') if tg.strip()}
        if tags & _PROTECTED_TAGS:
            continue
        added = int(info.get('added_on') or now)
        if (now - added) < fresh_guard_sec:
            continue
        last_act = int(info.get('last_activity') or added)
        idle_sec = max(0, now - last_act)
        if idle_sec < min_idle_sec:
            continue

        sz = int(info.get('total_size', 0) or 0)
        up = int(info.get('uploaded', 0) or 0)
        items.append({
            'hash': h, 'name': info.get('name', h),
            'size': sz, 'size_fmt': format_file_size(sz),
            'uploaded_fmt': format_file_size(up),
            'ratio': round(float(info.get('ratio', 0.0) or 0.0), 2),
            'seeds': hm.get('num_complete', 0),
            'idle_days': round(idle_sec / 86400.0, 1),
            'content_path': info.get('content_path') or info.get('save_path') or ''
        })

    items.sort(key=lambda x: (x['size'], x['idle_days']), reverse=True)
    return {'success': True, 'items': items}