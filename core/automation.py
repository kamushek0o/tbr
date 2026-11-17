# core/automation.py
import os
import time
import json
import html
import sqlite3
import threading
import urllib.request
from utils.config import cfg
from utils.helpers import APP_DATA_DIR, format_file_size, write_log, write_error_log
from core.qb_api import (
    detect_qbittorrent_port, get_live_torrent_info, send_qb_command,
    add_torrent_tags, remove_torrent_tags
)
from core.summary_tracker import summary_tracker

VALID_TIME_MODES = ('seeding_time', 'time_active')
VALID_SPEED_OPS = ('', '>=', '<')


def format_duration_ru(seconds):
    sec = max(0, int(seconds or 0))
    if sec >= 86400:
        d = sec // 86400
        h = (sec % 86400) // 3600
        return f"{d} д {h} ч"
    if sec >= 3600:
        h = sec // 3600
        return f"{h} ч"
    m = sec // 60
    return f"{m} мин"


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
                            name TEXT NOT NULL,
                            enabled INTEGER NOT NULL DEFAULT 1,
                            time_mode TEXT NOT NULL DEFAULT 'seeding_time',
                            min_ratio REAL NOT NULL DEFAULT 0,
                            min_seed_days REAL NOT NULL DEFAULT 0,
                            min_uploaded_bytes INTEGER NOT NULL DEFAULT 0,
                            speed_op TEXT NOT NULL DEFAULT '',
                            speed_bytes REAL NOT NULL DEFAULT 0,
                            speed_window_min INTEGER NOT NULL DEFAULT 60,
                            action_pause INTEGER NOT NULL DEFAULT 0,
                            action_tag TEXT NOT NULL DEFAULT '',
                            action_remove_tag TEXT NOT NULL DEFAULT '',
                            notify INTEGER NOT NULL DEFAULT 1
                        );
                        CREATE TABLE IF NOT EXISTS notified_events (
                            rule_id INTEGER NOT NULL,
                            hash_id TEXT NOT NULL,
                            triggered_at REAL NOT NULL,
                            PRIMARY KEY (rule_id, hash_id),
                            FOREIGN KEY (rule_id) REFERENCES rules(id) ON DELETE CASCADE
                        );
                    """)
                    # Миграция старых таблиц rules
                    cur = conn.cursor()
                    cur.execute("PRAGMA table_info(rules)")
                    cols = {r['name'] for r in cur.fetchall()}
                    migrations = [
                        ("time_mode", "TEXT NOT NULL DEFAULT 'seeding_time'"),
                        ("min_uploaded_bytes", "INTEGER NOT NULL DEFAULT 0"),
                        ("speed_op", "TEXT NOT NULL DEFAULT ''"),
                        ("speed_bytes", "REAL NOT NULL DEFAULT 0"),
                        ("speed_window_min", "INTEGER NOT NULL DEFAULT 60"),
                        ("action_remove_tag", "TEXT NOT NULL DEFAULT ''")
                    ]
                    for col_name, col_def in migrations:
                        if col_name not in cols:
                            cur.execute(f"ALTER TABLE rules ADD COLUMN {col_name} {col_def}")
                    cur.execute("UPDATE rules SET time_mode = 'seeding_time' WHERE time_mode IS NULL OR time_mode NOT IN ('seeding_time', 'time_active')")
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
            except Exception as e:
                write_error_log("Ошибка get_rules", e)
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
                        """INSERT INTO rules (
                               name, enabled, time_mode, min_ratio, min_seed_days, min_uploaded_bytes,
                               speed_op, speed_bytes, speed_window_min, action_pause, action_tag, action_remove_tag, notify
                           ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            name, t_mode, float(min_ratio), float(min_seed_days), int(min_uploaded_bytes),
                            s_op, float(speed_bytes), max(1, int(speed_window_min)),
                            1 if action_pause else 0, action_tag.strip(), action_remove_tag.strip(),
                            1 if notify else 0
                        )
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
                        """UPDATE rules
                           SET name = ?, time_mode = ?, min_ratio = ?, min_seed_days = ?, min_uploaded_bytes = ?,
                               speed_op = ?, speed_bytes = ?, speed_window_min = ?,
                               action_pause = ?, action_tag = ?, action_remove_tag = ?, notify = ?
                           WHERE id = ?""",
                        (
                            name, t_mode, float(min_ratio), float(min_seed_days), int(min_uploaded_bytes),
                            s_op, float(speed_bytes), max(1, int(speed_window_min)),
                            1 if action_pause else 0, action_tag.strip(), action_remove_tag.strip(),
                            1 if notify else 0, int(rule_id)
                        )
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
                    cur = conn.cursor()
                    cur.execute("UPDATE rules SET enabled = 1 - enabled WHERE id = ?", (int(rule_id),))
                    conn.commit()
                    return True
            except Exception as e:
                write_error_log("Ошибка toggle_rule", e)
                return False

    def delete_rule(self, rule_id):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM rules WHERE id = ?", (int(rule_id),))
                    conn.commit()
                    return True
            except Exception as e:
                write_error_log("Ошибка delete_rule", e)
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
                    conn.execute(
                        "INSERT OR IGNORE INTO notified_events (rule_id, hash_id, triggered_at) VALUES (?, ?, ?)",
                        (rule_id, t_hash, time.time())
                    )
                    conn.commit()
            except Exception:
                pass

    def send_telegram(self, text_html):
        token = cfg.get('TG_Bot_Token', '').strip()
        chat_id = cfg.get('TG_Chat_ID', '').strip()
        if not token or not chat_id:
            return False, "Не задан токен или Chat ID"

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({
            'chat_id': chat_id,
            'text': text_html,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }).encode('utf-8')
        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.getcode() == 200, "Telegram: OK"
        except Exception as e:
            write_error_log("Telegram send error", e)
            return False, f"Telegram: {e}"

    def send_discord(self, text_md):
        webhook = cfg.get('Discord_Webhook', '').strip()
        if not webhook:
            return False, "Не задан Discord Webhook"

        payload = json.dumps({'content': text_md[:1900]}).encode('utf-8')
        req = urllib.request.Request(
            webhook,
            data=payload,
            headers={'Content-Type': 'application/json', 'User-Agent': 'tbr-pro/2.0'}
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.getcode() in (200, 204), "Discord: OK"
        except Exception as e:
            write_error_log("Discord send error", e)
            return False, f"Discord: {e}"

    def notify_all(self, title, lines):
        tg_msg = f"<b>{html.escape(title)}</b>\n" + "\n".join(html.escape(l) for l in lines)
        dc_msg = f"**{title}**\n" + "\n".join(lines)

        results = []
        if cfg.get('TG_Bot_Token', '').strip() and cfg.get('TG_Chat_ID', '').strip():
            _, res_tg = self.send_telegram(tg_msg)
            results.append(res_tg)
        if cfg.get('Discord_Webhook', '').strip():
            _, res_dc = self.send_discord(dc_msg)
            results.append(res_dc)
        return results

    def test_notifications(self):
        has_tg = bool(cfg.get('TG_Bot_Token', '').strip() and cfg.get('TG_Chat_ID', '').strip())
        has_dc = bool(cfg.get('Discord_Webhook', '').strip())
        if not has_tg and not has_dc:
            return False, ["Не настроен ни Telegram, ни Discord."]

        res = self.notify_all(
            "⚡ tbr PRO — Тест уведомлений",
            ["Связь настроена! Бот готов присылать отчёты по правилам."]
        )
        return True, res

    def run_cycle(self):
        rules = [r for r in self.get_rules() if r.get('enabled')]
        if not rules:
            return 0

        ip, port = detect_qbittorrent_port(cfg.config)
        if not port:
            return 0
        live = get_live_torrent_info(ip, port)
        if not live:
            return 0

        now_ts = time.time()
        triggered_count = 0

        for r in rules:
            t_mode = r.get('time_mode') if r.get('time_mode') in VALID_TIME_MODES else 'seeding_time'
            min_r = float(r.get('min_ratio', 0) or 0)
            min_d = float(r.get('min_seed_days', 0) or 0)
            min_up = int(r.get('min_uploaded_bytes', 0) or 0)
            s_op = r.get('speed_op', '') or ''
            s_bytes = float(r.get('speed_bytes', 0) or 0)
            w_sec = max(60, int(r.get('speed_window_min', 60) or 60) * 60)
            use_speed = (s_op in ('>=', '<') and s_bytes > 0)

            if min_r <= 0 and min_d <= 0 and min_up <= 0 and not use_speed:
                continue

            for t_hash, info in live.items():
                ratio = float(info.get('ratio', 0) or 0)
                uploaded = int(info.get('uploaded', 0) or 0)
                time_sec = float(info.get(t_mode, 0) or 0)
                time_days = time_sec / 86400.0

                if min_r > 0 and ratio < min_r:
                    continue
                if min_d > 0 and time_days < min_d:
                    continue
                if min_up > 0 and uploaded < min_up:
                    continue

                v_avg = None
                if use_speed:
                    first, last, cnt = summary_tracker.db.get_torrent_window_bounds(t_hash, now_ts - w_sec, now_ts)
                    if cnt < 2 or not first or not last:
                        continue  # холодный старт
                    dt_win = last[0] - first[0]
                    if dt_win < (0.5 * w_sec):
                        continue  # холодный старт (< 0.5 * W)
                    v_avg = max(0.0, (last[1] - first[1]) / dt_win)
                    if s_op == '>=' and v_avg < s_bytes:
                        continue
                    if s_op == '<' and v_avg >= s_bytes:
                        continue

                if self._is_triggered(r['id'], t_hash):
                    continue

                # Защита от качелей по тегам
                raw_tags = str(info.get('tags', '') or '')
                cur_tags = {tg.strip().lower() for tg in raw_tags.split(',') if tg.strip()}
                add_tag = str(r.get('action_tag', '') or '').strip()
                rem_tag = str(r.get('action_remove_tag', '') or '').strip()
                want_pause = bool(r.get('action_pause'))

                actions_done = []
                if want_pause:
                    if send_qb_command(ip, port, 'stop', t_hash):
                        actions_done.append("⏸️ Поставлено на паузу")

                if add_tag and add_tag.lower() not in cur_tags:
                    if add_torrent_tags(ip, port, t_hash, add_tag):
                        actions_done.append(f"🏷️ +Тег: {add_tag}")

                if rem_tag and rem_tag.lower() in cur_tags:
                    if remove_torrent_tags(ip, port, t_hash, rem_tag):
                        actions_done.append(f"✂️ -Тег: {rem_tag}")

                # Если правило чисто теговое (без паузы и без уведомления/или теги уже были в нужном состоянии)
                if not want_pause and (add_tag or rem_tag) and not actions_done:
                    self._mark_triggered(r['id'], t_hash)
                    continue

                self._mark_triggered(r['id'], t_hash)
                triggered_count += 1

                t_name = info.get('name', t_hash)
                up_fmt = format_file_size(uploaded)
                time_lbl = "Сид" if t_mode == 'seeding_time' else "Актив"
                dur_fmt = format_duration_ru(time_sec)

                write_log('automation', f"Правило '{r['name']}' -> '{t_name}' (Ratio: {ratio:.2f}, {time_lbl}: {dur_fmt})")

                if r.get('notify'):
                    stat_line = f"Отдано: {up_fmt} | Ratio: {ratio:.2f}x | {time_lbl}: {dur_fmt}"
                    if v_avg is not None:
                        stat_line += f" | Ср. скор.: {format_file_size(v_avg)}/s"
                    msg_lines = [f"Раздача: {t_name}", stat_line]
                    if actions_done:
                        msg_lines.append("Действия: " + ", ".join(actions_done))
                    self.notify_all(f"🤖 Сработало правило: {r['name']}", msg_lines)

        return triggered_count

    def start(self):
        if self._running:
            return
        self._running = True

        def loop():
            time.sleep(10)
            while self._running:
                try:
                    if cfg.getboolean('Auto_Enabled', False):
                        self.run_cycle()
                except Exception as e:
                    write_error_log("AutomationEngine loop", e)

                interval_sec = max(1, cfg.getint('Auto_Interval_Min', 5)) * 60
                for _ in range(interval_sec):
                    if not self._running:
                        return
                    time.sleep(1)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()


automation_engine = AutomationEngine()