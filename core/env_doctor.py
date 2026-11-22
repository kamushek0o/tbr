# core/env_doctor.py
import os
import re
import time
import sqlite3
import platform
import email.utils
import urllib.request
from utils.config import cfg
from utils.helpers import APP_DATA_DIR, BT_BACKUP_PATH, LOG_FOLDER
from core.version import APP_VERSION
from core.qb_api import detect_qbittorrent_port, check_qb_api_alive, get_qb_version, is_qb_running
from core.disk_monitor import list_active_disks
from core.config_vault import detect_qb_config_dir

_DB_LIST = [
    ("summary_history.db", os.path.join(LOG_FOLDER, "auto_hourly", "summary_history.db")),
    ("profiles.db", os.path.join(APP_DATA_DIR, "profiles.db")),
    ("automation.db", os.path.join(APP_DATA_DIR, "automation.db")),
    ("app_state.db", os.path.join(APP_DATA_DIR, "app_state.db")),
    ("file_index.db", os.path.join(APP_DATA_DIR, "file_index.db")),
]


def _check_time_skew():
    try:
        req = urllib.request.Request("https://api.github.com", method="HEAD", headers={"User-Agent": f"tbr-pro/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            hdr = resp.headers.get("Date")
            if hdr:
                remote_ts = email.utils.mktime_tz(email.utils.parsedate_tz(hdr))
                diff = abs(time.time() - remote_ts)
                return {"ok": diff < 120, "skew_sec": round(diff, 1)}
    except Exception:
        pass
    return {"ok": None, "skew_sec": None}


def run_environment_doctor():
    ip, port = detect_qbittorrent_port(cfg.config)
    api_ok = check_qb_api_alive(ip, port) if port else False
    qb_ver = get_qb_version(ip, port, timeout=2.0) if api_ok else None

    bt_exists = os.path.isdir(BT_BACKUP_PATH)
    bt_rw = False
    if bt_exists:
        test_f = os.path.join(BT_BACKUP_PATH, ".tbr_rw_test.tmp")
        try:
            with open(test_f, "w") as f:
                f.write("ok")
            os.remove(test_f)
            bt_rw = True
        except Exception:
            bt_rw = False

    dbs = []
    for name, path in _DB_LIST:
        if not os.path.isfile(path):
            dbs.append({"name": name, "exists": False, "quick_check": "missing", "wal": False})
            continue
        try:
            conn = sqlite3.connect(path, timeout=5.0)
            qc = conn.execute("PRAGMA quick_check;").fetchone()[0]
            jm = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            conn.close()
            dbs.append({"name": name, "exists": True, "quick_check": str(qc), "wal": str(jm).lower() == "wal"})
        except Exception as e:
            dbs.append({"name": name, "exists": True, "quick_check": f"error: {e}", "wal": False})

    return {
        "app_version": APP_VERSION,
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "qb": {
            "running": is_qb_running(),
            "ip": ip, "port": port,
            "api_ok": api_ok,
            "version": qb_ver or ("OK" if api_ok else "не отвечает"),
            "config_dir": detect_qb_config_dir() or "не найдена"
        },
        "bt_backup": {"path": BT_BACKUP_PATH, "exists": bt_exists, "rw": bt_rw},
        "databases": dbs,
        "disks": list_active_disks(),
        "notifiers": {
            "telegram_configured": bool(cfg.get("TG_Bot_Token", "").strip() and cfg.get("TG_Chat_ID", "").strip()),
            "discord_configured": bool(cfg.get("Discord_Webhook", "").strip())
        },
        "time_skew": _check_time_skew()
    }


def sanitize_text_for_github(raw_text):
    s = str(raw_text or "")
    s = re.sub(r'tbr_api_[A-Za-z0-9_\-]+', 'tbr_api_<REDACTED>', s)
    s = re.sub(r'inv_[A-Za-z0-9_\-]+', 'inv_<REDACTED>', s)
    s = re.sub(r'bot\d+:[A-Za-z0-9_\-]+', 'bot<REDACTED>', s)
    s = re.sub(r'https://discord(?:app)?\.com/api/webhooks/[^\s\)]+', 'https://discord.com/api/webhooks/<REDACTED>', s)
    s = re.sub(r'passkey=[A-Za-z0-9]+', 'passkey=<REDACTED>', s, flags=re.IGNORECASE)
    s = re.sub(r'C:\\Users\\[^\\\s]+', r'C:\\Users\\<USER>', s, flags=re.IGNORECASE)
    s = re.sub(r'/home/[^/\s]+', '/home/<USER>', s)
    s = re.sub(r'\b(?!127\.0\.0\.1\b)(?!10\.)(?!192\.168\.)(?!100\.)\d{1,3}(?:\.\d{1,3}){3}\b', '<EXTERNAL_IP>', s)
    return s


def generate_github_issue_report(diag=None):
    d = diag or run_environment_doctor()
    db_lines = "\n".join(f"  - `{x['name']}`: quick_check=`{x['quick_check']}`, WAL=`{x['wal']}`" for x in d["databases"])
    disk_lines = "\n".join(f"  - `{dk['path']}`: {dk['free_fmt']} free / {dk['total_fmt']} ({dk['torrents_count']} torrents)" for dk in d["disks"])
    skew = d["time_skew"]
    skew_txt = f"{skew['skew_sec']}s" if skew["skew_sec"] is not None else "n/a"

    md = (
        f"### Environment Report — tbr PRO v{d['app_version']}\n"
        f"- **OS / Python:** `{d['os']}` / Python `{d['python']}`\n"
        f"- **qBittorrent:** running=`{d['qb']['running']}`, API=`{d['qb']['api_ok']}` (`{d['qb']['version']}`)\n"
        f"- **BT_backup:** exists=`{d['bt_backup']['exists']}`, rw=`{d['bt_backup']['rw']}`\n"
        f"- **Time Skew (vs GitHub UTC):** `{skew_txt}`\n"
        f"- **Notifiers:** TG=`{d['notifiers']['telegram_configured']}`, Discord=`{d['notifiers']['discord_configured']}`\n"
        f"- **Databases:**\n{db_lines}\n"
        f"- **Disks:**\n{disk_lines}\n"
    )
    return sanitize_text_for_github(md)


def probe_onboarding_defaults():
    ip, port = detect_qbittorrent_port(cfg.config)
    diag = run_environment_doctor()
    return {
        "completed": cfg.getboolean("Onboarding_Completed", False),
        "detected_ip": ip,
        "detected_port": port,
        "qb_api_ok": diag["qb"]["api_ok"],
        "qb_version": diag["qb"]["version"],
        "bt_backup_ok": diag["bt_backup"]["exists"] and diag["bt_backup"]["rw"],
        "disks": diag["disks"],
        "max_channel_mbps": cfg.getint("Max_Channel_Mbps", 1000)
    }