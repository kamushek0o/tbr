# core/soft_trash.py
import os
import json
import time
import shutil
import secrets
import datetime
from utils.config import cfg
from utils.helpers import APP_DATA_DIR, BT_BACKUP_PATH, format_file_size, write_error_log, write_log
from core.disk_monitor import _find_mount_root, list_active_disks

SNAPSHOTS_DIR = os.path.join(APP_DATA_DIR, "fastresume_snapshots")
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)


def _trash_root_for_path(target_path):
    """Создаёт _tbr_trash в корне того же тома/раздела для мгновенного os.replace."""
    mount = _find_mount_root(target_path)
    cand = os.path.join(mount, "_tbr_trash")
    try:
        os.makedirs(cand, exist_ok=True)
        return cand
    except PermissionError:
        # Фоллбэк на том же томе, если корень системного диска закрыт UAC
        same_drive_app = os.path.splitdrive(os.path.abspath(APP_DATA_DIR))[0].upper()
        target_drive = os.path.splitdrive(os.path.abspath(target_path))[0].upper()
        if os.name == "nt" and same_drive_app == target_drive:
            alt = os.path.join(APP_DATA_DIR, "_tbr_trash")
        else:
            alt = os.path.join(os.path.dirname(os.path.abspath(target_path)), "_tbr_trash")
        os.makedirs(alt, exist_ok=True)
        return alt


def _entry_size(path):
    if os.path.isfile(path) or os.path.islink(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, _, files in os.walk(path, followlinks=False):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total


def _atomic_write_json(fpath, data):
    tmp = fpath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, fpath)


def move_to_trash(target_path, name="", t_hash="", ttl_days=None, actor="admin"):
    abs_p = os.path.abspath(str(target_path or "").strip())
    if not os.path.exists(abs_p) and not os.path.islink(abs_p):
        return False, "Путь не найден"

    ttl = int(ttl_days if ttl_days is not None else cfg.getint("Trash_TTL_Days", 7))
    trash_root = _trash_root_for_path(abs_p)
    item_id = f"{int(time.time())}_{secrets.token_hex(4)}"
    item_dir = os.path.join(trash_root, item_id)
    os.makedirs(item_dir, exist_ok=True)

    sz = _entry_size(abs_p)
    base_name = os.path.basename(abs_p)
    payload_dst = os.path.join(item_dir, "payload_" + base_name)

    try:
        os.replace(abs_p, payload_dst)
    except OSError:
        shutil.move(abs_p, payload_dst)

    has_tor = False
    if t_hash and os.path.isdir(BT_BACKUP_PATH):
        tor_cand = os.path.join(BT_BACKUP_PATH, t_hash.lower() + ".torrent")
        if os.path.isfile(tor_cand):
            shutil.copy2(tor_cand, os.path.join(item_dir, "backup.torrent"))
            has_tor = True

    now = time.time()
    meta = {
        "id": item_id,
        "name": name or base_name,
        "hash": str(t_hash or "").lower(),
        "original_path": abs_p,
        "payload_path": payload_dst,
        "trash_root": trash_root,
        "size": sz,
        "size_fmt": format_file_size(sz),
        "has_torrent": has_tor,
        "deleted_at": now,
        "expires_at": now + (max(1, ttl) * 86400),
        "actor": actor
    }
    _atomic_write_json(os.path.join(item_dir, "meta.json"), meta)
    write_log("system", f"Soft-Delete -> _tbr_trash: '{meta['name']}' ({meta['size_fmt']})")
    return True, meta


def _discover_trash_roots():
    roots = set()
    for d in list_active_disks():
        cand = os.path.join(d["path"], "_tbr_trash")
        if os.path.isdir(cand):
            roots.add(cand)
    app_tr = os.path.join(APP_DATA_DIR, "_tbr_trash")
    if os.path.isdir(app_tr):
        roots.add(app_tr)
    return sorted(roots)


def list_trash_items():
    items = []
    for tr_root in _discover_trash_roots():
        try:
            for ent in os.scandir(tr_root):
                if not ent.is_dir():
                    continue
                meta_p = os.path.join(ent.path, "meta.json")
                if not os.path.isfile(meta_p):
                    continue
                try:
                    with open(meta_p, "r", encoding="utf-8") as f:
                        m = json.load(f)
                    m["item_dir"] = ent.path
                    m["deleted_fmt"] = datetime.datetime.fromtimestamp(m.get("deleted_at", 0)).strftime("%Y-%m-%d %H:%M")
                    m["expires_fmt"] = datetime.datetime.fromtimestamp(m.get("expires_at", 0)).strftime("%Y-%m-%d %H:%M")
                    items.append(m)
                except Exception:
                    continue
        except Exception:
            continue
    items.sort(key=lambda x: x.get("deleted_at", 0), reverse=True)
    return items


def restore_trash_item(item_id):
    target = next((x for x in list_trash_items() if x.get("id") == item_id), None)
    if not target:
        return False, "Запись в корзине не найдена"
    orig = target["original_path"]
    payload = target["payload_path"]
    if os.path.exists(orig):
        return False, f"Целевой путь уже существует: {orig}"
    if not os.path.exists(payload):
        return False, "Содержимое корзины отсутствует на диске"

    os.makedirs(os.path.dirname(orig), exist_ok=True)
    try:
        os.replace(payload, orig)
    except OSError:
        shutil.move(payload, orig)

    tor_bak = os.path.join(target["item_dir"], "backup.torrent")
    if os.path.isfile(tor_bak) and target.get("hash") and os.path.isdir(BT_BACKUP_PATH):
        dst_tor = os.path.join(BT_BACKUP_PATH, target["hash"] + ".torrent")
        if not os.path.exists(dst_tor):
            shutil.copy2(tor_bak, dst_tor)

    shutil.rmtree(target["item_dir"], ignore_errors=True)
    return True, f"Восстановлено в {orig}"


def purge_trash_item(item_id):
    target = next((x for x in list_trash_items() if x.get("id") == item_id), None)
    if not target:
        return False, "Запись не найдена"
    shutil.rmtree(target["item_dir"], ignore_errors=True)
    return True, f"Удалено безвозвратно: {target.get('name')}"


def cleanup_expired_trash():
    now = time.time()
    removed = 0
    for item in list_trash_items():
        if float(item.get("expires_at") or 0) <= now:
            shutil.rmtree(item["item_dir"], ignore_errors=True)
            removed += 1
    return removed


def create_fastresume_snapshot(hashes, reason="pre_op", max_keep=10):
    if not hashes or not os.path.isdir(BT_BACKUP_PATH):
        return None
    ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    snap_dir = os.path.join(SNAPSHOTS_DIR, f"{ts_str}_{reason}")
    os.makedirs(snap_dir, exist_ok=True)
    copied = 0
    for h in hashes:
        hl = str(h or "").strip().lower()
        for ext in (".fastresume", ".torrent"):
            src = os.path.join(BT_BACKUP_PATH, hl + ext)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(snap_dir, hl + ext))
                copied += 1
    if copied == 0:
        shutil.rmtree(snap_dir, ignore_errors=True)
        return None

    try:
        snaps = sorted(
            [os.path.join(SNAPSHOTS_DIR, d) for d in os.listdir(SNAPSHOTS_DIR) if os.path.isdir(os.path.join(SNAPSHOTS_DIR, d))],
            key=lambda p: os.path.getmtime(p), reverse=True
        )
        for old_d in snaps[max_keep:]:
            shutil.rmtree(old_d, ignore_errors=True)
    except Exception as e:
        write_error_log("rotate fastresume_snapshots", e)
    return snap_dir