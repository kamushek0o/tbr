# core/profiles_db.py
import os
import hmac
import json
import time
import hashlib
import secrets
import sqlite3
import threading
from werkzeug.security import generate_password_hash, check_password_hash
from utils.helpers import APP_DATA_DIR, write_error_log
from core.ui_defaults import DEFAULT_UI_SETTINGS, merge_ui_defaults


def hash_token(raw_token):
    return hashlib.sha256(str(raw_token).encode('utf-8')).hexdigest()


def hash_password_salted(raw_token):
    return generate_password_hash(str(raw_token), method='pbkdf2:sha256')


def _verify_stored_token(stored_hash, raw_token):
    if not stored_hash:
        return False, False
    if stored_hash.startswith(('pbkdf2:', 'scrypt:')):
        return check_password_hash(stored_hash, raw_token), False
    legacy_ok = hmac.compare_digest(stored_hash.lower(), hash_token(raw_token).lower())
    return legacy_ok, legacy_ok


class ProfilesDB:
    def __init__(self):
        self.db_file = os.path.join(APP_DATA_DIR, "profiles.db")
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
                        CREATE TABLE IF NOT EXISTS profiles (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT NOT NULL,
                            login TEXT,
                            role TEXT NOT NULL CHECK(role IN ('admin', 'viewer')),
                            token_hash TEXT NOT NULL,
                            token_prefix TEXT NOT NULL,
                            api_token TEXT,
                            ui_settings_json TEXT NOT NULL,
                            created_at REAL NOT NULL
                        );
                        CREATE TABLE IF NOT EXISTS invites (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            profile_id INTEGER NOT NULL,
                            token_hash TEXT UNIQUE NOT NULL,
                            expires_at REAL NOT NULL,
                            used_at REAL,
                            FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE
                        );
                    """)
                    cur = conn.cursor()
                    cur.execute("PRAGMA table_info(profiles)")
                    cols = {r['name'] for r in cur.fetchall()}
                    if 'login' not in cols:
                        cur.execute("ALTER TABLE profiles ADD COLUMN login TEXT")
                    if 'api_token' not in cols:
                        cur.execute("ALTER TABLE profiles ADD COLUMN api_token TEXT")

                    cur.execute("SELECT id, name, login, api_token FROM profiles ORDER BY id ASC")
                    rows = cur.fetchall()
                    used_logins = {r['login'].lower() for r in rows if r['login']}
                    for r in rows:
                        if not r['login']:
                            base = ''.join(c for c in str(r['name'] or 'user').lower() if c.isalnum() or c in ('_', '-'))[:24] or 'user'
                            cand = base
                            if cand in used_logins:
                                cand = f"{base}_{r['id']}"
                            used_logins.add(cand)
                            cur.execute("UPDATE profiles SET login = ? WHERE id = ?", (cand, r['id']))
                        if not r['api_token']:
                            cur.execute("UPDATE profiles SET api_token = ? WHERE id = ?", ("tbr_api_" + secrets.token_urlsafe(24), r['id']))

                    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_login ON profiles(login)")
                    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_api_token ON profiles(api_token)")

                    cur.execute("SELECT COUNT(*) FROM profiles WHERE role = 'admin'")
                    if cur.fetchone()[0] == 0:
                        raw = "tbr_" + secrets.token_urlsafe(18)
                        api_tok = "tbr_api_" + secrets.token_urlsafe(24)
                        cur.execute(
                            """INSERT INTO profiles (name, login, role, token_hash, token_prefix, api_token, ui_settings_json, created_at)
                               VALUES (?, ?, 'admin', ?, ?, ?, ?, ?)""",
                            ("Admin", "admin", hash_password_salted(raw), raw[:8] + "...", api_tok, json.dumps(DEFAULT_UI_SETTINGS), time.time())
                        )
                    conn.commit()
            except Exception as e:
                write_error_log("Инициализация profiles.db", e)

    def get_default_admin(self):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    row = conn.execute("SELECT * FROM profiles WHERE role = 'admin' ORDER BY id ASC LIMIT 1").fetchone()
                    return dict(row) if row else None
            except Exception:
                return None

    def get_by_id(self, profile_id):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    row = conn.execute("SELECT * FROM profiles WHERE id = ?", (int(profile_id),)).fetchone()
                    return dict(row) if row else None
            except Exception:
                return None

    def authenticate_login(self, login, password):
        clean_login = str(login or '').strip().lower()
        clean_pwd = str(password or '').strip()
        if not clean_login or not clean_pwd:
            return None
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM profiles WHERE lower(login) = ? LIMIT 1", (clean_login,))
                    row = cur.fetchone()
                    if not row:
                        return None
                    ok, needs_upgrade = _verify_stored_token(row['token_hash'], clean_pwd)
                    if not ok:
                        return None
                    prof = dict(row)
                    if needs_upgrade:
                        new_h = hash_password_salted(clean_pwd)
                        cur.execute("UPDATE profiles SET token_hash = ? WHERE id = ?", (new_h, row['id']))
                        conn.commit()
                        prof['token_hash'] = new_h
                    return prof
            except Exception:
                return None

    def authenticate_api_token(self, raw_token):
        clean = str(raw_token or '').strip()
        if not clean:
            return None
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM profiles WHERE api_token = ? LIMIT 1", (clean,))
                    row = cur.fetchone()
                    if row:
                        return dict(row)
                    cur.execute("SELECT * FROM profiles")
                    for r in cur.fetchall():
                        ok, needs_upgrade = _verify_stored_token(r['token_hash'], clean)
                        if ok:
                            prof = dict(r)
                            if needs_upgrade:
                                cur.execute("UPDATE profiles SET token_hash = ? WHERE id = ?", (hash_password_salted(clean), r['id']))
                                conn.commit()
                            return prof
                    return None
            except Exception:
                return None

    def authenticate_token(self, raw_token):
        return self.authenticate_api_token(raw_token)

    def list_profiles(self):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, name, login, role, token_prefix, api_token, created_at FROM profiles ORDER BY id ASC")
                    return [dict(r) for r in cur.fetchall()]
            except Exception:
                return []

    def create_profile(self, name, role, login=None, password=None):
        role = 'admin' if role == 'admin' else 'viewer'
        clean_name = str(name or '').strip()[:48] or ('Admin' if role == 'admin' else 'Viewer')
        clean_login = ''.join(c for c in str(login or clean_name).strip().lower() if c.isalnum() or c in ('_', '-', '.'))[:32]
        if len(clean_login) < 2:
            return None, None, None, "Логин должен быть не короче 2 символов"

        raw_pwd = str(password or '').strip() or ("tbr_" + secrets.token_urlsafe(12))
        if len(raw_pwd) < 3:
            return None, None, None, "Пароль должен быть не короче 3 символов"

        api_tok = "tbr_api_" + secrets.token_urlsafe(24)
        prefix = (raw_pwd[:2] + "***") if len(raw_pwd) <= 6 else (raw_pwd[:4] + "...")

        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        """INSERT INTO profiles (name, login, role, token_hash, token_prefix, api_token, ui_settings_json, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (clean_name, clean_login, role, hash_password_salted(raw_pwd), prefix, api_tok, json.dumps(DEFAULT_UI_SETTINGS), time.time())
                    )
                    conn.commit()
                    return cur.lastrowid, raw_pwd, api_tok, None
            except sqlite3.IntegrityError:
                return None, None, None, "Такой логин уже занят!"
            except Exception as e:
                write_error_log("Ошибка create_profile", e)
                return None, None, None, str(e)

    def change_password(self, profile_id, new_password=None, new_login=None):
        raw_pwd = str(new_password or '').strip() or ("tbr_" + secrets.token_urlsafe(12))
        if len(raw_pwd) < 3:
            return None, "Пароль должен быть не короче 3 символов"
        prefix = (raw_pwd[:2] + "***") if len(raw_pwd) <= 6 else (raw_pwd[:4] + "...")
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    if new_login:
                        clean_login = ''.join(c for c in str(new_login).strip().lower() if c.isalnum() or c in ('_', '-', '.'))[:32]
                        if len(clean_login) < 2:
                            return None, "Логин должен быть не короче 2 символов"
                        cur.execute(
                            "UPDATE profiles SET login = ?, token_hash = ?, token_prefix = ? WHERE id = ?",
                            (clean_login, hash_password_salted(raw_pwd), prefix, int(profile_id))
                        )
                    else:
                        cur.execute(
                            "UPDATE profiles SET token_hash = ?, token_prefix = ? WHERE id = ?",
                            (hash_password_salted(raw_pwd), prefix, int(profile_id))
                        )
                    conn.commit()
                    return (raw_pwd, None) if cur.rowcount > 0 else (None, "Профиль не найден")
            except sqlite3.IntegrityError:
                return None, "Такой логин уже занят!"
            except Exception as e:
                return None, str(e)

    def reissue_api_token(self, profile_id):
        new_api = "tbr_api_" + secrets.token_urlsafe(24)
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("UPDATE profiles SET api_token = ? WHERE id = ?", (new_api, int(profile_id)))
                    conn.commit()
                    return new_api if cur.rowcount > 0 else None
            except Exception:
                return None

    def create_invite(self, profile_id, ttl_hours=24):
        raw_inv = "inv_" + secrets.token_urlsafe(24)
        with self._lock:
            try:
                with self._get_conn() as conn:
                    conn.execute(
                        "INSERT INTO invites (profile_id, token_hash, expires_at, used_at) VALUES (?, ?, ?, NULL)",
                        (int(profile_id), hash_token(raw_inv), time.time() + ttl_hours * 3600)
                    )
                    conn.commit()
                    return raw_inv
            except Exception as e:
                write_error_log("Ошибка create_invite", e)
                return None

    def get_valid_invite(self, raw_inv):
        if not raw_inv:
            return None
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        """SELECT i.id AS invite_id, i.profile_id, i.expires_at, i.used_at, p.name, p.login, p.role
                           FROM invites i JOIN profiles p ON p.id = i.profile_id
                           WHERE i.token_hash = ? LIMIT 1""",
                        (hash_token(raw_inv.strip()),)
                    )
                    row = cur.fetchone()
                    if not row or row['used_at'] is not None or time.time() > row['expires_at']:
                        return None
                    return dict(row)
            except Exception:
                return None

    def consume_invite(self, raw_inv, new_login, new_password):
        inv = self.get_valid_invite(raw_inv)
        if not inv:
            return None, "Инвайт недействителен, просрочен или уже использован"
        _, err = self.change_password(inv['profile_id'], new_password=new_password, new_login=new_login)
        if err:
            return None, err
        with self._lock:
            try:
                with self._get_conn() as conn:
                    conn.execute("UPDATE invites SET used_at = ? WHERE id = ?", (time.time(), inv['invite_id']))
                    conn.commit()
            except Exception:
                pass
        return self.get_by_id(inv['profile_id']), None

    def delete_profile(self, profile_id):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT role FROM profiles WHERE id = ?", (int(profile_id),))
                    row = cur.fetchone()
                    if not row:
                        return False, "Профиль не найден"
                    if row['role'] == 'admin':
                        cur.execute("SELECT COUNT(*) FROM profiles WHERE role = 'admin'")
                        if cur.fetchone()[0] <= 1:
                            return False, "Нельзя удалить последнего администратора!"
                    cur.execute("DELETE FROM profiles WHERE id = ?", (int(profile_id),))
                    conn.commit()
                    return True, "Профиль удалён"
            except Exception as e:
                return False, str(e)

    def get_ui_settings(self, profile_id):
        p = self.get_by_id(profile_id)
        return merge_ui_defaults(p['ui_settings_json'] if p else None)

    def save_ui_settings(self, profile_id, new_settings):
        merged = merge_ui_defaults(new_settings)
        with self._lock:
            try:
                with self._get_conn() as conn:
                    conn.execute("UPDATE profiles SET ui_settings_json = ? WHERE id = ?", (json.dumps(merged, ensure_ascii=False), int(profile_id)))
                    conn.commit()
            except Exception as e:
                write_error_log("Ошибка save_ui_settings", e)
        return merged

    def reset_admin_token_local(self):
        adm = self.get_default_admin() or (self._init_db() or self.get_default_admin())
        if not adm:
            return None
        raw, _ = self.change_password(adm['id'])
        return raw


profiles_db = ProfilesDB()