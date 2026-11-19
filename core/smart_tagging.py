# core/smart_tagging.py
import time
from core.app_state_db import app_state_db
from core.qb_api import add_torrent_tags
from utils.helpers import write_log, write_error_log

VALID_MATCH_FIELDS = ('tracker', 'save_path')


def _ensure_table():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS tagging_rules (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        match_field TEXT NOT NULL,
                        pattern TEXT NOT NULL,
                        target_tag TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )
                """)
                conn.commit()
        except Exception as e:
            write_error_log("tagging_rules init", e)


_ensure_table()


def list_tagging_rules():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = conn.execute("SELECT * FROM tagging_rules ORDER BY id DESC").fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []


def add_tagging_rule(name, match_field, pattern, target_tag):
    fld = match_field if match_field in VALID_MATCH_FIELDS else 'tracker'
    pat = str(pattern or '').strip()[:120]
    tag = str(target_tag or '').strip()[:32]
    nm = str(name or '').strip()[:64] or f"{fld}: {pat} -> {tag}"
    if not pat or not tag:
        return None
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO tagging_rules (name, enabled, match_field, pattern, target_tag, created_at) VALUES (?, 1, ?, ?, ?, ?)",
                    (nm, fld, pat, tag, time.time())
                )
                conn.commit()
                return cur.lastrowid
        except Exception as e:
            write_error_log("add_tagging_rule", e)
            return None


def toggle_tagging_rule(rule_id):
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("UPDATE tagging_rules SET enabled = 1 - enabled WHERE id = ?", (int(rule_id),))
                conn.commit()
                return True
        except Exception:
            return False


def delete_tagging_rule(rule_id):
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("DELETE FROM tagging_rules WHERE id = ?", (int(rule_id),))
                conn.commit()
                return True
        except Exception:
            return False


def run_smart_tagging(ip, port, live, parsed_torrents=None):
    rules = [r for r in list_tagging_rules() if r.get('enabled')]
    if not rules or not ip or not port or not live:
        return 0

    parsed = parsed_torrents or {}
    applied = 0
    for raw_hash, info in live.items():
        cur_tags = {tg.strip().lower() for tg in str(info.get('tags', '') or '').split(',') if tg.strip()}
        save_path = str(info.get('save_path') or '').lower()
        tr_list = [str(info.get('tracker') or '')]
        st_item = parsed.get(raw_hash.lower()) or {}
        tr_list.extend(str(x) for x in (st_item.get('trackers') or []))
        trackers_blob = " ".join(tr_list).lower()

        for r in rules:
            tgt = str(r.get('target_tag') or '').strip()
            pat = str(r.get('pattern') or '').strip().lower()
            if not tgt or not pat or tgt.lower() in cur_tags:
                continue

            matched = (pat in trackers_blob) if r.get('match_field') == 'tracker' else (pat in save_path)
            if matched and add_torrent_tags(ip, port, raw_hash, tgt):
                cur_tags.add(tgt.lower())
                applied += 1
                nm = str(info.get('name') or raw_hash[:8])
                write_log('automation', f"Smart Tagging: '{nm}' -> +{tgt} (по правилу '{r['name']}')")
                app_state_db.add_audit_event('automation', f'Авто-тег +{tgt}', nm)

    return applied