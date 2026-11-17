# core/profiles_db.py
import os
import hmac
import json
import time
import hashlib
import secrets
import sqlite3
import threading
from copy import deepcopy
from werkzeug.security import generate_password_hash, check_password_hash
from utils.helpers import APP_DATA_DIR, write_error_log

DEFAULT_UI_SETTINGS = {
    "version": 1,
    "theme": "dark",
    "custom_colors": {
        "bg_main": "#121214",
        "bg_panel": "#1a1a20",
        "text": "#ffffff",
        "accent": "#2ecc71"
    },
    "font": "Segoe UI",
    "allow_google_fonts": False,
    "mobile_mode": True,
    "charts": {
        "daily": {"color": "#2ecc71", "gradient": False, "opacity": 0.7},
        "top5": {"color": "#e67e22", "gradient": False, "opacity": 0.7},
        "hourly": {"color": "#3498db", "gradient": True, "opacity": 0.2}
    },
    "summary_columns": {
        "visible": ["name", "size", "uploaded", "ratio", "speed_all_time", "speed_1h", "speed_24h", "vol_hour", "vol_day", "ratio_h_all", "created"],
        "order": ["name", "size", "uploaded", "ratio", "speed_all_time", "speed_1h", "speed_24h", "vol_hour", "vol_day", "ratio_h_all", "created"],
        "widths": {}
    }
}


def merge_ui_defaults(raw_json):
    result = deepcopy(DEFAULT_UI_SETTINGS)
    if not raw_json:
        return result
    try:
        data = json.loads(raw_json) if isinstance(raw_json, str) else dict(raw_json)
    except Exception:
        return result

    def deep_merge(dst, src):
        for k, v in src.items():
            if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
                deep_merge(dst[k], v)
            else:
                dst[k] = v

    if isinstance(data, dict):
        deep_merge(result, data)
    result["version"] = DEFAULT_UI_SETTINGS["version"]
    return result


def hash_token(raw_token):
    return hashlib.sha256(str(raw_token).encode('utf-8')).hexdigest()


def hash_password_salted(raw_token):
    return generate_password_hash(str(raw_token), method='pbkdf2:sha256')


