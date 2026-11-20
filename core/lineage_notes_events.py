# core/lineage_notes_events.py
import time
import datetime
import threading
from collections import deque
from core.app_state_db import app_state_db
from utils.helpers import write_error_log

_TICKER_LOCK = threading.Lock()
_TICKER_BUF = deque(maxlen=80)
_EVENT_DEBOUNCE = {}  # (uid, event_type) -> ts


def _ensure_tables():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS torrent_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        uid TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        title TEXT NOT NULL,
                        created_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_tor_ev_uid ON torrent_events(uid, created_at DESC);

                    CREATE TABLE IF NOT EXISTS torrent_notes (
                        uid TEXT PRIMARY KEY,
                        note TEXT NOT NULL,
                        last_name TEXT NOT NULL DEFAULT '',
                        updated_at REAL NOT NULL
                    );
                """)
                conn.commit()
        except Exception as e:
            write_error_log("lineage_notes_events init", e)


_ensure_tables()


def resolve_uid(t_hash):
    hl = str(t_hash or '').strip().lower()
    if not hl:
        return ''
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                row = conn.execute("SELECT torrent_uid FROM torrent_lineage WHERE torrent_hash = ?", (hl,)).fetchone()
                return row['torrent_uid'] if row else hl
        except Exception:
            return hl


def push_activity(category, text, t_hash=''):
    """#44 Живой пульс событий (кольцевой буфер на 80 записей)."""
    with _TICKER_LOCK:
        _TICKER_BUF.appendleft({
            'ts': int(time.time()),
            'time': datetime.datetime.now().strftime('%H:%M:%S'),
            'category': str(category),
            'text': str(text)[:180],
            'hash': str(t_hash or '').lower()
        })


def get_activity_feed(hidden_hashes=None):
    hidden = {h.lower() for h in (hidden_hashes or set())}
    with _TICKER_LOCK:
        return [ev for ev in _TICKER_BUF if not ev['hash'] or ev['hash'] not in hidden]


def record_torrent_event(t_hash, event_type, title):
    """#15 Биография раздачи по uid (с дебаунсом 60с от миганий сети)."""
    uid = resolve_uid(t_hash)
    if not uid:
        return
    now = time.time()
    key = (uid, str(event_type))
    if (now - _EVENT_DEBOUNCE.get(key, 0)) < 60.0:
        return
    _EVENT_DEBOUNCE[key] = now

    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute(
                    "INSERT INTO torrent_events (uid, event_type, title, created_at) VALUES (?, ?, ?, ?)",
                    (uid, str(event_type)[:32], str(title)[:240], now)
                )
                conn.commit()
        except Exception:
            pass
    push_activity(event_type, title, t_hash=t_hash)


def get_torrent_timeline(t_hash):
    uid = resolve_uid(t_hash)
    if not uid:
        return []
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = conn.execute(
                    "SELECT event_type, title, created_at FROM torrent_events WHERE uid = ? ORDER BY created_at DESC LIMIT 100",
                    (uid,)
                ).fetchall()
                out = []
                for r in rows:
                    d = dict(r)
                    d['date'] = datetime.datetime.fromtimestamp(d['created_at']).strftime('%Y-%m-%d %H:%M')
                    out.append(d)
                return out
        except Exception:
            return []


def get_torrent_note(t_hash):
    uid = resolve_uid(t_hash)
    if not uid:
        return ''
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                row = conn.execute("SELECT note FROM torrent_notes WHERE uid = ?", (uid,)).fetchone()
                return row['note'] if row else ''
        except Exception:
            return ''


def set_torrent_note(t_hash, note_text, last_name=''):
    uid = resolve_uid(t_hash)
    if not uid:
        return False
    clean = str(note_text or '').strip()[:2000]
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                if not clean:
                    conn.execute("DELETE FROM torrent_notes WHERE uid = ?", (uid,))
                else:
                    conn.execute(
                        "INSERT OR REPLACE INTO torrent_notes (uid, note, last_name, updated_at) VALUES (?, ?, ?, ?)",
                        (uid, clean, str(last_name or '')[:160], time.time())
                    )
                conn.commit()
                return True
        except Exception:
            return False


def list_all_notes(hidden_uids=None):
    hidden = {u.lower() for u in (hidden_uids or set())}
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = conn.execute("SELECT * FROM torrent_notes ORDER BY updated_at DESC").fetchall()
                return [dict(r) for r in rows if r['uid'] not in hidden]
        except Exception:
            return []