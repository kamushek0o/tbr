# core/dnd_digest.py
import json
import time
import datetime
from utils.config import cfg
from utils.helpers import format_file_size, write_error_log
from core.app_state_db import app_state_db
from core.summary_tracker import summary_tracker
from core.torrent_parser import get_all_torrents
from core.scheduler import MIN_DELTA_SEC
from core.disk_monitor import get_monitored_disk_info
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info


def _parse_hhmm(val, default_min):
    try:
        parts = str(val or "").strip().split(":")
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    except Exception:
        pass
    return default_min


def get_dnd_settings():
    raw_days = str(cfg.get("DND_Days", "0,1,2,3,4,5,6"))
    days = sorted({int(x) for x in raw_days.split(",") if x.strip().isdigit() and 0 <= int(x) <= 6})
    return {
        "enabled": cfg.getboolean("DND_Enabled", False),
        "start": cfg.get("DND_Start", "23:00") or "23:00",
        "end": cfg.get("DND_End", "08:00") or "08:00",
        "days": days,
    }


def is_dnd_active_now(now_dt=None):
    st = get_dnd_settings()
    if not st["enabled"] or not st["days"]:
        return False

    dt = now_dt or datetime.datetime.now()
    cur_min = dt.hour * 60 + dt.minute
    start_min = _parse_hhmm(st["start"], 23 * 60)
    end_min = _parse_hhmm(st["end"], 8 * 60)
    wd = dt.weekday()

    if start_min == end_min:
        return False
    if start_min < end_min:
        return (wd in st["days"]) and (start_min <= cur_min < end_min)
    if cur_min >= start_min:
        return wd in st["days"]
    if cur_min < end_min:
        return ((wd - 1) % 7) in st["days"]
    return False


def queue_dnd_message(title, lines):
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute(
                    "INSERT INTO dnd_queue (title, lines_json, created_at) VALUES (?, ?, ?)",
                    (str(title), json.dumps(list(lines or []), ensure_ascii=False), time.time())
                )
                conn.commit()
        except Exception as e:
            write_error_log("queue_dnd_message", e)


def flush_dnd_if_ready(send_fn):
    if is_dnd_active_now():
        return 0
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = conn.execute("SELECT * FROM dnd_queue ORDER BY id ASC").fetchall()
                if not rows:
                    return 0
                conn.execute("DELETE FROM dnd_queue")
                conn.commit()
        except Exception:
            return 0

    lines = []
    for r in rows[:25]:
        ts_str = datetime.datetime.fromtimestamp(r["created_at"]).strftime("%H:%M")
        try:
            sub = json.loads(r["lines_json"] or "[]")
            preview = sub[0] if sub else ""
        except Exception:
            preview = ""
        lines.append(f"[{ts_str}] {r['title']}" + (f" — {preview}" if preview else ""))
    if len(rows) > 25:
        lines.append(f"...и ещё событий: {len(rows) - 25}")

    send_fn(f"🌙 Итоги «тихого часа» ({len(rows)} событий)", lines, critical=True)
    return len(rows)


def _sum_positive_delta(since_ts, until_ts):
    rows = summary_tracker.db.get_snapshots_since(since_ts)
    total, prev = 0, None
    for r in rows:
        ts = float(r["timestamp"])
        if ts > until_ts:
            break
        if prev is not None:
            dt = ts - float(prev["timestamp"])
            d = max(0, int(r["total_uploaded"]) - int(prev["total_uploaded"]))
            if dt >= MIN_DELTA_SEC and d > 0:
                total += d
        prev = r
    return total


def get_digest_settings():
    return {
        "mode": cfg.get("Digest_Mode", "off"),
        "hour": max(0, min(23, cfg.getint("Digest_Hour", 21))),
        "weekday": max(0, min(6, cfg.getint("Digest_Weekday", 6))),
    }


def _last_scheduled_ts(now_dt, mode, target_hour, target_wd):
    cand = now_dt.replace(hour=target_hour, minute=0, second=0, microsecond=0)
    if mode == "daily":
        return (cand - datetime.timedelta(days=1)).timestamp() if cand > now_dt else cand.timestamp()
    days_back = (now_dt.weekday() - target_wd) % 7
    cand = (now_dt - datetime.timedelta(days=days_back)).replace(hour=target_hour, minute=0, second=0, microsecond=0)
    if cand > now_dt:
        cand -= datetime.timedelta(days=7)
    return cand.timestamp()


def maybe_send_digest(send_fn):
    st = get_digest_settings()
    mode = st["mode"]
    if mode not in ("daily", "weekly"):
        return False

    now_dt = datetime.datetime.now()
    now_ts = now_dt.timestamp()
    sched_ts = _last_scheduled_ts(now_dt, mode, st["hour"], st["weekday"])
    last_sent = float(cfg.getint("Digest_Last_Sent_Ts", 0) or 0)

    if last_sent == 0:
        cfg.set("Digest_Last_Sent_Ts", str(int(now_ts)))
        cfg.save()
        return False
    if last_sent >= sched_ts:
        return False

    period_sec = 7 * 86400 if mode == "weekly" else 86400
    delayed_sec = now_ts - sched_ts
    since_ts = max(last_sent, now_ts - (30 * 86400)) if delayed_sec > 3600 else (now_ts - period_sec)
    span_sec = max(3600.0, now_ts - since_ts)

    cur_vol = _sum_positive_delta(since_ts, now_ts)
    prev_vol = _sum_positive_delta(since_ts - span_sec, since_ts)
    if prev_vol > 0:
        diff_pct = ((cur_vol - prev_vol) / prev_vol) * 100.0
        pct_str = f" ({'+' if diff_pct >= 0 else ''}{diff_pct:.1f}% к прошл. периоду)"
    else:
        pct_str = ""

    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    disk_info = get_monitored_disk_info(live)

    torrents = get_all_torrents(use_cache=True)
    deltas = summary_tracker.db.get_torrents_positive_deltas(since_ts)
    top3 = sorted(deltas.items(), key=lambda x: x[1], reverse=True)[:3]

    span_hours = int(round(span_sec / 3600.0))
    lbl = "Недельный дайджест" if mode == "weekly" else "Дневной дайджест"
    lines = [
        f"⏱️ Интервал: {span_hours} ч" + (" (дослан после простоя)" if delayed_sec > 3600 else ""),
        f"📤 Отдано: {format_file_size(cur_vol)}{pct_str}",
        f"💾 Свободно ({disk_info['path']}): {disk_info['free_fmt']}",
    ]
    if top3:
        lines.append("🏆 Топ-3 раздачи:")
        for idx, (h, val) in enumerate(top3, 1):
            nm = (torrents.get(h) or {}).get("name") or h[:10]
            lines.append(f"{idx}. {nm[:36]} — {format_file_size(val)}")

    cfg.set("Digest_Last_Sent_Ts", str(int(now_ts)))
    cfg.save()
    send_fn(f"📊 tbr PRO — {lbl}", lines, critical=False)
    app_state_db.add_audit_event("automation", lbl, f"Отдано {format_file_size(cur_vol)}")
    return True