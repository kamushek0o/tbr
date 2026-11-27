# core/tuner_db.py
import re
import json
import time
from copy import deepcopy
from core.app_state_db import app_state_db
from core.tuner_presets import BASE_PROFILE_TEMPLATE, BUILTIN_PRESETS, merge_profile_config
from utils.helpers import write_error_log

ALLOWED_PREFS_KEYS = (
    'max_uploads', 'max_uploads_per_torrent',
    'max_connec', 'max_connec_per_torrent',
    'max_active_uploads', 'up_limit', 'dl_limit'
)

DEFAULT_RULE_TEMPLATE = {
    'processes': {'enabled': False, 'names': []},
    'schedule': {'enabled': False, 'start': '01:00', 'end': '08:00', 'days': [0, 1, 2, 3, 4, 5, 6]},
    'external_load': {
        'enabled': False,
        'cpu_enabled': True, 'cpu_warn': 45, 'cpu_recover': 25,
        'net_enabled': True, 'net_warn_pct': 25, 'net_recover_pct': 12,
        'ram_enabled': False, 'ram_min_free': 15, 'ram_recover_free': 25,
        'disk_enabled': False, 'disk_warn': 70, 'disk_recover': 45,
    },
    'enter_sec': 10,
    'exit_sec': 180
}


def _slugify(name):
    s = re.sub(r'[^a-z0-9_]+', '_', str(name or '').lower()).strip('_')
    return s[:28] or f"prof_{int(time.time())}"


def _migrate_old_profiles(conn):
    cols = {r['name'] for r in conn.execute("PRAGMA table_info(tuner_profiles)").fetchall()}
    if not cols or 'id' in cols:
        return
    old_rows = [dict(r) for r in conn.execute("SELECT mode, profile_json, updated_at FROM tuner_profiles").fetchall()]
    conn.execute("DROP TABLE IF EXISTS _old_tuner_profiles")
    conn.execute("ALTER TABLE tuner_profiles RENAME TO _old_tuner_profiles")
    conn.execute("""
        CREATE TABLE tuner_profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            icon TEXT NOT NULL DEFAULT '⚙️',
            is_builtin INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 10,
            config_json TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
    """)
    now = time.time()
    migrated_ids = set()
    for r in old_rows:
        m = r['mode']
        cfg_data = merge_profile_config(BASE_PROFILE_TEMPLATE, json.loads(r.get('profile_json') or '{}'))
        meta = {
            'performance': ('Производительность', '⚡', 2),
            'comfort': ('Комфорт', '🛋️', 4),
        }.get(m, (m.title(), '⚙️', 10))
        conn.execute(
            "INSERT OR REPLACE INTO tuner_profiles (id, name, icon, is_builtin, sort_order, config_json, updated_at) VALUES (?, ?, ?, 1, ?, ?, ?)",
            (m, meta[0], meta[1], meta[2], json.dumps(cfg_data, ensure_ascii=False), float(r.get('updated_at') or now))
        )
        migrated_ids.add(m)
    for idx, p in enumerate(BUILTIN_PRESETS, start=1):
        if p['id'] not in migrated_ids:
            cfg_data = merge_profile_config(BASE_PROFILE_TEMPLATE, p['config'])
            conn.execute(
                "INSERT OR IGNORE INTO tuner_profiles (id, name, icon, is_builtin, sort_order, config_json, updated_at) VALUES (?, ?, ?, 1, ?, ?, ?)",
                (p['id'], p['name'], p['icon'], idx, json.dumps(cfg_data, ensure_ascii=False), now)
            )
    conn.execute("DROP TABLE IF EXISTS _old_tuner_profiles")


