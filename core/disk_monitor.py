# core/disk_monitor.py
import os
import shutil
from utils.config import cfg
from utils.helpers import BT_BACKUP_PATH, APP_DATA_DIR, format_file_size
from core.torrent_parser import get_all_torrents


def _get_mount_key(path):
    ap = os.path.abspath(str(path).strip())
    if os.name == 'nt':
        drive, _ = os.path.splitdrive(ap)
        if drive:
            return drive.upper() + os.sep
    try:
        st = os.stat(ap)
        return f"dev:{st.st_dev}"
    except Exception:
        return ap


def _find_mount_root(path):
    ap = os.path.abspath(str(path).strip())
    if os.name == 'nt':
        drive, _ = os.path.splitdrive(ap)
        return (drive.upper() + os.sep) if drive else ap
    cur = ap
    while cur != os.path.dirname(cur):
        parent = os.path.dirname(cur)
        if os.path.ismount(cur) or not os.path.exists(parent):
            return cur
        try:
            if os.stat(cur).st_dev != os.stat(parent).st_dev:
                return cur
        except Exception:
            break
        cur = parent
    return cur


def list_active_disks(live=None):
    """Собирает уникальные диски/точки монтирования по save_path всех раздач."""
    mounts = {}

    def register_path(raw_p, weight=1):
        if not raw_p or not str(raw_p).strip():
            return
        p = str(raw_p).strip()
        if not os.path.exists(p):
            return
        key = _get_mount_key(p)
        if key not in mounts:
            root = _find_mount_root(p)
            try:
                usage = shutil.disk_usage(p)
                mounts[key] = {
                    'key': key,
                    'path': root,
                    'probe_path': p,
                    'torrents_count': 0,
                    'free_bytes': usage.free,
                    'total_bytes': usage.total,
                    'free_fmt': format_file_size(usage.free),
                    'total_fmt': format_file_size(usage.total),
                }
            except Exception:
                return
        mounts[key]['torrents_count'] += weight

    if live:
        for info in live.values():
            register_path(info.get('save_path'), weight=1)
    else:
        for st in get_all_torrents(use_cache=True).values():
            register_path(st.get('save_path'), weight=1)

    if not mounts:
        for fallback in (BT_BACKUP_PATH, APP_DATA_DIR):
            if fallback and os.path.exists(fallback):
                register_path(fallback, weight=0)
                break

    res = sorted(mounts.values(), key=lambda x: (x['torrents_count'], x['total_bytes']), reverse=True)
    return res


def get_monitored_disk_info(live=None):
    """Возвращает выбранный в настройках диск или диск с наибольшим числом раздач."""
    disks = list_active_disks(live)
    if not disks:
        return {'path': '—', 'free_bytes': 0, 'total_bytes': 0, 'free_fmt': '—', 'torrents_count': 0}

    preferred = cfg.get('Monitored_Disk_Path', '').strip()
    if preferred:
        pref_key = _get_mount_key(preferred)
        for d in disks:
            if d['key'] == pref_key or d['path'] == preferred:
                return d
        if os.path.exists(preferred):
            try:
                usage = shutil.disk_usage(preferred)
                return {
                    'path': preferred,
                    'free_bytes': usage.free,
                    'total_bytes': usage.total,
                    'free_fmt': format_file_size(usage.free),
                    'torrents_count': 0
                }
            except Exception:
                pass

    return disks[0]