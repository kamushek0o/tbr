# core/sessions.py
import time
import secrets
import threading
import ipaddress
from core.profiles_db import profiles_db
from utils.helpers import write_error_log


class SessionAndRateManager:
    def __init__(self):
        self._rate_lock = threading.Lock()
        self._login_fails = {}   # { ip: [ts, ...] }
        self._token_fails = {}   # { ip: [ts, ...] }
        self._init_table()

    def _init_table(self):
        with profiles_db._lock:
            try:
                with profiles_db._get_conn() as conn:
                    conn.executescript("""
                        CREATE TABLE IF NOT EXISTS user_sessions (
                            sid TEXT PRIMARY KEY,
                            profile_id INTEGER NOT NULL,
                            ip TEXT NOT NULL,
                            user_agent TEXT NOT NULL,
                            created_at REAL NOT NULL,
                            last_seen REAL NOT NULL,
                            revoked INTEGER NOT NULL DEFAULT 0,
                            FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE
                        );
                        CREATE INDEX IF NOT EXISTS idx_sessions_prof ON user_sessions(profile_id, revoked);
                    """)
                    conn.commit()
            except Exception as e:
                write_error_log("Инициализация user_sessions", e)

    @staticmethod
    def is_whitelisted_ip(ip_str):
        s = str(ip_str or '').strip().lower()
        if s in ('', '127.0.0.1', '::1', 'localhost'):
            return True
        try:
            obj = ipaddress.ip_address(s)
            return obj.is_loopback or obj.is_private
        except ValueError:
            return False

    def check_rate_limit(self, ip, bucket='login'):
        if self.is_whitelisted_ip(ip):
            return True
        now = time.time()
        window = 600 if bucket == 'login' else 300
        max_att = 5 if bucket == 'login' else 15
        store = self._login_fails if bucket == 'login' else self._token_fails
        with self._rate_lock:
            hist = [t for t in store.get(ip, []) if (now - t) < window]
            store[ip] = hist
            return len(hist) < max_att

    def record_failure(self, ip, bucket='login'):
        if self.is_whitelisted_ip(ip):
            return
        now = time.time()
        window = 600 if bucket == 'login' else 300
        store = self._login_fails if bucket == 'login' else self._token_fails
        with self._rate_lock:
            hist = [t for t in store.get(ip, []) if (now - t) < window]
            hist.append(now)
            store[ip] = hist

    def clear_failures(self, ip, bucket='login'):
        store = self._login_fails if bucket == 'login' else self._token_fails
        with self._rate_lock:
            store.pop(ip, None)

    def create_session(self, profile_id, ip, user_agent):
        sid = secrets.token_urlsafe(24)
        now = time.time()
        ua = str(user_agent or 'Unknown')[:220]
        with profiles_db._lock:
            try:
                with profiles_db._get_conn() as conn:
                    conn.execute(
                        """INSERT INTO user_sessions (sid, profile_id, ip, user_agent, created_at, last_seen, revoked)
                           VALUES (?, ?, ?, ?, ?, ?, 0)""",
                        (sid, int(profile_id), str(ip)[:64], ua, now, now)
                    )
                    conn.commit()
                    return sid
            except Exception as e:
                write_error_log("create_session", e)
                return sid

    def validate_and_touch(self, sid):
        if not sid:
            return False
        now = time.time()
        with profiles_db._lock:
            try:
                with profiles_db._get_conn() as conn:
                    row = conn.execute("SELECT revoked, last_seen FROM user_sessions WHERE sid = ?", (sid,)).fetchone()
                    if not row or row['revoked']:
                        return False
                    if (now - float(row['last_seen'] or 0)) >= 30.0:
                        conn.execute("UPDATE user_sessions SET last_seen = ? WHERE sid = ?", (now, sid))
                        conn.commit()
                    return True
            except Exception:
                return True

    def revoke_session(self, sid):
        if not sid:
            return False
        with profiles_db._lock:
            try:
                with profiles_db._get_conn() as conn:
                    cur = conn.execute("UPDATE user_sessions SET revoked = 1 WHERE sid = ?", (sid,))
                    conn.commit()
                    return cur.rowcount > 0
            except Exception:
                return False

    def revoke_other_sessions(self, current_sid, profile_id=None):
        with profiles_db._lock:
            try:
                with profiles_db._get_conn() as conn:
                    if profile_id is not None:
                        cur = conn.execute(
                            "UPDATE user_sessions SET revoked = 1 WHERE profile_id = ? AND sid != ? AND revoked = 0",
                            (int(profile_id), str(current_sid or ''))
                        )
                    else:
                        cur = conn.execute(
                            "UPDATE user_sessions SET revoked = 1 WHERE sid != ? AND revoked = 0",
                            (str(current_sid or ''),)
                        )
                    conn.commit()
                    return cur.rowcount
            except Exception:
                return 0

    def list_active_sessions(self, current_sid='', profile_id=None):
        cutoff = time.time() - (30 * 86400)
        with profiles_db._lock:
            try:
                with profiles_db._get_conn() as conn:
                    if profile_id is not None:
                        rows = conn.execute(
                            """SELECT s.*, p.name AS profile_name, p.login AS profile_login, p.role AS profile_role
                               FROM user_sessions s JOIN profiles p ON p.id = s.profile_id
                               WHERE s.revoked = 0 AND s.last_seen >= ? AND s.profile_id = ?
                               ORDER BY s.last_seen DESC""",
                            (cutoff, int(profile_id))
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            """SELECT s.*, p.name AS profile_name, p.login AS profile_login, p.role AS profile_role
                               FROM user_sessions s JOIN profiles p ON p.id = s.profile_id
                               WHERE s.revoked = 0 AND s.last_seen >= ?
                               ORDER BY s.last_seen DESC""",
                            (cutoff,)
                        ).fetchall()
                    out = []
                    for r in rows:
                        d = dict(r)
                        d['is_current'] = (d['sid'] == current_sid)
                        out.append(d)
                    return out
            except Exception:
                return []


sessions_mgr = SessionAndRateManager()