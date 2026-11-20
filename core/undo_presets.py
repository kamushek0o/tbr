# core/undo_presets.py
import json
import time
from utils.config import cfg
from core.app_state_db import app_state_db
from core.automation import automation_engine
from core.qb_api import (
    detect_qbittorrent_port, edit_torrent_tracker,
    add_torrent_tags, remove_torrent_tags, send_qb_command
)


def list_undo_stack():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = conn.execute(
                    "SELECT id, op_type, title, created_at, undone FROM undo_stack ORDER BY id DESC LIMIT 10"
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []


def execute_undo(undo_id):
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                row = conn.execute("SELECT * FROM undo_stack WHERE id = ?", (int(undo_id),)).fetchone()
                if not row:
                    return False, "Запись отката не найдена"
                if row['undone']:
                    return False, "Эта операция уже была отменена"
                rec = dict(row)
        except Exception as e:
            return False, str(e)

    ip, port = detect_qbittorrent_port(cfg.config)
    if not port:
        return False, "qBittorrent недоступен для отката"

    payload = json.loads(rec['payload_json'] or '[]')
    op = rec['op_type']
    reverted = 0

    if op == 'tracker_replace':
        for it in payload:
            if edit_torrent_tracker(ip, port, it['hash'], it['orig_url'], it['new_url']):
                reverted += 1
            time.sleep(0.1)
    elif op == 'tags_bulk':
        act_fn = remove_torrent_tags if payload.get('action') == 'addTags' else add_torrent_tags
        if act_fn(ip, port, payload.get('hashes', ''), payload.get('tag', '')):
            reverted = 1
    elif op == 'pause_start_bulk':
        rev_act = 'start' if payload.get('action') == 'stop' else 'stop'
        if send_qb_command(ip, port, rev_act, payload.get('hashes', '')):
            reverted = 1

    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            conn.execute("UPDATE undo_stack SET undone = 1 WHERE id = ?", (int(undo_id),))
            conn.commit()

    app_state_db.add_audit_event('system', 'Откат операции (Undo)', f"{rec['title']} (reverted={reverted})", actor='admin')
    return True, f"Откат выполнен: {rec['title']}"


def export_presets_json():
    rules = automation_engine.get_rules()
    clean_rules = []
    for r in rules:
        d = dict(r)
        d.pop('id', None)
        clean_rules.append(d)

    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS saved_views (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, filters_json TEXT NOT NULL, created_at REAL NOT NULL)")
                views = [dict(v) for v in conn.execute("SELECT name, filters_json FROM saved_views ORDER BY id ASC").fetchall()]
        except Exception:
            views = []

    return {
        'format': 'tbr_pro_presets_v1',
        'exported_at': int(time.time()),
        'automation_rules': clean_rules,
        'saved_views': views
    }


def import_presets_json(data):
    if not isinstance(data, dict) or data.get('format') != 'tbr_pro_presets_v1':
        return False, "Неверный формат пресета (ожидался tbr_pro_presets_v1)"

    imported_rules = 0
    for r in (data.get('automation_rules') or []):
        if not isinstance(r, dict):
            continue
        rid = automation_engine.add_rule(
            name=str(r.get('name', 'Импорт'))[:64],
            min_ratio=float(r.get('min_ratio', 0) or 0),
            min_seed_days=float(r.get('min_seed_days', 0) or 0),
            action_pause=bool(r.get('action_pause', False)),
            action_tag=str(r.get('action_tag', '') or '')[:32],
            notify=bool(r.get('notify', True)),
            time_mode=str(r.get('time_mode', 'seeding_time')),
            min_uploaded_bytes=int(r.get('min_uploaded_bytes', 0) or 0),
            speed_op=str(r.get('speed_op', '') or ''),
            speed_bytes=float(r.get('speed_bytes', 0) or 0),
            speed_window_min=int(r.get('speed_window_min', 60) or 60),
            action_remove_tag=str(r.get('action_remove_tag', '') or '')[:32]
        )
        if rid:
            # Все импортируемые правила строго ВЫКЛЮЧЕНЫ (#29)
            automation_engine.toggle_rule(rid)
            imported_rules += 1

    imported_views = 0
    if data.get('saved_views'):
        with app_state_db._lock:
            with app_state_db._get_conn() as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS saved_views (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, filters_json TEXT NOT NULL, created_at REAL NOT NULL)")
                for v in data['saved_views']:
                    if isinstance(v, dict) and v.get('name') and v.get('filters_json'):
                        conn.execute("INSERT INTO saved_views (name, filters_json, created_at) VALUES (?, ?, ?)", (str(v['name'])[:40], str(v['filters_json']), time.time()))
                        imported_views += 1
                conn.commit()

    return True, f"Импортировано правил (выключены!): {imported_rules}, видов: {imported_views}. Рекомендуется прогнать Dry-Run."