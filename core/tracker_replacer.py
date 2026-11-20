# core/tracker_replacer.py
import json
import time
from utils.config import cfg
from utils.helpers import write_error_log
from core.app_state_db import app_state_db
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info, get_torrent_trackers, edit_torrent_tracker


def _ensure_undo_table():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS undo_stack (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        op_type TEXT NOT NULL,
                        title TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        undone INTEGER NOT NULL DEFAULT 0
                    )
                """)
                conn.commit()
        except Exception as e:
            write_error_log("undo_stack init", e)


_ensure_undo_table()


def push_undo_record(op_type, title, payload):
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute(
                    "INSERT INTO undo_stack (op_type, title, payload_json, created_at, undone) VALUES (?, ?, ?, ?, 0)",
                    (str(op_type), str(title)[:160], json.dumps(payload, ensure_ascii=False), time.time())
                )
                conn.execute("DELETE FROM undo_stack WHERE id NOT IN (SELECT id FROM undo_stack ORDER BY id DESC LIMIT 10)")
                conn.commit()
        except Exception as e:
            write_error_log("push_undo_record", e)


def preview_tracker_replace(find_str, replace_str):
    find_s = str(find_str or '').strip()
    rep_s = str(replace_str or '').strip()
    if not find_s or not rep_s or find_s == rep_s:
        return {'success': False, 'error': 'Укажите разные непустые строки поиска и замены', 'matches': []}

    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    if not live:
        return {'success': False, 'error': 'qBittorrent недоступен', 'matches': []}

    matches = []
    for h, info in live.items():
        for tr in get_torrent_trackers(ip, port, h):
            url = str(tr.get('url', '') or '')
            if not url or url.startswith('**[') or find_s not in url:
                continue
            new_url = url.replace(find_s, rep_s)
            matches.append({
                'hash': h,
                'name': info.get('name', h),
                'old_url': url,
                'new_url': new_url
            })
    return {'success': True, 'matches': matches, 'count': len(matches)}


def apply_tracker_replace(find_str, replace_str, actor='admin'):
    prev = preview_tracker_replace(find_str, replace_str)
    if not prev.get('success'):
        return prev
    matches = prev.get('matches') or []
    if not matches:
        return {'success': False, 'error': 'Совпадений в трекерах не найдено'}

    ip, port = detect_qbittorrent_port(cfg.config)
    updated = 0
    reverse_ops = []

    for m in matches:
        if edit_torrent_tracker(ip, port, m['hash'], m['old_url'], m['new_url']):
            updated += 1
            reverse_ops.append({'hash': m['hash'], 'orig_url': m['new_url'], 'new_url': m['old_url']})
        time.sleep(0.15)

    if reverse_ops:
        push_undo_record('tracker_replace', f"Замена трекеров ({updated} шт.)", reverse_ops)
        app_state_db.add_audit_event('system', 'Смена трекеров/пасскеев', f'Обновлено URL: {updated}', actor=actor)

    return {'success': True, 'updated': updated, 'total': len(matches)}