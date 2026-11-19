# core/app_state_db.py
import os
import json
import time
import sqlite3
import threading
from utils.helpers import APP_DATA_DIR, write_error_log


class AppStateDB:
    def __init__(self):
        self.db_file = os.path.join(APP_DATA_DIR, "app_state.db")
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_file, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout = 30000;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    conn.executescript("""
                        CREATE TABLE IF NOT EXISTS audit_log (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            created_at REAL NOT NULL,
                            category TEXT NOT NULL,
                            actor TEXT NOT NULL DEFAULT 'system',
                            action TEXT NOT NULL,
                            details TEXT NOT NULL DEFAULT ''
                        );
                        CREATE INDEX IF NOT EXISTS idx_audit_cat_ts ON audit_log(category, created_at DESC);

                        CREATE TABLE IF NOT EXISTS smart_freeze (
                            hash_id TEXT PRIMARY KEY,
                            frozen_at REAL NOT NULL
                        );

                        CREATE TABLE IF NOT EXISTS snooze_timers (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            resume_at REAL NOT NULL,
                            mode TEXT NOT NULL DEFAULT 'pause',
                            active INTEGER NOT NULL DEFAULT 1,
                            created_at REAL NOT NULL
                        );

                        CREATE TABLE IF NOT EXISTS expiration_timers (
                            hash_id TEXT PRIMARY KEY,
                            expires_at REAL,
                            target_uploaded INTEGER,
                            delete_files INTEGER NOT NULL DEFAULT 0,
                            created_at REAL NOT NULL
                        );

                        CREATE TABLE IF NOT EXISTS dnd_queue (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            title TEXT NOT NULL,
                            lines_json TEXT NOT NULL,
                            created_at REAL NOT NULL
                        );

                        CREATE TABLE IF NOT EXISTS torrent_targets (
                            hash_id TEXT PRIMARY KEY,
                            target_ratio REAL NOT NULL DEFAULT 0,
                            target_bytes INTEGER NOT NULL DEFAULT 0,
                            achieved_at REAL,
                            updated_at REAL NOT NULL
                        );

                        CREATE TABLE IF NOT EXISTS private_vault_tags (
                            tag TEXT PRIMARY KEY,
                            created_at REAL NOT NULL
                        );

                        CREATE TABLE IF NOT EXISTS achievements (
                            code TEXT PRIMARY KEY,
                            unlocked_at REAL NOT NULL,
                            meta_json TEXT NOT NULL DEFAULT '{}'
                        );

                        CREATE TABLE IF NOT EXISTS watchdog_state (
                            id INTEGER PRIMARY KEY CHECK(id = 1),
                            consecutive_restarts INTEGER NOT NULL DEFAULT 0,
                            down_since REAL,
                            last_restart_at REAL,
                            halted INTEGER NOT NULL DEFAULT 0,
                            recheck_attempts_json TEXT NOT NULL DEFAULT '{}'
                        );

                        CREATE TABLE IF NOT EXISTS merger_history (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            source_hash TEXT NOT NULL,
                            target_hash TEXT NOT NULL,
                            mode TEXT NOT NULL DEFAULT 'add',
                            source_uploaded INTEGER NOT NULL DEFAULT 0,
                            target_uploaded INTEGER NOT NULL DEFAULT 0,
                            final_uploaded INTEGER NOT NULL DEFAULT 0,
                            created_at REAL NOT NULL
                        );
                        CREATE INDEX IF NOT EXISTS idx_merger_pair ON merger_history(source_hash, target_hash);
                    """)
                    conn.execute(
                        """INSERT OR IGNORE INTO watchdog_state
                           (id, consecutive_restarts, down_since, last_restart_at, halted, recheck_attempts_json)
                           VALUES (1, 0, NULL, NULL, 0, '{}')"""
                    )
                    conn.commit()
            except Exception as e:
                write_error_log("Инициализация app_state.db", e)

    def add_audit_event(self, category, action, details="", actor="system", max_rows=1000):
        cat = str(category or "system").strip().lower()
        with self._lock:
            try:
                with self._get_conn() as conn:
                    conn.execute(
                        "INSERT INTO audit_log (created_at, category, actor, action, details) VALUES (?, ?, ?, ?, ?)",
                        (time.time(), cat, str(actor or "system")[:64], str(action)[:160], str(details or "")[:1000])
                    )
                    conn.execute(
                        """DELETE FROM audit_log WHERE id NOT IN (
                               SELECT id FROM audit_log ORDER BY id DESC LIMIT ?
                           )""",
                        (max(100, int(max_rows)),)
                    )
                    conn.commit()
            except Exception as e:
                write_error_log("Ошибка add_audit_event", e)

    def get_audit_events(self, category="", limit=100, offset=0):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    if category:
                        cur.execute(
                            "SELECT * FROM audit_log WHERE category = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                            (category.strip().lower(), int(limit), int(offset))
                        )
                    else:
                        cur.execute(
                            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
                            (int(limit), int(offset))
                        )
                    return [dict(r) for r in cur.fetchall()]
            except Exception:
                return []

    def get_watchdog_state(self):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    row = conn.execute("SELECT * FROM watchdog_state WHERE id = 1").fetchone()
                    if row:
                        return dict(row)
            except Exception as e:
                write_error_log("Ошибка get_watchdog_state", e)
            return {
                "id": 1, "consecutive_restarts": 0, "down_since": None,
                "last_restart_at": None, "halted": 0, "recheck_attempts_json": "{}"
            }

    def update_watchdog_state(self, **fields):
        allowed = {"consecutive_restarts", "down_since", "last_restart_at", "halted", "recheck_attempts_json"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        with self._lock:
            try:
                set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
                params = list(updates.values())
                with self._get_conn() as conn:
                    conn.execute(f"UPDATE watchdog_state SET {set_clause} WHERE id = 1", params)
                    conn.commit()
            except Exception as e:
                write_error_log("Ошибка update_watchdog_state", e)

    def get_recheck_attempts(self):
        st = self.get_watchdog_state()
        try:
            data = json.loads(st.get("recheck_attempts_json") or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def save_recheck_attempts(self, attempts_map):
        clean = {str(k).lower(): float(v) for k, v in (attempts_map or {}).items()}
        self.update_watchdog_state(recheck_attempts_json=json.dumps(clean))

    def add_merger_record(self, src_hash, dst_hash, mode, src_up, dst_up, final_up):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    conn.execute(
                        """INSERT INTO merger_history
                           (source_hash, target_hash, mode, source_uploaded, target_uploaded, final_uploaded, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (src_hash.lower(), dst_hash.lower(), str(mode), int(src_up), int(dst_up), int(final_up), time.time())
                    )
                    conn.commit()
            except Exception as e:
                write_error_log("add_merger_record", e)

    def get_merger_history(self, src_hash, dst_hash):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    rows = conn.execute(
                        """SELECT * FROM merger_history
                           WHERE source_hash = ? AND target_hash = ?
                           ORDER BY id DESC""",
                        (src_hash.lower(), dst_hash.lower())
                    ).fetchall()
                    return [dict(r) for r in rows]
            except Exception:
                return []


app_state_db = AppStateDB()