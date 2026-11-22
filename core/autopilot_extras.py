# core/autopilot_extras.py
import json
import time
import datetime
from utils.config import cfg
from utils.helpers import format_file_size, write_error_log
from core.app_state_db import app_state_db
from core.notifiers import notify_all
from core.disk_monitor import get_monitored_disk_info
from core.qb_api import _post_qb_api, set_global_speed_limits

_REANNOUNCE_COOLDOWN = {}  # { hash_lower: ts }


def _ensure_tables():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS download_snipers (
                        hash_id TEXT PRIMARY KEY,
                        idle_hours REAL NOT NULL DEFAULT 4.0,
                        last_progress REAL NOT NULL DEFAULT 0,
                        last_progress_at REAL NOT NULL,
                        notified_state TEXT NOT NULL DEFAULT ''
                    );
                    CREATE TABLE IF NOT EXISTS auto_router_rules (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        priority INTEGER NOT NULL DEFAULT 10,
                        match_field TEXT NOT NULL,
                        pattern TEXT NOT NULL,
                        target_category TEXT NOT NULL DEFAULT '',
                        target_path TEXT NOT NULL DEFAULT ''
                    );
                    CREATE TABLE IF NOT EXISTS auto_router_seen (
                        hash_id TEXT PRIMARY KEY,
                        routed_at REAL NOT NULL
                    );
                """)
                conn.commit()
        except Exception as e:
            write_error_log("autopilot_extras init", e)


_ensure_tables()


def toggle_sniper(t_hash, idle_hours=4.0):
    hl = str(t_hash or '').strip().lower()
    if not hl:
        return False, False
    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            ex = conn.execute("SELECT 1 FROM download_snipers WHERE hash_id = ?", (hl,)).fetchone()
            if ex:
                conn.execute("DELETE FROM download_snipers WHERE hash_id = ?", (hl,))
                conn.commit()
                return True, False
            conn.execute(
                "INSERT INTO download_snipers (hash_id, idle_hours, last_progress, last_progress_at, notified_state) VALUES (?, ?, 0, ?, '')",
                (hl, max(0.5, float(idle_hours)), time.time())
            )
            conn.commit()
            return True, True


def list_snipers():
    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            return [r['hash_id'] for r in conn.execute("SELECT hash_id FROM download_snipers").fetchall()]


def _tick_snipers(live):
    now = time.time()
    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM download_snipers").fetchall()]
    if not rows:
        return

    live_map = {h.lower(): info for h, info in live.items()}
    free_b = int(get_monitored_disk_info(live).get('free_bytes') or 0)

    for r in rows:
        hl = r['hash_id']
        info = live_map.get(hl)
        if not info:
            continue
        prog = float(info.get('progress', 0.0) or 0.0)
        nm = str(info.get('name') or hl)
        if prog >= 0.9999:
            notify_all("🎯 Закачка завершена!", [f"Раздача: {nm}"], critical=True)
            with app_state_db._lock:
                with app_state_db._get_conn() as conn:
                    conn.execute("DELETE FROM download_snipers WHERE hash_id = ?", (hl,))
                    conn.commit()
            continue

        if prog > float(r['last_progress'] or 0) + 0.001:
            with app_state_db._lock:
                with app_state_db._get_conn() as conn:
                    conn.execute("UPDATE download_snipers SET last_progress = ?, last_progress_at = ?, notified_state = '' WHERE hash_id = ?", (prog, now, hl))
                    conn.commit()
            continue

        left_b = int(info.get('amount_left', 0) or 0)
        if free_b > 0 and left_b > free_b and r['notified_state'] != 'no_space':
            notify_all("⚠️ Недостаточно места для финиша закачки", [f"Раздача: {nm}", f"Нужно: {format_file_size(left_b)}, свободно: {format_file_size(free_b)}"], critical=True)
            with app_state_db._lock:
                with app_state_db._get_conn() as conn:
                    conn.execute("UPDATE download_snipers SET notified_state = 'no_space' WHERE hash_id = ?", (hl,))
                    conn.commit()
        elif (now - float(r['last_progress_at'])) >= float(r['idle_hours']) * 3600 and r['notified_state'] != 'stalled':
            notify_all("⏳ Закачка зависла без прогресса", [f"Раздача: {nm}", f"Прогресс: {prog*100:.1f}% (простой > {r['idle_hours']}ч)"])
            with app_state_db._lock:
                with app_state_db._get_conn() as conn:
                    conn.execute("UPDATE download_snipers SET notified_state = 'stalled' WHERE hash_id = ?", (hl,))
                    conn.commit()


def get_conductor_config():
    try:
        blocks = json.loads(cfg.get('Conductor_Blocks_JSON', '[]') or '[]')
    except Exception:
        blocks = []
    return {
        'enabled': cfg.getboolean('Conductor_Enabled', False),
        'blocks': blocks if isinstance(blocks, list) else [],
        'override_until': cfg.getint('Conductor_Override_Until', 0)
    }


def _hour_in_block(hr, start_h, end_h):
    if start_h == end_h:
        return True
    if start_h < end_h:
        return start_h <= hr < end_h
    return hr >= start_h or hr < end_h


def _tick_conductor(ip, port):
    c = get_conductor_config()
    now = time.time()
    last_applied = cfg.getint('Conductor_Last_Applied_Up', -1)

    if not c['enabled'] or not c['blocks'] or now < c['override_until']:
        if last_applied > 0:
            set_global_speed_limits(ip, port, 0, 0)
            cfg.set('Conductor_Last_Applied_Up', '0')
            cfg.save()
        return

    hr = datetime.datetime.now().hour
    matched = None
    for b in c['blocks']:
        if not isinstance(b, dict):
            continue
        try:
            sh = int(b.get('start_h', 0)) % 24
            eh = int(b.get('end_h', 24))
            eh = 24 if eh == 24 else (eh % 24)
        except (ValueError, TypeError):
            continue
        if _hour_in_block(hr, sh, eh):
            matched = b
            break

    if not matched:
        if last_applied > 0:
            set_global_speed_limits(ip, port, 0, 0)
            cfg.set('Conductor_Last_Applied_Up', '0')
            cfg.save()
        return

    try:
        pct = max(0, min(100, int(matched.get('pct_limit', 100))))
    except (ValueError, TypeError):
        pct = 100
    max_mbps = max(10, cfg.getint('Max_Channel_Mbps', 1000))
    up_bps = 0 if pct >= 100 else max(1024, int(((max_mbps * 1_000_000) / 8.0) * (pct / 100.0)))
    if last_applied != up_bps:
        set_global_speed_limits(ip, port, 0, up_bps)
        cfg.set('Conductor_Last_Applied_Up', str(up_bps))
        cfg.save()


def _tick_auto_router(ip, port, live):
    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            rules = [dict(r) for r in conn.execute("SELECT * FROM auto_router_rules ORDER BY priority ASC, id ASC").fetchall()]
            if not rules:
                return
            seen = {r['hash_id'] for r in conn.execute("SELECT hash_id FROM auto_router_seen").fetchall()}

    now = time.time()
    new_seen = []
    for raw_h, info in live.items():
        hl = raw_h.lower()
        if hl in seen:
            continue
        new_seen.append((hl, now))
        tr = str(info.get('tracker') or '').lower()
        sz_gib = float(info.get('total_size', 0) or 0) / (1024 ** 3)
        nm = str(info.get('name') or '').lower()

        for r in rules:
            fld = r['match_field']
            pat = str(r['pattern'] or '').lower().strip()
            if not pat:
                continue
            hit = False
            if fld == 'tracker':
                hit = pat in tr
            elif fld == 'ext':
                hit = pat in nm
            elif fld == 'min_gib':
                try:
                    hit = sz_gib >= float(pat)
                except (ValueError, TypeError):
                    hit = False
            if hit:
                if r['target_category']:
                    _post_qb_api(ip, port, 'torrents/setCategory', {'hashes': raw_h, 'category': r['target_category']})
                if r['target_path']:
                    _post_qb_api(ip, port, 'torrents/setLocation', {'hashes': raw_h, 'location': r['target_path']})
                break

    if new_seen:
        with app_state_db._lock:
            with app_state_db._get_conn() as conn:
                conn.executemany("INSERT OR IGNORE INTO auto_router_seen (hash_id, routed_at) VALUES (?, ?)", new_seen)
                conn.commit()


def _tick_smart_queue_and_reannounce(ip, port, live):
    now = time.time()
    if cfg.getboolean('Smart_Queue_Enabled', False):
        small_fast = [h for h, inf in live.items() if float(inf.get('progress', 0) or 0) < 0.99 and 0 < int(inf.get('total_size', 0) or 0) <= (2 * 1024 ** 3) and int(inf.get('num_seeds', 0) or 0) >= 3 and int(inf.get('priority', 0) or 0) > 1]
        if small_fast:
            _post_qb_api(ip, port, 'torrents/topPrio', {'hashes': '|'.join(small_fast[:5])})

    if cfg.getboolean('Smart_Reannounce_Enabled', False):
        for raw_h, inf in live.items():
            hl = raw_h.lower()
            st = str(inf.get('state', '')).lower()
            if st not in ('stalledup', 'stalleddl', 'uploading', 'downloading'):
                continue
            if int(inf.get('num_leechs', 0) or 0) == 0 and int(inf.get('num_seeds', 0) or 0) == 0 and int(inf.get('time_active', 0) or 0) >= 600:
                if (now - _REANNOUNCE_COOLDOWN.get(hl, 0)) >= 1800:
                    _REANNOUNCE_COOLDOWN[hl] = now
                    _post_qb_api(ip, port, 'torrents/reannounce', {'hashes': raw_h})
                    time.sleep(0.2)


def tick_autopilot_extras(ip, port, live):
    if not port or not live:
        return
    try:
        _tick_snipers(live)
        _tick_conductor(ip, port)
        _tick_auto_router(ip, port, live)
        _tick_smart_queue_and_reannounce(ip, port, live)
    except Exception as e:
        write_error_log("tick_autopilot_extras", e)