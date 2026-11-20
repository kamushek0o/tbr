# core/webhooks_bundler.py
import json
import time
import threading
import urllib.request
from utils.config import cfg
from utils.helpers import write_error_log
from core.app_state_db import app_state_db

_BUNDLE_LOCK = threading.Lock()
_BUNDLE_BUFFER = []
_BUNDLE_TIMER = None


def _ensure_webhook_table():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS webhook_deliveries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_type TEXT NOT NULL,
                        url TEXT NOT NULL,
                        status_code INTEGER NOT NULL,
                        ok INTEGER NOT NULL,
                        error TEXT NOT NULL DEFAULT '',
                        created_at REAL NOT NULL
                    )
                """)
                conn.commit()
        except Exception as e:
            write_error_log("webhook_deliveries init", e)


_ensure_webhook_table()


def emit_webhook(event_type, payload):
    """#41 Исходящие JSON POST вебхуки в отдельном потоке с жёстким таймаутом 4с."""
    raw_urls = cfg.get('Outbound_Webhooks', '').strip()
    if not raw_urls:
        return
    urls = [u.strip() for u in raw_urls.splitlines() if u.strip().startswith(('http://', 'https://'))]
    if not urls:
        return

    body_bytes = json.dumps({
        'event': str(event_type),
        'timestamp': int(time.time()),
        'data': payload or {}
    }, ensure_ascii=False).encode('utf-8')

    def send_one(url):
        code, ok, err = 0, False, ''
        try:
            req = urllib.request.Request(
                url, data=body_bytes, method='POST',
                headers={'Content-Type': 'application/json', 'User-Agent': 'tbr-pro-webhook/3.2'}
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                code = resp.getcode()
                ok = (200 <= code < 300)
        except Exception as e:
            err = str(e)[:200]
        with app_state_db._lock:
            try:
                with app_state_db._get_conn() as conn:
                    conn.execute(
                        "INSERT INTO webhook_deliveries (event_type, url, status_code, ok, error, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (str(event_type), url[:250], code, 1 if ok else 0, err, time.time())
                    )
                    conn.execute("DELETE FROM webhook_deliveries WHERE id NOT IN (SELECT id FROM webhook_deliveries ORDER BY id DESC LIMIT 30)")
                    conn.commit()
            except Exception:
                pass

    for u in urls[:5]:
        threading.Thread(target=send_one, args=(u,), daemon=True).start()


def get_webhook_deliveries(limit=20):
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = conn.execute("SELECT * FROM webhook_deliveries ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []


def queue_bundled_alert(title, lines, send_fn):
    """#49 Cascade Alert Bundler: группирует некритические алерты в окно 45 секунд."""
    global _BUNDLE_TIMER
    with _BUNDLE_LOCK:
        _BUNDLE_BUFFER.append((title, list(lines or [])))
        if _BUNDLE_TIMER is not None and _BUNDLE_TIMER.is_alive():
            return

        def flush():
            global _BUNDLE_TIMER
            with _BUNDLE_LOCK:
                batch = list(_BUNDLE_BUFFER)
                _BUNDLE_BUFFER.clear()
                _BUNDLE_TIMER = None
            if not batch:
                return
            if len(batch) == 1:
                send_fn(batch[0][0], batch[0][1])
                return
            merged_lines = []
            for t, lns in batch[:20]:
                preview = lns[0] if lns else ''
                merged_lines.append(f"• {t}" + (f": {preview}" if preview else ""))
            if len(batch) > 20:
                merged_lines.append(f"...и ещё событий: {len(batch) - 20}")
            send_fn(f"📦 Сводка событий ({len(batch)} шт. за 45с)", merged_lines)

        _BUNDLE_TIMER = threading.Timer(45.0, flush)
        _BUNDLE_TIMER.daemon = True
        _BUNDLE_TIMER.start()