def _migrate_old_rules(conn):
    cols = {r['name'] for r in conn.execute("PRAGMA table_info(tuner_switch_rules)").fetchall()}
    if not cols or 'priority' in cols:
        return
    old_row = conn.execute("SELECT rules_json FROM tuner_switch_rules WHERE id = 1").fetchone()
    old_rules = json.loads(old_row['rules_json'] or '{}') if old_row else {}
    conn.execute("DROP TABLE IF EXISTS _old_tuner_switch_rules")
    conn.execute("ALTER TABLE tuner_switch_rules RENAME TO _old_tuner_switch_rules")
    conn.execute("""
        CREATE TABLE tuner_switch_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            priority INTEGER NOT NULL DEFAULT 10,
            name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            target_profile_id TEXT NOT NULL,
            rule_json TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
    """)
    now = time.time()
    def_mode = old_rules.get('default_mode') or 'performance'
    ov_pol = old_rules.get('override_policy') or '2h'
    conn.execute("UPDATE tuner_state SET default_profile_id = ?, manual_override_policy = ? WHERE id = 1", (def_mode, ov_pol))

    prio = 1
    pr = old_rules.get('processes') or {}
    if pr.get('names'):
        rule_cfg = deepcopy(DEFAULT_RULE_TEMPLATE)
        rule_cfg['processes'] = {'enabled': True, 'names': list(pr['names'])}
        rule_cfg['enter_sec'] = int(pr.get('enter_sec', 15) or 15)
        rule_cfg['exit_sec'] = int(pr.get('exit_sec', 180) or 180)
        conn.execute(
            "INSERT INTO tuner_switch_rules (priority, name, enabled, target_profile_id, rule_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (prio, 'Отслеживаемые программы', 1 if pr.get('enabled') else 0, pr.get('target_mode', 'comfort'), json.dumps(rule_cfg, ensure_ascii=False), now)
        )
        prio += 1

    ex = old_rules.get('external_load') or {}
    if ex.get('enabled'):
        rule_cfg = deepcopy(DEFAULT_RULE_TEMPLATE)
        rule_cfg['external_load'].update({
            'enabled': True, 'cpu_enabled': True, 'cpu_warn': int(ex.get('cpu_warn', 45)), 'cpu_recover': int(ex.get('cpu_recover', 25)),
            'net_enabled': True, 'net_warn_pct': int(ex.get('net_warn_pct', 25)), 'net_recover_pct': int(ex.get('net_recover_pct', 12)),
            'ram_enabled': True, 'ram_min_free': int(ex.get('ram_min_free', 15)), 'ram_recover_free': int(ex.get('ram_recover_free', 25)),
        })
        rule_cfg['enter_sec'] = int(ex.get('enter_sec', 30) or 30)
        rule_cfg['exit_sec'] = int(ex.get('exit_sec', 300) or 300)
        conn.execute(
            "INSERT INTO tuner_switch_rules (priority, name, enabled, target_profile_id, rule_json, updated_at) VALUES (?, ?, 1, ?, ?, ?)",
            (prio, 'Высокая нагрузка от других программ', ex.get('target_mode', 'comfort'), json.dumps(rule_cfg, ensure_ascii=False), now)
        )
        prio += 1

    for idx, sc in enumerate(old_rules.get('schedules') or [], start=1):
        if isinstance(sc, dict):
            rule_cfg = deepcopy(DEFAULT_RULE_TEMPLATE)
            rule_cfg['schedule'] = {'enabled': True, 'start': sc.get('start', '01:00'), 'end': sc.get('end', '08:00'), 'days': sc.get('days', [0, 1, 2, 3, 4, 5, 6])}
            rule_cfg['enter_sec'], rule_cfg['exit_sec'] = 5, 10
            conn.execute(
                "INSERT INTO tuner_switch_rules (priority, name, enabled, target_profile_id, rule_json, updated_at) VALUES (?, ?, 1, ?, ?, ?)",
                (prio, f"Расписание #{idx}", sc.get('mode', 'performance'), json.dumps(rule_cfg, ensure_ascii=False), now)
            )
            prio += 1
    conn.execute("DROP TABLE IF EXISTS _old_tuner_switch_rules")


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
                        poll_interval_sec INTEGER NOT NULL DEFAULT 3,
                        default_profile_id TEXT NOT NULL DEFAULT 'performance',
                        active_rule_id INTEGER NOT NULL DEFAULT 0,
                        baseline_json TEXT NOT NULL DEFAULT '{}',
                        current_limits_json TEXT NOT NULL DEFAULT '{}',
                        dirty_flag INTEGER NOT NULL DEFAULT 0,
                        cooldown_until REAL NOT NULL DEFAULT 0,
                        last_action_ts REAL NOT NULL DEFAULT 0,
                        last_reason TEXT NOT NULL DEFAULT 'Выключен'
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
                cols_st = {r['name'] for r in conn.execute("PRAGMA table_info(tuner_state)").fetchall()}
                for col_n, col_d in [('poll_interval_sec', 'INTEGER NOT NULL DEFAULT 3'), ('default_profile_id', "TEXT NOT NULL DEFAULT 'performance'"), ('active_rule_id', 'INTEGER NOT NULL DEFAULT 0')]:
                    if col_n not in cols_st:
                        conn.execute(f"ALTER TABLE tuner_state ADD COLUMN {col_n} {col_d}")
                conn.execute("INSERT OR IGNORE INTO tuner_state (id) VALUES (1)")

                has_prof = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tuner_profiles'").fetchone()
                if has_prof:
                    _migrate_old_profiles(conn)
                else:
                    conn.execute("""
                        CREATE TABLE tuner_profiles (
                            id TEXT PRIMARY KEY, name TEXT NOT NULL, icon TEXT NOT NULL DEFAULT '⚙️',
                            is_builtin INTEGER NOT NULL DEFAULT 0, sort_order INTEGER NOT NULL DEFAULT 10,
                            config_json TEXT NOT NULL, updated_at REAL NOT NULL
                        )
                    """)
                    now = time.time()
                    for idx, p in enumerate(BUILTIN_PRESETS, start=1):
                        cfg_data = merge_profile_config(BASE_PROFILE_TEMPLATE, p['config'])
                        conn.execute(
                            "INSERT INTO tuner_profiles (id, name, icon, is_builtin, sort_order, config_json, updated_at) VALUES (?, ?, ?, 1, ?, ?, ?)",
                            (p['id'], p['name'], p['icon'], idx, json.dumps(cfg_data, ensure_ascii=False), now)
                        )

                has_rules = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tuner_switch_rules'").fetchone()
                if has_rules:
                    _migrate_old_rules(conn)
                else:
                    conn.execute("""
                        CREATE TABLE tuner_switch_rules (
                            id INTEGER PRIMARY KEY AUTOINCREMENT, priority INTEGER NOT NULL DEFAULT 10,
                            name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                            target_profile_id TEXT NOT NULL, rule_json TEXT NOT NULL, updated_at REAL NOT NULL
                        )
                    """)
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
    return {'id': 1, 'mode': 'off', 'auto_switch_enabled': 0, 'poll_interval_sec': 3, 'default_profile_id': 'performance', 'dirty_flag': 0, 'baseline': {}, 'current_limits': {}, 'last_reason': 'Выключен'}


