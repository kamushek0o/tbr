# core/tuner_db.py
import json
import time
from copy import deepcopy
from core.app_state_db import app_state_db
from utils.helpers import write_error_log

ALLOWED_PREFS_KEYS = (
    'max_uploads', 'max_uploads_per_torrent',
    'max_connec', 'max_connec_per_torrent',
    'max_active_uploads', 'up_limit', 'dl_limit'
)

DEFAULT_PROFILES = {
    'performance': {
        'max_uploads_min': 15, 'max_uploads_max': 150, 'max_uploads_start': 40,
        'per_torrent_up_min': 4, 'per_torrent_up_max': 40, 'per_torrent_up_auto': True,
        'max_connec_min': 60, 'max_connec_max': 600, 'max_connec_auto': True,
        'per_torrent_connec_min': 15, 'per_torrent_connec_max': 150,
        'active_uploads_mode': 'keep', 'active_uploads_min': 10, 'active_uploads_max': 40,
        'channel_target_min': 85, 'channel_target_max': 100,
        'up_limit_pct': 0, 'dl_limit_pct': 0, 'squeeze_enabled': False, 'squeeze_up_pct': 70, 'squeeze_dl_pct': 70,
        'cooldown_sec': 180, 'step_up_size': 5,
        'yield_to_turtle': True,
        'guards': {
            'disk': {'enabled': False, 'warn': 85, 'crit': 95, 'recover': 70},
            'cpu':  {'enabled': True,  'warn': 85, 'recover': 65},
            'ram':  {'enabled': True,  'min_free': 10, 'recover_free': 18},
            'net':  {'enabled': False, 'warn_pct': 45, 'recover_pct': 25},
        }
    },
    'comfort': {
        'max_uploads_min': 8, 'max_uploads_max': 45, 'max_uploads_start': 20,
        'per_torrent_up_min': 3, 'per_torrent_up_max': 15, 'per_torrent_up_auto': True,
        'max_connec_min': 40, 'max_connec_max': 220, 'max_connec_auto': True,
        'per_torrent_connec_min': 10, 'per_torrent_connec_max': 50,
        'active_uploads_mode': 'range', 'active_uploads_min': 4, 'active_uploads_max': 15,
        'channel_target_min': 55, 'channel_target_max': 75,
        'up_limit_pct': 75, 'dl_limit_pct': 75, 'squeeze_enabled': True, 'squeeze_up_pct': 40, 'squeeze_dl_pct': 40,
        'cooldown_sec': 180, 'step_up_size': 3,
        'yield_to_turtle': True,
        'guards': {
            'disk': {'enabled': True, 'warn': 55, 'crit': 80, 'recover': 35},
            'cpu':  {'enabled': True, 'warn': 45, 'recover': 30},
            'ram':  {'enabled': True, 'min_free': 20, 'recover_free': 28},
            'net':  {'enabled': True, 'warn_pct': 20, 'recover_pct': 10},
        }
    }
}

DEFAULT_SWITCH_RULES = {
    'default_mode': 'performance',
    'override_policy': '2h',  # '2h' | 'until_schedule' | 'until_process_exit'
    'schedules': [],  # [{start: "01:00", end: "08:00", days: [0..6], mode: "performance"}]
    'processes': {
        'enabled': False,
        'target_mode': 'comfort',
        'names': ['cs2.exe', 'dota2.exe', 'obs64.exe'],
        'enter_sec': 15,
        'exit_sec': 180
    },
    'external_load': {
        'enabled': False,
        'target_mode': 'comfort',
        'cpu_warn': 45, 'cpu_recover': 25,
        'net_warn_pct': 25, 'net_recover_pct': 12,
        'ram_min_free': 15, 'ram_recover_free': 25,
        'enter_sec': 30,
        'exit_sec': 300
    }
}


def _merge_dict(base, patch):
    res = deepcopy(base)
    if not isinstance(patch, dict):
        return res
    for k, v in patch.items():
        if k in res and isinstance(res[k], dict) and isinstance(v, dict):
            res[k] = _merge_dict(res[k], v)
        else:
            res[k] = v
    return res


