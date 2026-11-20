# core/hdd_smart_queue.py
import os
import json
import time
import shutil
import subprocess
from utils.config import cfg
from utils.helpers import write_error_log
from core.app_state_db import app_state_db
from core.qb_api import recheck_torrents
from core.disk_monitor import _get_mount_key

_WIN_FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
_CHECKING_STATES = {'checkingup', 'checkingdl', 'checkingresumedata'}


def _ensure_table():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS recheck_queue (
                        hash_id TEXT PRIMARY KEY,
                        drive_key TEXT NOT NULL,
                        name TEXT NOT NULL,
                        added_at REAL NOT NULL
                    )
                """)
                conn.commit()
        except Exception as e:
            write_error_log("recheck_queue init", e)


_ensure_table()


def enqueue_recheck(t_hash, save_path='', name=''):
    hl = str(t_hash or '').strip().lower()
    if not hl:
        return False
    dkey = _get_mount_key(save_path) if save_path and os.path.exists(save_path) else 'default'
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO recheck_queue (hash_id, drive_key, name, added_at) VALUES (?, ?, ?, ?)",
                    (hl, dkey, str(name or hl)[:160], time.time())
                )
                conn.commit()
                return True
        except Exception:
            return False


def list_recheck_queue():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                return [dict(r) for r in conn.execute("SELECT * FROM recheck_queue ORDER BY added_at ASC").fetchall()]
        except Exception:
            return []


def tick_recheck_queue(ip, port, live):
    """Гарантирует не более 1 активного речека на физический диск."""
    if not port or not live:
        return 0
    queue = list_recheck_queue()
    if not queue:
        return 0

    busy_drives = set()
    live_map = {}
    for raw_h, info in live.items():
        live_map[raw_h.lower()] = (raw_h, info)
        if str(info.get('state', '')).lower() in _CHECKING_STATES:
            sp = str(info.get('save_path') or '')
            busy_drives.add(_get_mount_key(sp) if sp and os.path.exists(sp) else 'default')

    started = 0
    for item in queue:
        hl, dkey = item['hash_id'], item['drive_key']
        if hl not in live_map:
            with app_state_db._lock:
                with app_state_db._get_conn() as conn:
                    conn.execute("DELETE FROM recheck_queue WHERE hash_id = ?", (hl,))
                    conn.commit()
            continue
        if dkey in busy_drives:
            continue
        raw_h, _ = live_map[hl]
        if recheck_torrents(ip, port, raw_h):
            busy_drives.add(dkey)
            started += 1
            with app_state_db._lock:
                with app_state_db._get_conn() as conn:
                    conn.execute("DELETE FROM recheck_queue WHERE hash_id = ?", (hl,))
                    conn.commit()
    return started


def get_smart_disks_status():
    """Опциональный SMART-монитор через smartctl с безопасным фоллбэком."""
    exe = shutil.which('smartctl')
    if not exe:
        return {'available': False, 'reason': 'Утилита smartctl (smartmontools) не установлена в системе', 'disks': []}

    try:
        scan = subprocess.run([exe, '--scan', '-j'], capture_output=True, text=True, timeout=4.0, creationflags=_WIN_FLAGS)
        data = json.loads(scan.stdout or '{}')
        devs = [d.get('name') for d in (data.get('devices') or []) if d.get('name')]
    except Exception as e:
        return {'available': False, 'reason': f'Нет доступа к SMART (нужны права Администратора/root): {e}', 'disks': []}

    disks = []
    for dev in devs[:10]:
        try:
            r = subprocess.run([exe, '-A', '-H', '-j', dev], capture_output=True, text=True, timeout=4.0, creationflags=_WIN_FLAGS)
            info = json.loads(r.stdout or '{}')
            passed = (info.get('smart_status') or {}).get('passed')
            temp = (info.get('temperature') or {}).get('current')
            model = info.get('model_name') or dev
            disks.append({'device': dev, 'model': model, 'passed': passed, 'temp_c': temp})
        except Exception:
            continue

    if not disks:
        return {'available': False, 'reason': 'Не удалось прочитать SMART-атрибуты (требуются повышенные права)', 'disks': []}
    return {'available': True, 'disks': disks}