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
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info, send_qb_command, add_torrent_tags


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
                            min_ratio REAL NOT NULL DEFAULT 0,
                            min_seed_days REAL NOT NULL DEFAULT 0,
                            action_pause INTEGER NOT NULL DEFAULT 0,
                            action_tag TEXT NOT NULL DEFAULT '',
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

    def add_rule(self, name, min_ratio, min_seed_days, action_pause, action_tag, notify):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        """INSERT INTO rules (name, enabled, min_ratio, min_seed_days, action_pause, action_tag, notify)
                           VALUES (?, 1, ?, ?, ?, ?, ?)""",
                        (name, float(min_ratio), float(min_seed_days), 1 if action_pause else 0, action_tag.strip(), 1 if notify else 0)
                    )
                    conn.commit()
                    return cur.lastrowid
            except Exception as e:
                write_error_log("Ошибка add_rule", e)
                return None

    def update_rule(self, rule_id, name, min_ratio, min_seed_days, action_pause, action_tag, notify):
        with self._lock:
            try:
                with self._get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        """UPDATE rules
                           SET name = ?, min_ratio = ?, min_seed_days = ?, action_pause = ?, action_tag = ?, notify = ?
                           WHERE id = ?""",
                        (name, float(min_ratio), float(min_seed_days), 1 if action_pause else 0, action_tag.strip(), 1 if notify else 0, int(rule_id))
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

        triggered_count = 0
        for r in rules:
            min_r = float(r.get('min_ratio', 0) or 0)
            min_d = float(r.get('min_seed_days', 0) or 0)
            if min_r <= 0 and min_d <= 0:
                continue

            for t_hash, info in live.items():
                ratio = float(info.get('ratio', 0) or 0)
                seed_days = float(info.get('seeding_time', 0) or 0) / 86400.0

                if min_r > 0 and ratio < min_r:
                    continue
                if min_d > 0 and seed_days < min_d:
                    continue

                if self._is_triggered(r['id'], t_hash):
                    continue

                actions_done = []
                if r.get('action_pause'):
                    if send_qb_command(ip, port, 'stop', t_hash):
                        actions_done.append("⏸️ Поставлено на паузу")

                tag = str(r.get('action_tag', '')).strip()
                if tag:
                    if add_torrent_tags(ip, port, t_hash, tag):
                        actions_done.append(f"🏷️ Тег: {tag}")

                self._mark_triggered(r['id'], t_hash)
                triggered_count += 1

                t_name = info.get('name', t_hash)
                up_fmt = format_file_size(info.get('uploaded', 0))
                write_log('automation', f"Правило '{r['name']}' сработало на '{t_name}' (Ratio: {ratio:.2f}, Сид: {seed_days:.1f}д)")

                if r.get('notify'):
                    msg_lines = [
                        f"Раздача: {t_name}",
                        f"Отдано: {up_fmt} | Ratio: {ratio:.2f}x | Сид: {seed_days:.1f} дн."
                    ]
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