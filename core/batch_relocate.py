# core/batch_relocate.py
import os
import time
import shutil
import threading
from utils.config import cfg
from utils.helpers import format_file_size, write_error_log
from core.app_state_db import app_state_db
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info, set_torrent_location
from core.disk_monitor import _get_mount_key

_WORKER_LOCK = threading.Lock()
_WORKER_RUNNING = False


def _ensure_table():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS batch_relocate_queue (
                        hash_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        old_path TEXT NOT NULL,
                        new_path TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'pending',
                        created_at REAL NOT NULL
                    )
                """)
                conn.commit()
        except Exception as e:
            write_error_log("batch_relocate_queue init", e)


_ensure_table()


def _norm_sep(p):
    return os.path.normpath(str(p or '').strip())


def preview_batch_relocate(old_prefix, new_prefix):
    op = _norm_sep(old_prefix)
    np = _norm_sep(new_prefix)
    if not op or not np or op == np:
        return {'success': False, 'error': 'Укажите разные непустые шаблоны пути', 'items': []}

    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    if not live:
        return {'success': False, 'error': 'qBittorrent недоступен', 'items': []}

    items = []
    need_bytes = 0
    op_cmp = os.path.normcase(op)

    for h, info in live.items():
        sp = _norm_sep(info.get('save_path', ''))
        if not sp:
            continue
        sp_cmp = os.path.normcase(sp)
        if sp_cmp == op_cmp or sp_cmp.startswith(op_cmp + os.sep):
            suffix = sp[len(op):].lstrip('\\/')
            dst = os.path.join(np, suffix) if suffix else np
            sz = int(info.get('total_size', 0) or 0)
            if _get_mount_key(sp) != _get_mount_key(np if os.path.exists(np) else os.path.dirname(np)):
                need_bytes += sz
            items.append({'hash': h, 'name': info.get('name', h), 'old_path': sp, 'new_path': dst, 'size': sz, 'size_fmt': format_file_size(sz)})

    free_bytes = None
    probe = np if os.path.exists(np) else os.path.dirname(np)
    if probe and os.path.exists(probe):
        try:
            free_bytes = shutil.disk_usage(probe).free
        except Exception:
            pass

    space_ok = True if (free_bytes is None or need_bytes == 0) else (free_bytes > need_bytes + (512 * 1024 * 1024))
    return {
        'success': True, 'items': items, 'count': len(items),
        'need_fmt': format_file_size(need_bytes),
        'free_fmt': format_file_size(free_bytes) if free_bytes is not None else '—',
        'space_ok': space_ok
    }


def start_batch_relocate(old_prefix, new_prefix, actor='admin'):
    prev = preview_batch_relocate(old_prefix, new_prefix)
    if not prev.get('success'):
        return prev
    if not prev.get('space_ok'):
        return {'success': False, 'error': f"Недостаточно места на целевом диске! Нужно {prev['need_fmt']}, свободно {prev['free_fmt']}"}
    items = prev.get('items') or []
    if not items:
        return {'success': False, 'error': 'Нет раздач под указанный шаблон пути'}

    now = time.time()
    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            conn.execute("DELETE FROM batch_relocate_queue WHERE status IN ('done', 'error')")
            conn.executemany(
                """INSERT OR REPLACE INTO batch_relocate_queue
                   (hash_id, name, old_path, new_path, size_bytes, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                [(it['hash'], it['name'], it['old_path'], it['new_path'], it['size'], now) for it in items]
            )
            conn.commit()

    app_state_db.add_audit_event('system', 'Пакетный переезд запущен', f'{old_prefix} -> {new_prefix} ({len(items)} шт.)', actor=actor)
    _spawn_relocate_worker()
    return {'success': True, 'queued': len(items)}


def get_relocate_status():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = [dict(r) for r in conn.execute("SELECT * FROM batch_relocate_queue ORDER BY created_at ASC").fetchall()]
                return {
                    'running': _WORKER_RUNNING,
                    'total': len(rows),
                    'pending': sum(1 for r in rows if r['status'] == 'pending'),
                    'moving': sum(1 for r in rows if r['status'] == 'moving'),
                    'done': sum(1 for r in rows if r['status'] == 'done'),
                    'items': rows[:50]
                }
        except Exception:
            return {'running': False, 'total': 0, 'pending': 0, 'moving': 0, 'done': 0, 'items': []}


def _spawn_relocate_worker():
    global _WORKER_RUNNING
    with _WORKER_LOCK:
        if _WORKER_RUNNING:
            return
        _WORKER_RUNNING = True

    def worker():
        global _WORKER_RUNNING
        try:
            while True:
                with app_state_db._lock:
                    with app_state_db._get_conn() as conn:
                        batch = [dict(r) for r in conn.execute(
                            "SELECT * FROM batch_relocate_queue WHERE status = 'pending' LIMIT 4"
                        ).fetchall()]
                if not batch:
                    break

                ip, port = detect_qbittorrent_port(cfg.config)
                if not port:
                    time.sleep(5)
                    continue

                by_dst = {}
                for b in batch:
                    by_dst.setdefault(b['new_path'], []).append(b['hash_id'])
                    with app_state_db._lock:
                        with app_state_db._get_conn() as conn:
                            conn.execute("UPDATE batch_relocate_queue SET status = 'moving' WHERE hash_id = ?", (b['hash_id'],))
                            conn.commit()

                for dst, hs in by_dst.items():
                    os.makedirs(dst, exist_ok=True)
                    set_torrent_location(ip, port, '|'.join(hs), dst)

                moving_hashes = {b['hash_id'].lower() for b in batch}
                deadline = time.monotonic() + 300.0
                while time.monotonic() < deadline:
                    time.sleep(2.0)
                    live = get_live_torrent_info(ip, port)
                    still_moving = any(
                        str(live.get(h, {}).get('state', '')).lower() == 'moving'
                        for h in live if h.lower() in moving_hashes
                    )
                    if not still_moving:
                        break

                with app_state_db._lock:
                    with app_state_db._get_conn() as conn:
                        for b in batch:
                            conn.execute("UPDATE batch_relocate_queue SET status = 'done' WHERE hash_id = ?", (b['hash_id'],))
                        conn.commit()
        except Exception as e:
            write_error_log("batch_relocate worker", e)
        finally:
            with _WORKER_LOCK:
                _WORKER_RUNNING = False

    threading.Thread(target=worker, daemon=True).start()


def resume_pending_relocate_if_any():
    st = get_relocate_status()
    if st.get('pending', 0) > 0 or st.get('moving', 0) > 0:
        with app_state_db._lock:
            with app_state_db._get_conn() as conn:
                conn.execute("UPDATE batch_relocate_queue SET status = 'pending' WHERE status = 'moving'")
                conn.commit()
        _spawn_relocate_worker()