def _verify_stored_token(stored_hash, raw_token):
    if not stored_hash:
        return False, False
    if stored_hash.startswith(('pbkdf2:', 'scrypt:')):
        return check_password_hash(stored_hash, raw_token), False
    # Мягкая проверка старого несолёного SHA-256 с флагом миграции
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
                            role TEXT NOT NULL CHECK(role IN ('admin', 'viewer')),
                            token_hash TEXT UNIQUE NOT NULL,
                            token_prefix TEXT NOT NULL,
                            magic_token_hash TEXT,
                            ui_settings_json TEXT NOT NULL,
                            created_at REAL NOT NULL
                        );
                    """)
                    cur = conn.cursor()
                    cur.execute("PRAGMA table_info(profiles)")
                    cols = {r['name'] for r in cur.fetchall()}
                    if 'magic_token_hash' not in cols:
                        cur.execute("ALTER TABLE profiles ADD COLUMN magic_token_hash TEXT")

                    cur.execute("SELECT COUNT(*) FROM profiles WHERE role = 'admin'")
                    if cur.fetchone()[0] == 0:
                        raw = "tbr_" + secrets.token_urlsafe(24)
                        cur.execute(
                            """INSERT INTO profiles (name, role, token_hash, token_prefix, magic_token_hash, ui_settings_json, created_at)
                               VALUES (?, 'admin', ?, ?, NULL, ?, ?)""",
                            ("Admin", hash_password_salted(raw), raw[:10] + "...", json.dumps(DEFAULT_UI_SETTINGS), time.time())
                        )
                    conn.commit()
            except Exception as e:
                write_error_log("Инициализация profiles.db", e)

    def get_default_admin(self):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM profiles WHERE role = 'admin' ORDER BY id ASC LIMIT 1")
                    row = cur.fetchone()
                    return dict(row) if row else None
            except Exception:
                return None

    def get_by_id(self, profile_id):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM profiles WHERE id = ?", (int(profile_id),))
                    row = cur.fetchone()
                    return dict(row) if row else None
            except Exception:
                return None

    def authenticate_token(self, raw_token):
        if not raw_token or not isinstance(raw_token, str):
            return None
        clean = raw_token.strip()
        if not clean:
            return None
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM profiles")
                    for row in cur.fetchall():
                        ok, needs_upgrade = _verify_stored_token(row['token_hash'], clean)
                        if ok:
                            prof = dict(row)
                            if needs_upgrade:
                                new_h = hash_password_salted(clean)
                                cur.execute("UPDATE profiles SET token_hash = ? WHERE id = ?", (new_h, row['id']))
                                conn.commit()
                                prof['token_hash'] = new_h
                            return prof
                    return None
            except Exception:
                return None

    def authenticate_magic(self, raw_magic):
        if not raw_magic or not isinstance(raw_magic, str):
            return None
        clean = raw_magic.strip()
        if len(clean) < 16:
            return None
        m_hash = hash_token(clean)
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM profiles WHERE magic_token_hash = ? LIMIT 1", (m_hash,))
                    row = cur.fetchone()
                    return dict(row) if row else None
            except Exception:
                return None

    def list_profiles(self):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        """SELECT id, name, role, token_prefix,
                                  (magic_token_hash IS NOT NULL AND magic_token_hash != '') AS has_magic,
                                  created_at
                           FROM profiles ORDER BY id ASC"""
                    )
                    return [dict(r) for r in cur.fetchall()]
            except Exception:
                return []

    def create_profile(self, name, role, custom_token=None):
        role = 'admin' if role == 'admin' else 'viewer'
        clean_name = str(name or '').strip()[:48] or ('Admin' if role == 'admin' else 'Viewer')
        custom = str(custom_token or '').strip()

        if custom:
            if len(custom) < 3:
                return None, None, None, "Пароль должен быть не короче 3 символов"
            raw_token = custom
            prefix = (raw_token[:2] + "***") if len(raw_token) <= 6 else (raw_token[:4] + "...")
        else:
            raw_token = "tbr_" + secrets.token_urlsafe(24)
            prefix = raw_token[:10] + "..."

        if self.authenticate_token(raw_token):
            return None, None, None, "Такой пароль/токен уже занят другим профилем!"

        # Для Viewer сразу генерируем отдельную 1-клик ссылку; для Admin — только по явному запросу
        raw_magic = ("m_" + secrets.token_urlsafe(24)) if role == 'viewer' else None
        m_hash = hash_token(raw_magic) if raw_magic else None
        p_hash = hash_password_salted(raw_token)

        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        """INSERT INTO profiles (name, role, token_hash, token_prefix, magic_token_hash, ui_settings_json, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (clean_name, role, p_hash, prefix, m_hash, json.dumps(DEFAULT_UI_SETTINGS), time.time())
                    )
                    conn.commit()
                    return cur.lastrowid, raw_token, raw_magic, None
            except Exception as e:
                write_error_log("Ошибка create_profile", e)
                return None, None, None, str(e)

    def change_password(self, profile_id, new_password=None):
        custom = str(new_password or '').strip()
        if custom:
            if len(custom) < 3:
                return None, None, "Пароль должен быть не короче 3 символов"
            raw_token = custom
            prefix = (raw_token[:2] + "***") if len(raw_token) <= 6 else (raw_token[:4] + "...")
        else:
            raw_token = "tbr_" + secrets.token_urlsafe(24)
            prefix = raw_token[:10] + "..."

        existing = self.authenticate_token(raw_token)
        if existing and existing['id'] != int(profile_id):
            return None, None, "Такой пароль уже занят другим профилем!"

        p_hash = hash_password_salted(raw_token)
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE profiles SET token_hash = ?, token_prefix = ?, magic_token_hash = NULL WHERE id = ?",
                        (p_hash, prefix, int(profile_id))
                    )
                    conn.commit()
                    if cur.rowcount > 0:
                        return raw_token, None, None
                    return None, None, "Профиль не найден"
            except Exception as e:
                write_error_log("Ошибка change_password", e)
                return None, None, str(e)

    def reissue_magic_token(self, profile_id):
        raw_magic = "m_" + secrets.token_urlsafe(24)
        m_hash = hash_token(raw_magic)
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("UPDATE profiles SET magic_token_hash = ? WHERE id = ?", (m_hash, int(profile_id)))
                    conn.commit()
                    return raw_magic if cur.rowcount > 0 else None
            except Exception as e:
                write_error_log("Ошибка reissue_magic_token", e)
                return None

    def reissue_token(self, profile_id):
        raw_token, _, _ = self.change_password(profile_id, new_password=None)
        return raw_token, None

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
                write_error_log("Ошибка delete_profile", e)
                return False, str(e)

    def get_ui_settings(self, profile_id):
        p = self.get_by_id(profile_id)
        return merge_ui_defaults(p['ui_settings_json'] if p else None)

    def save_ui_settings(self, profile_id, new_settings):
        merged = merge_ui_defaults(new_settings)
        with self._lock:
            try:
                with self._get_conn() as conn:
                    conn.execute(
                        "UPDATE profiles SET ui_settings_json = ? WHERE id = ?",
                        (json.dumps(merged, ensure_ascii=False), int(profile_id))
                    )
                    conn.commit()
                    return merged
            except Exception as e:
                write_error_log("Ошибка save_ui_settings", e)
                return merged

    def reset_admin_token_local(self):
        adm = self.get_default_admin()
        if not adm:
            self._init_db()
            adm = self.get_default_admin()
        if not adm:
            return None
        raw, _ = self.reissue_token(adm['id'])
        return raw


profiles_db = ProfilesDB()