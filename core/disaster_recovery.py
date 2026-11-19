# core/disaster_recovery.py
import os
import json
import time
import datetime
import urllib.parse
from utils.config import cfg
from utils.helpers import APP_DATA_DIR, format_file_size, write_log, write_error_log
from core.app_state_db import app_state_db
from core.notifiers import notify_all
from core.torrent_parser import get_all_torrents
from core.qb_api import (
    detect_qbittorrent_port, get_live_torrent_info, send_qb_command,
    set_global_speed_limits, shutdown_qb_webui, close_qbittorrent
)

MANIFESTS_DIR = os.path.join(APP_DATA_DIR, "manifests")
os.makedirs(MANIFESTS_DIR, exist_ok=True)


def execute_panic_killswitch(kill_qb=False, actor="admin"):
    ip, port = detect_qbittorrent_port(cfg.config)
    details = []

    if port:
        if send_qb_command(ip, port, "stop", "all"):
            details.append("Все раздачи поставлены на паузу")
        if set_global_speed_limits(ip, port, 1, 1):
            details.append("Глобальный лимит скорости зажат до 1 B/s")

    frozen_until = int(time.time() + 3600)
    cfg.set("Autopilot_Frozen_Until", str(frozen_until))
    cfg.save()
    details.append("Автопилот заморожен на 1 час")

    if kill_qb:
        if port:
            shutdown_qb_webui(ip, port)
        if os.name == "nt":
            close_qbittorrent()
        details.append("Отправлена команда завершения qBittorrent")

    summary = "; ".join(details)
    write_log("app", f"PANIC KILLSWITCH ({actor}): {summary}")
    app_state_db.add_audit_event("system", "Panic Killswitch", summary, actor=actor)
    notify_all("🚨 PANIC KILLSWITCH АКТИВИРОВАН", details, critical=True)

    return {"success": True, "details": details, "frozen_until": frozen_until}


def _build_magnet(t_hash, name, trackers):
    params = [("xt", f"urn:btih:{t_hash}"), ("dn", name)]
    for tr in trackers:
        if tr:
            params.append(("tr", tr))
    return "magnet:?" + "&".join(f"{k}={urllib.parse.quote(str(v), safe=':')}" for k, v in params)


def _prune_old_manifests(max_keep=2):
    try:
        files = [
            os.path.join(MANIFESTS_DIR, f)
            for f in os.listdir(MANIFESTS_DIR)
            if f.startswith("tbr_manifest_") and f.endswith(".json")
        ]
        files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        for old_path in files[max_keep:]:
            try:
                os.remove(old_path)
            except OSError:
                pass
    except Exception as e:
        write_error_log("Ротация аварийных манифестов", e)


def create_disaster_manifest(actor="admin"):
    from core.version import APP_VERSION
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    parsed = get_all_torrents(use_cache=True)

    items = []
    seen = set()
    for h, st in parsed.items():
        seen.add(h.lower())
        lv = live.get(h) or live.get(h.lower()) or {}
        name = str(lv.get("name") or st.get("name") or h)
        size = int(lv.get("total_size") or st.get("size") or 0)
        trackers = list(st.get("trackers") or [])
        tr_live = str(lv.get("tracker") or "").strip()
        if tr_live and tr_live not in trackers:
            trackers.insert(0, tr_live)
        items.append({
            "name": name,
            "hash": h.lower(),
            "size": size,
            "size_fmt": format_file_size(size),
            "trackers": trackers,
            "magnet": _build_magnet(h.lower(), name, trackers),
        })

    for h, lv in live.items():
        hl = h.lower()
        if hl in seen:
            continue
        name = str(lv.get("name") or hl)
        size = int(lv.get("total_size") or 0)
        tr_live = str(lv.get("tracker") or "").strip()
        trackers = [tr_live] if tr_live else []
        items.append({
            "name": name,
            "hash": hl,
            "size": size,
            "size_fmt": format_file_size(size),
            "trackers": trackers,
            "magnet": _build_magnet(hl, name, trackers),
        })

    items.sort(key=lambda x: x["name"].lower())
    ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"tbr_manifest_{ts_str}.json"
    fpath = os.path.join(MANIFESTS_DIR, fname)

    payload = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "app_version": APP_VERSION,
        "count": len(items),
        "torrents": items,
    }
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    _prune_old_manifests(max_keep=2)
    cfg.set("Manifest_Last_Run", str(int(time.time())))
    cfg.save()
    app_state_db.add_audit_event("system", "Аварийный манифест", f"Создан {fname} ({len(items)} раздач)", actor=actor)
    return {"filename": fname, "count": len(items), "size": os.path.getsize(fpath)}


def list_manifests():
    res = []
    try:
        for f in os.listdir(MANIFESTS_DIR):
            if f.startswith("tbr_manifest_") and f.endswith(".json"):
                p = os.path.join(MANIFESTS_DIR, f)
                res.append({
                    "filename": f,
                    "size_fmt": format_file_size(os.path.getsize(p)),
                    "mtime": int(os.path.getmtime(p)),
                    "date": datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S"),
                })
        res.sort(key=lambda x: x["mtime"], reverse=True)
    except Exception:
        pass
    return res[:2]


def get_manifest_path(filename):
    clean = os.path.basename(str(filename or "").replace("\\", "/"))
    if not clean or not clean.startswith("tbr_manifest_") or not clean.endswith(".json"):
        return None
    base = os.path.abspath(MANIFESTS_DIR)
    full = os.path.abspath(os.path.join(base, clean))
    if os.path.commonpath([base, full]) == base and os.path.isfile(full):
        return full
    return None


def maybe_run_weekly_manifest():
    if not cfg.getboolean("Manifest_Weekly", False):
        return
    last_ts = cfg.getint("Manifest_Last_Run", 0)
    if (time.time() - last_ts) >= 7 * 86400:
        try:
            create_disaster_manifest(actor="scheduler")
        except Exception as e:
            write_error_log("Еженедельный манифест", e)