def ensure_tuner_tables():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS tuner_state (
                        id INTEGER PRIMARY KEY CHECK(id = 1),
                        mode TEXT NOT NULL DEFAULT 'off',
                        auto_switch_enabled INTEGER NOT NULL DEFAULT 0,
                        manual_override_until REAL NOT NULL DEFAULT 0,
                        manual_override_mode TEXT NOT NULL DEFAULT '',
                        manual_override_policy TEXT NOT NULL DEFAULT '2h',
                        baseline_json TEXT NOT NULL DEFAULT '{}',
                        current_limits_json TEXT NOT NULL DEFAULT '{}',
                        dirty_flag INTEGER NOT NULL DEFAULT 0,
                        cooldown_until REAL NOT NULL DEFAULT 0,
                        last_action_ts REAL NOT NULL DEFAULT 0,
                        last_reason TEXT NOT NULL DEFAULT 'Выключен'
                    );
                    CREATE TABLE IF NOT EXISTS tuner_profiles (
                        mode TEXT PRIMARY KEY,
                        profile_json TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS tuner_switch_rules (
                        id INTEGER PRIMARY KEY CHECK(id = 1),
                        rules_json TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS tuner_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts REAL NOT NULL,
                        mode TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        disk_busy REAL NOT NULL DEFAULT 0,
                        cpu_ext REAL NOT NULL DEFAULT 0,
                        ram_free REAL NOT NULL DEFAULT 0,
                        net_pct REAL NOT NULL DEFAULT 0,
                        old_slots INTEGER NOT NULL DEFAULT 0,
                        new_slots INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE INDEX IF NOT EXISTS idx_tuner_hist_ts ON tuner_history(ts DESC);
                """)
                conn.execute("INSERT OR IGNORE INTO tuner_state (id) VALUES (1)")
                now = time.time()
                for m, prof in DEFAULT_PROFILES.items():
                    conn.execute(
                        "INSERT OR IGNORE INTO tuner_profiles (mode, profile_json, updated_at) VALUES (?, ?, ?)",
                        (m, json.dumps(prof, ensure_ascii=False), now)
                    )
                conn.execute(
                    "INSERT OR IGNORE INTO tuner_switch_rules (id, rules_json, updated_at) VALUES (1, ?, ?)",
                    (json.dumps(DEFAULT_SWITCH_RULES, ensure_ascii=False), now)
                )
        except Exception as e:
            write_error_log("ensure_tuner_tables", e)


ensure_tuner_tables()


def get_tuner_state():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                row = conn.execute("SELECT * FROM tuner_state WHERE id = 1").fetchone()
                if row:
                    d = dict(row)
                    d['baseline'] = json.loads(d.get('baseline_json') or '{}')
                    d['current_limits'] = json.loads(d.get('current_limits_json') or '{}')
                    return d
        except Exception as e:
            write_error_log("get_tuner_state", e)
    return {'id': 1, 'mode': 'off', 'auto_switch_enabled': 0, 'dirty_flag': 0, 'baseline': {}, 'current_limits': {}, 'last_reason': 'Выключен'}


def update_tuner_state(**fields):
    allowed = {
        'mode', 'auto_switch_enabled', 'manual_override_until', 'manual_override_mode',
        'manual_override_policy', 'baseline_json', 'current_limits_json', 'dirty_flag',
        'cooldown_until', 'last_action_ts', 'last_reason'
    }
    upd = {k: v for k, v in fields.items() if k in allowed}
    if not upd:
        return
    with app_state_db._lock:
        try:
            clause = ", ".join(f"{k} = ?" for k in upd)
            with app_state_db._get_conn() as conn:
                conn.execute(f"UPDATE tuner_state SET {clause} WHERE id = 1", list(upd.values()))
        except Exception as e:
            write_error_log("update_tuner_state", e)


def get_tuner_profiles():
    res = deepcopy(DEFAULT_PROFILES)
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                for r in conn.execute("SELECT mode, profile_json FROM tuner_profiles").fetchall():
                    if r['mode'] in res:
                        res[r['mode']] = _merge_dict(res[r['mode']], json.loads(r['profile_json'] or '{}'))
        except Exception:
            pass
    return res


def save_tuner_profile(mode, profile_dict):
    if mode not in DEFAULT_PROFILES:
        return None
    merged = _merge_dict(DEFAULT_PROFILES[mode], profile_dict)
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO tuner_profiles (mode, profile_json, updated_at) VALUES (?, ?, ?)",
                    (mode, json.dumps(merged, ensure_ascii=False), time.time())
                )
        except Exception as e:
            write_error_log("save_tuner_profile", e)
    return merged


def reset_tuner_profile(mode):
    if mode not in DEFAULT_PROFILES:
        return None
    return save_tuner_profile(mode, DEFAULT_PROFILES[mode])


def get_switch_rules():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                row = conn.execute("SELECT rules_json FROM tuner_switch_rules WHERE id = 1").fetchone()
                if row:
                    return _merge_dict(DEFAULT_SWITCH_RULES, json.loads(row['rules_json'] or '{}'))
        except Exception:
            pass
    return deepcopy(DEFAULT_SWITCH_RULES)


def save_switch_rules(rules_dict):
    merged = _merge_dict(DEFAULT_SWITCH_RULES, rules_dict)
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO tuner_switch_rules (id, rules_json, updated_at) VALUES (1, ?, ?)",
                    (json.dumps(merged, ensure_ascii=False), time.time())
                )
        except Exception as e:
            write_error_log("save_switch_rules", e)
    return merged


def add_tuner_history(mode, event_type, reason, metrics, old_slots, new_slots):
    now = time.time()
    cutoff = now - (48 * 3600)
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute(
                    """INSERT INTO tuner_history
                       (ts, mode, event_type, reason, disk_busy, cpu_ext, ram_free, net_pct, old_slots, new_slots)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        now, str(mode), str(event_type), str(reason)[:220],
                        round(float(metrics.get('disk_busy', 0)), 1),
                        round(float(metrics.get('cpu_ext', 0)), 1),
                        round(float(metrics.get('ram_free', 0)), 1),
                        round(float(metrics.get('channel_pct', 0)), 1),
                        int(old_slots or 0), int(new_slots or 0)
                    )
                )
                conn.execute("DELETE FROM tuner_history WHERE ts < ?", (cutoff,))
        except Exception as e:
            write_error_log("add_tuner_history", e)


def get_tuner_history(limit=30):
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = conn.execute("SELECT * FROM tuner_history ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []