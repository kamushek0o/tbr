# core/automation.py
import os
import time
import sqlite3
import threading
from utils.config import cfg
from utils.helpers import APP_DATA_DIR, format_file_size, write_log, write_error_log
from core.qb_api import (
    detect_qbittorrent_port, get_live_torrent_info, send_qb_command,
    add_torrent_tags, remove_torrent_tags
)
from core.torrent_parser import get_all_torrents
from core.summary_tracker import summary_tracker
from core.notifiers import notify_all, test_notifications
from core.system_alerts import system_alerts
from core.app_state_db import app_state_db
from core.keep_awake import keep_awake
from core.reliability import run_auto_recheck, run_watchdog
from core.disaster_recovery import maybe_run_weekly_manifest
from core.smart_timers import tick_snooze, tick_expirations
from core.smart_tagging import run_smart_tagging
from core.dnd_digest import flush_dnd_if_ready, maybe_send_digest
from core.torrent_targets import evaluate_targets
from core.achievements import evaluate_achievements

VALID_TIME_MODES = ('seeding_time', 'time_active')
VALID_SPEED_OPS = ('', '>=', '<')


def format_duration_ru(seconds):
    sec = max(0, int(seconds or 0))
    if sec >= 86400:
        return f"{sec // 86400} д {(sec % 86400) // 3600} ч"
    if sec >= 3600:
        return f"{sec // 3600} ч"
    return f"{sec // 60} мин"


class AutomationEngine:
    def __init__(self):
        self.db_file = os.path.join(APP_DATA_DIR, "automation.db")
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
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
                        CREATE TABLE IF NOT EXISTS rules (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                            time_mode TEXT NOT NULL DEFAULT 'seeding_time',
                            min_ratio REAL NOT NULL DEFAULT 0, min_seed_days REAL NOT NULL DEFAULT 0,
                            min_uploaded_bytes INTEGER NOT NULL DEFAULT 0,
                            speed_op TEXT NOT NULL DEFAULT '', speed_bytes REAL NOT NULL DEFAULT 0,
                            speed_window_min INTEGER NOT NULL DEFAULT 60,
                            action_pause INTEGER NOT NULL DEFAULT 0, action_tag TEXT NOT NULL DEFAULT '',
                            action_remove_tag TEXT NOT NULL DEFAULT '', notify INTEGER NOT NULL DEFAULT 1
                        );
                        CREATE TABLE IF NOT EXISTS notified_events (
                            rule_id INTEGER NOT NULL, hash_id TEXT NOT NULL, triggered_at REAL NOT NULL,
                            PRIMARY KEY (rule_id, hash_id), FOREIGN KEY (rule_id) REFERENCES rules(id) ON DELETE CASCADE
                        );
                    """)
                    cur = conn.cursor()
                    cur.execute("PRAGMA table_info(rules)")
                    cols = {r['name'] for r in cur.fetchall()}
                    for col_name, col_def in [
                        ("time_mode", "TEXT NOT NULL DEFAULT 'seeding_time'"),
                        ("min_uploaded_bytes", "INTEGER NOT NULL DEFAULT 0"),
                        ("speed_op", "TEXT NOT NULL DEFAULT ''"),
                        ("speed_bytes", "REAL NOT NULL DEFAULT 0"),
                        ("speed_window_min", "INTEGER NOT NULL DEFAULT 60"),
                        ("action_remove_tag", "TEXT NOT NULL DEFAULT ''")
                    ]:
                        if col_name not in cols:
                            cur.execute(f"ALTER TABLE rules ADD COLUMN {col_name} {col_def}")
                    conn.commit()
            except Exception as e:
                write_error_log("Инициализация automation.db", e)

    def get_rules(self):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM rules ORDER BY id DESC")
                    return [dict(r) for r in cur.fetchall()]
            except Exception:
                return []

    def add_rule(self, name, min_ratio, min_seed_days, action_pause, action_tag, notify,
                 time_mode='seeding_time', min_uploaded_bytes=0, speed_op='', speed_bytes=0.0,
                 speed_window_min=60, action_remove_tag=''):
        t_mode = time_mode if time_mode in VALID_TIME_MODES else 'seeding_time'
        s_op = speed_op if speed_op in VALID_SPEED_OPS else ''
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        """INSERT INTO rules (name, enabled, time_mode, min_ratio, min_seed_days, min_uploaded_bytes,
                               speed_op, speed_bytes, speed_window_min, action_pause, action_tag, action_remove_tag, notify)
                           VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (name, t_mode, float(min_ratio), float(min_seed_days), int(min_uploaded_bytes),
                         s_op, float(speed_bytes), max(1, int(speed_window_min)),
                         1 if action_pause else 0, action_tag.strip(), action_remove_tag.strip(), 1 if notify else 0)
                    )
                    conn.commit()
                    return cur.lastrowid
            except Exception as e:
                write_error_log("Ошибка add_rule", e)
                return None

    def update_rule(self, rule_id, name, min_ratio, min_seed_days, action_pause, action_tag, notify,
                    time_mode='seeding_time', min_uploaded_bytes=0, speed_op='', speed_bytes=0.0,
                    speed_window_min=60, action_remove_tag=''):
        t_mode = time_mode if time_mode in VALID_TIME_MODES else 'seeding_time'
        s_op = speed_op if speed_op in VALID_SPEED_OPS else ''
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        """UPDATE rules SET name = ?, time_mode = ?, min_ratio = ?, min_seed_days = ?, min_uploaded_bytes = ?,
                               speed_op = ?, speed_bytes = ?, speed_window_min = ?,
                               action_pause = ?, action_tag = ?, action_remove_tag = ?, notify = ? WHERE id = ?""",
                        (name, t_mode, float(min_ratio), float(min_seed_days), int(min_uploaded_bytes),
                         s_op, float(speed_bytes), max(1, int(speed_window_min)),
                         1 if action_pause else 0, action_tag.strip(), action_remove_tag.strip(), 1 if notify else 0, int(rule_id))
                    )
                    updated = cur.rowcount > 0
                    cur.execute("DELETE FROM notified_events WHERE rule_id = ?", (int(rule_id),))
                    conn.commit()
                    return updated
            except Exception as e:
                write_error_log("Ошибка update_rule", e)
                return False

    def toggle_rule(self, rule_id):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    conn.execute("UPDATE rules SET enabled = 1 - enabled WHERE id = ?", (int(rule_id),))
                    conn.commit()
                    return True
            except Exception:
                return False

    def delete_rule(self, rule_id):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    conn.execute("DELETE FROM rules WHERE id = ?", (int(rule_id),))
                    conn.commit()
                    return True
            except Exception:
                return False

    def _is_triggered(self, rule_id, t_hash):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT 1 FROM notified_events WHERE rule_id = ? AND hash_id = ?", (rule_id, t_hash))
                    return cur.fetchone() is not None
            except Exception:
                return False

    def _mark_triggered(self, rule_id, t_hash):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    conn.execute("INSERT OR IGNORE INTO notified_events (rule_id, hash_id, triggered_at) VALUES (?, ?, ?)", (rule_id, t_hash, time.time()))
                    conn.commit()
            except Exception:
                pass

    def test_notifications(self):
        return test_notifications()

    def run_system_tick(self):
        ip, port = detect_qbittorrent_port(cfg.config)
        live = get_live_torrent_info(ip, port) if port else {}
        qb_up = bool(port and live)
        keep_awake.evaluate(live)
        system_alerts.check(qb_up, live=live)
        run_watchdog(qb_up)
        maybe_run_weekly_manifest()
        tick_snooze()
        flush_dnd_if_ready(notify_all)
        maybe_send_digest(notify_all)
        evaluate_achievements(force=False)
        if qb_up:
            evaluate_targets(live)
        if qb_up and time.time() >= cfg.getint('Autopilot_Frozen_Until', 0):
            tick_expirations(ip, port, live)
            run_smart_tagging(ip, port, live, get_all_torrents(use_cache=True))
        return ip, port, live

    def run_cycle(self):
        ip, port, live = self.run_system_tick()
        if not live:
            return 0

        now_ts = time.time()
        if now_ts < cfg.getint('Autopilot_Frozen_Until', 0):
            return 0

        run_auto_recheck(ip, port, live)
        rules = [r for r in self.get_rules() if r.get('enabled')]
        if not rules:
            return 0

        triggered_count = 0
        for r in rules:
            t_mode = r.get('time_mode') if r.get('time_mode') in VALID_TIME_MODES else 'seeding_time'
            min_r, min_d = float(r.get('min_ratio', 0) or 0), float(r.get('min_seed_days', 0) or 0)
            min_up = int(r.get('min_uploaded_bytes', 0) or 0)
            s_op, s_bytes = r.get('speed_op', '') or '', float(r.get('speed_bytes', 0) or 0)
            w_sec = max(60, int(r.get('speed_window_min', 60) or 60) * 60)
            use_speed = (s_op in ('>=', '<') and s_bytes > 0)
            if min_r <= 0 and min_d <= 0 and min_up <= 0 and not use_speed:
                continue

            for t_hash, info in live.items():
                ratio = float(info.get('ratio', 0) or 0)
                uploaded = int(info.get('uploaded', 0) or 0)
                time_sec = float(info.get(t_mode, 0) or 0)
                if (min_r > 0 and ratio < min_r) or (min_d > 0 and (time_sec / 86400.0) < min_d) or (min_up > 0 and uploaded < min_up):
                    continue

                v_avg = None
                if use_speed:
                    first, last, cnt = summary_tracker.db.get_torrent_window_bounds(t_hash, now_ts - w_sec, now_ts)
                    if cnt < 2 or not first or not last or (last[0] - first[0]) < (0.5 * w_sec):
                        continue
                    v_avg = max(0.0, (last[1] - first[1]) / (last[0] - first[0]))
                    if (s_op == '>=' and v_avg < s_bytes) or (s_op == '<' and v_avg >= s_bytes):
                        continue

                if self._is_triggered(r['id'], t_hash):
                    continue

                cur_tags = {tg.strip().lower() for tg in str(info.get('tags', '') or '').split(',') if tg.strip()}
                add_tag, rem_tag = str(r.get('action_tag', '') or '').strip(), str(r.get('action_remove_tag', '') or '').strip()
                want_pause = bool(r.get('action_pause'))
                actions_done = []
                if want_pause and send_qb_command(ip, port, 'stop', t_hash):
                    actions_done.append("⏸️ Поставлено на паузу")
                if add_tag and add_tag.lower() not in cur_tags and add_torrent_tags(ip, port, t_hash, add_tag):
                    actions_done.append(f"🏷️ +Тег: {add_tag}")
                if rem_tag and rem_tag.lower() in cur_tags and remove_torrent_tags(ip, port, t_hash, rem_tag):
                    actions_done.append(f"✂️ -Тег: {rem_tag}")

                if not want_pause and (add_tag or rem_tag) and not actions_done:
                    self._mark_triggered(r['id'], t_hash)
                    continue

                self._mark_triggered(r['id'], t_hash)
                triggered_count += 1
                t_name = info.get('name', t_hash)
                time_lbl, dur_fmt = ("Сид" if t_mode == 'seeding_time' else "Актив"), format_duration_ru(time_sec)
                write_log('automation', f"Правило '{r['name']}' -> '{t_name}' (Ratio: {ratio:.2f}, {time_lbl}: {dur_fmt})")
                app_state_db.add_audit_event('automation', f"Правило: {r['name']}", t_name)
                if r.get('notify'):
                    stat_line = f"Отдано: {format_file_size(uploaded)} | Ratio: {ratio:.2f}x | {time_lbl}: {dur_fmt}"
                    if v_avg is not None:
                        stat_line += f" | Ср. скор.: {format_file_size(v_avg)}/s"
                    msg_lines = [f"Раздача: {t_name}", stat_line] + (["Действия: " + ", ".join(actions_done)] if actions_done else [])
                    notify_all(f"🤖 Сработало правило: {r['name']}", msg_lines)

        return triggered_count

    def start(self):
        if self._running:
            return
        self._running = True

        def loop():
            time.sleep(8)
            last_auto_ts = 0.0
            while self._running:
                now = time.time()
                try:
                    auto_due = cfg.getboolean('Auto_Enabled', False) and (now - last_auto_ts) >= max(1, cfg.getint('Auto_Interval_Min', 5)) * 60
                    if auto_due:
                        self.run_cycle()
                        last_auto_ts = time.time()
                    else:
                        self.run_system_tick()
                except Exception as e:
                    write_error_log("AutomationEngine loop", e)
                for _ in range(30):
                    if not self._running:
                        return
                    time.sleep(1)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()


automation_engine = AutomationEngine()