def update_tuner_state(**fields):
    allowed = {
        'mode', 'auto_switch_enabled', 'manual_override_until', 'manual_override_mode',
        'manual_override_policy', 'poll_interval_sec', 'default_profile_id', 'active_rule_id',
        'baseline_json', 'current_limits_json', 'dirty_flag', 'cooldown_until', 'last_action_ts', 'last_reason'
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


def list_tuner_profiles():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = conn.execute("SELECT * FROM tuner_profiles ORDER BY sort_order ASC, name ASC").fetchall()
                out = []
                for r in rows:
                    d = dict(r)
                    d['config'] = merge_profile_config(BASE_PROFILE_TEMPLATE, json.loads(d.pop('config_json') or '{}'))
                    out.append(d)
                return out
        except Exception:
            return []


def get_tuner_profiles_map():
    return {p['id']: p for p in list_tuner_profiles()}


def save_tuner_profile(pid, name, icon, config_dict, is_new=False):
    clean_id = _slugify(pid or name)
    clean_name = str(name or '').strip()[:40] or 'Профиль'
    clean_icon = str(icon or '⚙️').strip()[:8] or '⚙️'
    merged = merge_profile_config(BASE_PROFILE_TEMPLATE, config_dict)
    now = time.time()
    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            if is_new:
                base_id = clean_id
                idx = 1
                while conn.execute("SELECT 1 FROM tuner_profiles WHERE id = ?", (clean_id,)).fetchone():
                    idx += 1
                    clean_id = f"{base_id}_{idx}"
                max_ord = conn.execute("SELECT COALESCE(MAX(sort_order), 10) FROM tuner_profiles").fetchone()[0]
                conn.execute(
                    "INSERT INTO tuner_profiles (id, name, icon, is_builtin, sort_order, config_json, updated_at) VALUES (?, ?, ?, 0, ?, ?, ?)",
                    (clean_id, clean_name, clean_icon, int(max_ord) + 1, json.dumps(merged, ensure_ascii=False), now)
                )
            else:
                conn.execute(
                    "UPDATE tuner_profiles SET name = ?, icon = ?, config_json = ?, updated_at = ? WHERE id = ?",
                    (clean_name, clean_icon, json.dumps(merged, ensure_ascii=False), now, clean_id)
                )
    return get_tuner_profiles_map().get(clean_id)


def delete_tuner_profile(pid):
    st = get_tuner_state()
    if pid == st.get('default_profile_id'):
        return False, "Нельзя удалить профиль, выбранный по умолчанию!"
    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM tuner_profiles").fetchone()[0]
            if cnt <= 1:
                return False, "Нельзя удалить последний профиль!"
            conn.execute("UPDATE tuner_switch_rules SET enabled = 0 WHERE target_profile_id = ?", (pid,))
            conn.execute("DELETE FROM tuner_profiles WHERE id = ?", (pid,))
            if st.get('mode') == pid:
                conn.execute("UPDATE tuner_state SET mode = ? WHERE id = 1", (st.get('default_profile_id', 'performance'),))
    return True, "Профиль удалён (связанные правила отключены)"


def reset_builtin_presets():
    now = time.time()
    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            for idx, p in enumerate(BUILTIN_PRESETS, start=1):
                cfg_data = merge_profile_config(BASE_PROFILE_TEMPLATE, p['config'])
                conn.execute(
                    "INSERT OR REPLACE INTO tuner_profiles (id, name, icon, is_builtin, sort_order, config_json, updated_at) VALUES (?, ?, ?, 1, ?, ?, ?)",
                    (p['id'], p['name'], p['icon'], idx, json.dumps(cfg_data, ensure_ascii=False), now)
                )
    return list_tuner_profiles()


def list_switch_rules():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = conn.execute("SELECT * FROM tuner_switch_rules ORDER BY priority ASC, id ASC").fetchall()
                out = []
                for r in rows:
                    d = dict(r)
                    d['config'] = merge_profile_config(DEFAULT_RULE_TEMPLATE, json.loads(d.pop('rule_json') or '{}'))
                    out.append(d)
                return out
        except Exception:
            return []


def save_switch_rule(rule_id, name, enabled, target_profile_id, rule_cfg):
    merged = merge_profile_config(DEFAULT_RULE_TEMPLATE, rule_cfg)
    now = time.time()
    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            if rule_id:
                conn.execute(
                    "UPDATE tuner_switch_rules SET name = ?, enabled = ?, target_profile_id = ?, rule_json = ?, updated_at = ? WHERE id = ?",
                    (str(name or 'Правило')[:60], 1 if enabled else 0, str(target_profile_id), json.dumps(merged, ensure_ascii=False), now, int(rule_id))
                )
                return int(rule_id)
            max_p = conn.execute("SELECT COALESCE(MAX(priority), 0) FROM tuner_switch_rules").fetchone()[0]
            cur = conn.execute(
                "INSERT INTO tuner_switch_rules (priority, name, enabled, target_profile_id, rule_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (int(max_p) + 1, str(name or 'Правило')[:60], 1 if enabled else 0, str(target_profile_id), json.dumps(merged, ensure_ascii=False), now)
            )
            return cur.lastrowid


def delete_switch_rule(rule_id):
    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            conn.execute("DELETE FROM tuner_switch_rules WHERE id = ?", (int(rule_id),))


def move_switch_rule(rule_id, direction):
    rules = list_switch_rules()
    idx = next((i for i, r in enumerate(rules) if r['id'] == int(rule_id)), -1)
    if idx < 0:
        return
    swap_idx = idx - 1 if direction == 'up' else idx + 1
    if not (0 <= swap_idx < len(rules)):
        return
    rules[idx], rules[swap_idx] = rules[swap_idx], rules[idx]
    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            for p_idx, r in enumerate(rules, start=1):
                conn.execute("UPDATE tuner_switch_rules SET priority = ? WHERE id = ?", (p_idx, r['id']))


def add_tuner_history(mode, event_type, reason, metrics, old_slots, new_slots):
    now = time.time()
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute(
                    """INSERT INTO tuner_history
                       (ts, mode, event_type, reason, disk_busy, cpu_ext, ram_free, net_pct, old_slots, new_slots)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        now, str(mode), str(event_type), str(reason)[:220],
                        round(float(metrics.get('disk_busy', 0)), 1), round(float(metrics.get('cpu_ext', 0)), 1),
                        round(float(metrics.get('ram_free', 0)), 1), round(float(metrics.get('channel_pct', 0)), 1),
                        int(old_slots or 0), int(new_slots or 0)
                    )
                )
                conn.execute("DELETE FROM tuner_history WHERE ts < ?", (now - 48 * 3600,))
        except Exception as e:
            write_error_log("add_tuner_history", e)


def get_tuner_history(limit=30):
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                return [dict(r) for r in conn.execute("SELECT * FROM tuner_history ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()]
        except Exception:
            return []
