# core/config_vault.py
import os
import shutil
import difflib
import datetime
from utils.config import cfg
from utils.helpers import APP_DATA_DIR, format_file_size, write_error_log
from core.qb_process import is_qb_running

VAULT_DIR = os.path.join(APP_DATA_DIR, "qb_config_vault")
os.makedirs(VAULT_DIR, exist_ok=True)
TARGET_FILES = ("qBittorrent.ini", "qBittorrent.conf", "categories.json", "watched_folders.json")


def detect_qb_config_dir():
    custom = cfg.get("QB_Config_Dir", "").strip()
    if custom and os.path.isdir(custom):
        return custom
    if os.name == "nt":
        cands = [
            os.path.join(os.environ.get("APPDATA", ""), "qBittorrent"),
            os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "qBittorrent"),
            os.path.join(os.path.expanduser("~"), "AppData", "Local", "qBittorrent"),
        ]
    else:
        cands = [
            "/config/qBittorrent",
            "/config",
            os.path.join(os.path.expanduser("~"), ".config", "qBittorrent"),
        ]
    for c in cands:
        if c and os.path.isdir(c):
            return c
    return ""


def _atomic_copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".tmp"
    shutil.copy2(src, tmp)
    with open(tmp, "rb") as f:
        os.fsync(f.fileno())
    os.replace(tmp, dst)


def create_config_backup(reason="manual", max_keep=10):
    src_dir = detect_qb_config_dir()
    if not src_dir or not os.path.isdir(src_dir):
        return False, "Папка конфигов qBittorrent не найдена. Укажите её вручную."

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    snap_name = f"cfg_{ts}_{reason}"
    snap_dir = os.path.join(VAULT_DIR, snap_name)
    os.makedirs(snap_dir, exist_ok=True)

    copied = []
    for fname in TARGET_FILES:
        src_p = os.path.join(src_dir, fname)
        if os.path.isfile(src_p):
            _atomic_copy(src_p, os.path.join(snap_dir, fname))
            copied.append(fname)

    rss_src = os.path.join(src_dir, "rss")
    if os.path.isdir(rss_src):
        shutil.copytree(rss_src, os.path.join(snap_dir, "rss"), dirs_exist_ok=True)
        copied.append("rss/")

    if not copied:
        shutil.rmtree(snap_dir, ignore_errors=True)
        return False, f"В {src_dir} не найдено целевых конфигов qBittorrent."

    try:
        snaps = sorted(
            [os.path.join(VAULT_DIR, d) for d in os.listdir(VAULT_DIR) if os.path.isdir(os.path.join(VAULT_DIR, d))],
            key=lambda p: os.path.getmtime(p), reverse=True
        )
        for old_d in snaps[max_keep:]:
            shutil.rmtree(old_d, ignore_errors=True)
    except Exception as e:
        write_error_log("rotate config_vault", e)

    return True, {"name": snap_name, "files": copied, "src_dir": src_dir}


def list_config_backups():
    out = []
    try:
        for d in os.listdir(VAULT_DIR):
            dp = os.path.join(VAULT_DIR, d)
            if not os.path.isdir(dp):
                continue
            files = []
            sz = 0
            for ent in os.scandir(dp):
                if ent.is_file():
                    files.append(ent.name)
                    sz += ent.stat().st_size
                elif ent.is_dir():
                    files.append(ent.name + "/")
            out.append({
                "name": d,
                "files": sorted(files),
                "size_fmt": format_file_size(sz),
                "mtime": int(os.path.getmtime(dp)),
                "date": datetime.datetime.fromtimestamp(os.path.getmtime(dp)).strftime("%Y-%m-%d %H:%M:%S")
            })
        out.sort(key=lambda x: x["mtime"], reverse=True)
    except Exception:
        pass
    return out


def _safe_snap_dir(name):
    clean = os.path.basename(str(name or "").replace("\\", "/"))
    full = os.path.abspath(os.path.join(VAULT_DIR, clean))
    if os.path.commonpath([os.path.abspath(VAULT_DIR), full]) == os.path.abspath(VAULT_DIR) and os.path.isdir(full):
        return full
    return None


def _read_lines_safe(path):
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.readlines()


def diff_config_backups(snap_a, snap_b, filename):
    da, db = _safe_snap_dir(snap_a), _safe_snap_dir(snap_b)
    clean_f = os.path.basename(str(filename or ""))
    if not da or not db or clean_f not in TARGET_FILES:
        return False, "Некорректные параметры для сравнения."

    la = _read_lines_safe(os.path.join(da, clean_f))
    lb = _read_lines_safe(os.path.join(db, clean_f))
    diff_txt = "".join(difflib.unified_diff(la, lb, fromfile=snap_a, tofile=snap_b, lineterm="\n"))
    return True, diff_txt or "Различий в файле не найдено."


def restore_config_backup(snap_name):
    if is_qb_running():
        return False, "🛑 Восстановление заблокировано: сначала остановите qBittorrent (иначе клиент перезапишет конфиг из памяти при выходе)."
    snap_dir = _safe_snap_dir(snap_name)
    dst_dir = detect_qb_config_dir()
    if not snap_dir or not dst_dir or not os.path.isdir(dst_dir):
        return False, "Снимок или папка конфигов qBittorrent не найдены."

    restored = []
    for fname in TARGET_FILES:
        src_p = os.path.join(snap_dir, fname)
        if os.path.isfile(src_p):
            _atomic_copy(src_p, os.path.join(dst_dir, fname))
            restored.append(fname)
    rss_src = os.path.join(snap_dir, "rss")
    if os.path.isdir(rss_src):
        shutil.copytree(rss_src, os.path.join(dst_dir, "rss"), dirs_exist_ok=True)
        restored.append("rss/")
    return True, f"✅ Восстановлено в {dst_dir}: {', '.join(restored)}"