# core/saved_views.py
import json
import time
from core.app_state_db import app_state_db
from utils.helpers import write_error_log


def _ensure_table():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS saved_views (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        filters_json TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )
                """)
                conn.commit()
        except Exception as e:
            write_error_log("saved_views init", e)


_ensure_table()


def list_saved_views():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = conn.execute("SELECT * FROM saved_views ORDER BY id ASC").fetchall()
                out = []
                for r in rows:
                    try:
                        flt = json.loads(r['filters_json'] or '{}')
                    except Exception:
                        flt = {}
                    out.append({'id': r['id'], 'name': r['name'], 'filters': flt})
                return out
        except Exception:
            return []


def add_saved_view(name, filters_dict):
    clean_name = str(name or '').strip()[:32]
    if not clean_name or not isinstance(filters_dict, dict):
        return None
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                cur = conn.execute(
                    "INSERT INTO saved_views (name, filters_json, created_at) VALUES (?, ?, ?)",
                    (clean_name, json.dumps(filters_dict, ensure_ascii=False), time.time())
                )
                conn.commit()
                return cur.lastrowid
        except Exception as e:
            write_error_log("add_saved_view", e)
            return None


def delete_saved_view(view_id):
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("DELETE FROM saved_views WHERE id = ?", (int(view_id),))
                conn.commit()
                return True
        except Exception:
            return False