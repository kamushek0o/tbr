# core/profiles_auth.py
import hmac
import time
import hashlib
import secrets
from werkzeug.security import generate_password_hash, check_password_hash
from utils.helpers import write_error_log


def hash_token(raw_token):
    return hashlib.sha256(str(raw_token).encode('utf-8')).hexdigest()


def hash_password_salted(raw_token):
    return generate_password_hash(str(raw_token), method='pbkdf2:sha256')


def verify_stored_token(stored_hash, raw_token):
    if not stored_hash:
        return False, False
    if stored_hash.startswith(('pbkdf2:', 'scrypt:')):
        return check_password_hash(stored_hash, raw_token), False
    legacy_ok = hmac.compare_digest(stored_hash.lower(), hash_token(raw_token).lower())
    return legacy_ok, legacy_ok


def create_invite_db(db, profile_id, ttl_hours=24):
    raw_inv = "inv_" + secrets.token_urlsafe(24)
    with db._lock:
        try:
            with db._get_conn() as conn:
                conn.execute(
                    "INSERT INTO invites (profile_id, token_hash, expires_at, used_at) VALUES (?, ?, ?, NULL)",
                    (int(profile_id), hash_token(raw_inv), time.time() + ttl_hours * 3600)
                )
                return raw_inv
        except Exception as e:
            write_error_log("Ошибка create_invite", e)
            return None


def get_valid_invite_db(db, raw_inv):
    if not raw_inv:
        return None
    with db._lock:
        try:
            with db._get_conn() as conn:
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


def consume_invite_db(db, raw_inv, new_login, new_password):
    inv = get_valid_invite_db(db, raw_inv)
    if not inv:
        return None, "Инвайт недействителен, просрочен или уже использован"
    _, err = db.change_password(inv['profile_id'], new_password=new_password, new_login=new_login)
    if err:
        return None, err
    with db._lock:
        try:
            with db._get_conn() as conn:
                conn.execute("UPDATE invites SET used_at = ? WHERE id = ?", (time.time(), inv['invite_id']))
        except Exception:
            pass
    return db.get_by_id(inv['profile_id']), None