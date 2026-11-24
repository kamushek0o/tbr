### Какой диск смотрится сейчас и в чём был подвох:
По умолчанию тюнер смотрел на **основной диск с наибольшим числом раздач** (или выбранный в общих `⚙️ Настройки`). 

Но под капотом Windows был критический баг: `psutil.disk_io_counters(perdisk=True)` возвращает ключи физических накопителей — `PhysicalDrive0`, `PhysicalDrive1` (а не буквы `C:` или `D:`). Из-за этого привязка по букве диска сбивалась на максимум по всем дискам, и в интерфейсе вообще не было видно, какой накопитель сейчас опрашивается.

### План
1. `core/tuner_telemetry.py` — внедряем Win32 API маппинг (`IOCTL_STORAGE_GET_DEVICE_NUMBER` через стандартный `ctypes`) и Linux `/sys/dev/block`, точно связывающие букву/точку монтирования с `PhysicalDriveX` / `sdX`. Добавляем поддержку режимов: `Авто`, `Все диски (Max)` или конкретный диск (`D:\`), а также возврат понятного лейбла `monitored_disk_label`.
2. `core/tuner_db.py` & `core/tuner_engine.py` — прописываем `target_disk` в дефолтные профили тюнера и передаём выбранный диск в сборщик телеметрии.
3. `web/routes/tuner_bp.py` — прокидываем список активных дисков `available_disks` в эндпоинт `/api/tuner/state`.
4. `web/templates/partials/tab_tuner.html` & `web/static/tuner_ui.js` — добавляем выпадающий список дисков прямо в строку «Диск I/O» и динамически выводим текущий опрашиваемый накопитель в шапку карточки телеметрии (`Диск I/O (D:)` или `Диск I/O (Все)`).

---

#### `core/tuner_telemetry.py`
```python
# core/tuner_telemetry.py
import os
import time
from utils.config import cfg
from core.disk_monitor import get_monitored_disk_info

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False


def _get_windows_physical_drive(drive_letter):
    letter = str(drive_letter or '').strip().rstrip(':\\/').upper()
    if not letter or len(letter) != 1 or not ('A' <= letter <= 'Z'):
        return None
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        h_dev = kernel32.CreateFileW(f"\\\\.\\{letter}:", 0, 3, None, 3, 0, None)
        if h_dev == -1 or h_dev == wintypes.HANDLE(-1).value:
            h_dev = kernel32.CreateFileW(f"\\\\.\\{letter}:", 0x80000000, 3, None, 3, 0, None)
        if h_dev != -1 and h_dev != wintypes.HANDLE(-1).value:
            class STORAGE_DEVICE_NUMBER(ctypes.Structure):
                _fields_ = [
                    ('DeviceType', wintypes.DWORD),
                    ('DeviceNumber', wintypes.DWORD),
                    ('PartitionNumber', wintypes.DWORD)
                ]
            dev_num = STORAGE_DEVICE_NUMBER()
            bytes_ret = wintypes.DWORD()
            ok = kernel32.DeviceIoControl(h_dev, 0x002D1080, None, 0, ctypes.byref(dev_num), ctypes.sizeof(dev_num), ctypes.byref(bytes_ret), None)
            kernel32.CloseHandle(h_dev)
            if ok:
                return f"PhysicalDrive{dev_num.DeviceNumber}"
    except Exception:
        pass
    return None


def _get_linux_block_device(path):
    if not path or not os.path.exists(path):
        return None
    try:
        st = os.stat(path)
        major = os.major(st.st_dev)
        minor = os.minor(st.st_dev)
        sys_path = f"/sys/dev/block/{major}:{minor}"
        if os.path.exists(sys_path):
            real = os.path.realpath(sys_path)
            parts = real.split(os.sep)
            if 'block' in parts:
                idx = parts.index('block')
                if idx + 1 < len(parts):
                    return parts[idx + 1]
    except Exception:
        pass
    return None


class TelemetryCollector:
    def __init__(self):
        self._qb_proc = None
        self._prev_ts = None
        self._prev_disk = None
        self._prev_net = None
        self._ema = {}

    def _smooth(self, key, val):
        if key not in self._ema:
            self._ema[key] = float(val)
        else:
            self._ema[key] = 0.3 * float(val) + 0.7 * self._ema[key]
        return self._ema[key]

    def _get_qb_process(self):
        if not HAS_PSUTIL:
            return None
        if self._qb_proc is not None:
            try:
                if self._qb_proc.is_running() and 'qbittorrent' in self._qb_proc.name().lower():
                    return self._qb_proc
            except Exception:
                self._qb_proc = None
        for p in psutil.process_iter(['pid', 'name']):
            try:
                nm = (p.info.get('name') or '').lower()
                if nm in ('qbittorrent.exe', 'qbittorrent-nox.exe', 'qbittorrent', 'qbittorrent-nox'):
                    p.cpu_percent(interval=None)
                    self._qb_proc = p
                    return p
            except Exception:
                continue
        return None

    def _measure_disk_busy(self, dt_ms, live, target_disk):
        if not HAS_PSUTIL or dt_ms <= 0:
            return 0.0, '—'
        try:
            counters = psutil.disk_io_counters(perdisk=True) or {}
        except Exception:
            return 0.0, '—'
        if self._prev_disk is None:
            self._prev_disk = counters
            return 0.0, '—'

        chosen_path = target_disk
        is_auto = False
        if not chosen_path:
            is_auto = True
            chosen_path = str(get_monitored_disk_info(live).get('path') or '')

        target_key = None
        label = 'Все'
        if chosen_path == 'ALL':
            label = 'Все'
        elif chosen_path:
            clean_p = os.path.splitdrive(chosen_path)[0].upper() or chosen_path
            label = f"Авто: {clean_p}" if is_auto else clean_p
            if os.name == 'nt':
                drive_letter = clean_p.rstrip(':\\/')
                target_key = _get_windows_physical_drive(drive_letter)
            else:
                target_key = _get_linux_block_device(chosen_path)

        max_busy = 0.0
        keys = [target_key] if (target_key and target_key in counters and target_key in self._prev_disk) else list(counters.keys())
        for k in keys:
            if k not in self._prev_disk or k not in counters:
                continue
            c_now, c_old = counters[k], self._prev_disk[k]
            d_read = max(0, getattr(c_now, 'read_time', 0) - getattr(c_old, 'read_time', 0))
            d_write = max(0, getattr(c_now, 'write_time', 0) - getattr(c_old, 'write_time', 0))
            busy = min(100.0, ((d_read + d_write) / dt_ms) * 100.0)
            if busy > max_busy:
                max_busy = busy

        self._prev_disk = counters
        return max_busy, label

    def collect(self, live, transfer_info, current_max_uploads, target_disk=''):
        now = time.monotonic()
        dt_sec = max(0.5, now - self._prev_ts) if self._prev_ts else 10.0
        dt_ms = dt_sec * 1000.0
        self._prev_ts = now

        qb_up = float(transfer_info.get('up_info_speed') or 0)
        qb_dl = float(transfer_info.get('dl_info_speed') or 0)
        max_mbps = max(10, cfg.getint('Max_Channel_Mbps', 1000))
        max_chan_bps = (max_mbps * 1_000_000) / 8.0

        disk_raw, disk_label = self._measure_disk_busy(dt_ms, live, target_disk)
        cpu_ext_raw, ram_free_raw, net_ext_raw = 0.0, 100.0, 0.0

        if HAS_PSUTIL:
            try:
                tot_cpu = psutil.cpu_percent(interval=None)
                cores = max(1, psutil.cpu_count(logical=True) or 1)
                qb_p = self._get_qb_process()
                qb_cpu_norm = (qb_p.cpu_percent(interval=None) / cores) if qb_p else 0.0
                cpu_ext_raw = max(0.0, tot_cpu - qb_cpu_norm)
            except Exception:
                pass

            try:
                vm = psutil.virtual_memory()
                ram_free_raw = (vm.available / max(1, vm.total)) * 100.0
            except Exception:
                pass

            try:
                net_now = psutil.net_io_counters()
                if self._prev_net is not None and net_now is not None:
                    d_tot = max(0, (net_now.bytes_sent - self._prev_net.bytes_sent) + (net_now.bytes_recv - self._prev_net.bytes_recv))
                    tot_bps = d_tot / dt_sec
                    net_ext_raw = max(0.0, tot_bps - (qb_dl + qb_up))
                self._prev_net = net_now
            except Exception:
                pass

        ema_disk = self._smooth('disk_busy', disk_raw)
        ema_cpu = self._smooth('cpu_ext', cpu_ext_raw)
        ema_ram = self._smooth('ram_free', ram_free_raw)
        ema_net_ext = self._smooth('net_ext_bps', net_ext_raw)
        ema_qb_up = self._smooth('qb_up_bps', qb_up)

        chan_pct = min(100.0, (ema_qb_up / max_chan_bps) * 100.0) if max_chan_bps > 0 else 0.0
        net_ext_pct = min(100.0, (ema_net_ext / max_chan_bps) * 100.0) if max_chan_bps > 0 else 0.0

        active_up_peers = sum(int(v.get('num_leechs', 0) or 0) for v in (live or {}).values() if int(v.get('upspeed', 0) or 0) > 0)
        cur_slots = max(1, int(current_max_uploads or 1))
        slots_fill_pct = min(100.0, (active_up_peers / cur_slots) * 100.0)

        return {
            'psutil_available': HAS_PSUTIL,
            'disk_busy': round(ema_disk, 1),
            'monitored_disk_label': disk_label,
            'cpu_ext': round(ema_cpu, 1),
            'ram_free': round(ema_ram, 1),
            'net_ext_bps': int(ema_net_ext),
            'net_ext_pct': round(net_ext_pct, 1),
            'qb_up_bps': int(ema_qb_up),
            'channel_pct': round(chan_pct, 1),
            'active_up_peers': active_up_peers,
            'slots_fill_pct': round(slots_fill_pct, 1),
            'max_channel_bps': int(max_chan_bps)
        }


def list_running_processes():
    if not HAS_PSUTIL:
        return []
    names = set()
    for p in psutil.process_iter(['name']):
        try:
            nm = str(p.info.get('name') or '').strip()
            if nm:
                names.add(nm)
        except Exception:
            continue
    return sorted(names, key=str.lower)


telemetry_collector = TelemetryCollector()
```

---

#### `core/tuner_db.py`
```python
# core/tuner_db.py
import json
import time
from copy import deepcopy
from core.app_state_db import app_state_db
from utils.helpers import write_error_log

ALLOWED_PREFS_KEYS = (
    'max_uploads', 'max_uploads_per_torrent',
    'max_connec', 'max_connec_per_torrent',
    'max_active_uploads', 'up_limit', 'dl_limit'
)

DEFAULT_PROFILES = {
    'performance': {
        'max_uploads_min': 15, 'max_uploads_max': 150, 'max_uploads_start': 40,
        'per_torrent_up_min': 4, 'per_torrent_up_max': 40, 'per_torrent_up_auto': True,
        'max_connec_min': 60, 'max_connec_max': 600, 'max_connec_auto': True,
        'per_torrent_connec_min': 15, 'per_torrent_connec_max': 150,
        'active_uploads_mode': 'keep', 'active_uploads_min': 10, 'active_uploads_max': 40,
        'channel_target_min': 85, 'channel_target_max': 100,
        'up_limit_pct': 0, 'dl_limit_pct': 0, 'squeeze_enabled': False, 'squeeze_up_pct': 70, 'squeeze_dl_pct': 70,
        'cooldown_sec': 180, 'step_up_size': 5,
        'yield_to_turtle': True,
        'guards': {
            'disk': {'enabled': False, 'target_disk': '', 'warn': 85, 'crit': 95, 'recover': 70},
            'cpu':  {'enabled': True,  'warn': 85, 'recover': 65},
            'ram':  {'enabled': True,  'min_free': 10, 'recover_free': 18},
            'net':  {'enabled': False, 'warn_pct': 45, 'recover_pct': 25},
        }
    },
    'comfort': {
        'max_uploads_min': 8, 'max_uploads_max': 45, 'max_uploads_start': 20,
        'per_torrent_up_min': 3, 'per_torrent_up_max': 15, 'per_torrent_up_auto': True,
        'max_connec_min': 40, 'max_connec_max': 220, 'max_connec_auto': True,
        'per_torrent_connec_min': 10, 'per_torrent_connec_max': 50,
        'active_uploads_mode': 'range', 'active_uploads_min': 4, 'active_uploads_max': 15,
        'channel_target_min': 55, 'channel_target_max': 75,
        'up_limit_pct': 75, 'dl_limit_pct': 75, 'squeeze_enabled': True, 'squeeze_up_pct': 40, 'squeeze_dl_pct': 40,
        'cooldown_sec': 180, 'step_up_size': 3,
        'yield_to_turtle': True,
        'guards': {
            'disk': {'enabled': True, 'target_disk': '', 'warn': 55, 'crit': 80, 'recover': 35},
            'cpu':  {'enabled': True, 'warn': 45, 'recover': 30},
            'ram':  {'enabled': True, 'min_free': 20, 'recover_free': 28},
            'net':  {'enabled': True, 'warn_pct': 20, 'recover_pct': 10},
        }
    }
}

DEFAULT_SWITCH_RULES = {
    'default_mode': 'performance',
    'override_policy': '2h',
    'schedules': [],
    'processes': {
        'enabled': False,
        'target_mode': 'comfort',
        'names': ['cs2.exe', 'dota2.exe', 'obs64.exe'],
        'enter_sec': 15,
        'exit_sec': 180
    },
    'external_load': {
        'enabled': False,
        'target_mode': 'comfort',
        'cpu_warn': 45, 'cpu_recover': 25,
        'net_warn_pct': 25, 'net_recover_pct': 12,
        'ram_min_free': 15, 'ram_recover_free': 25,
        'enter_sec': 30,
        'exit_sec': 300
    }
}


def _merge_dict(base, patch):
    res = deepcopy(base)
    if not isinstance(patch, dict):
        return res
    for k, v in patch.items():
        if k in res and isinstance(res[k], dict) and isinstance(v, dict):
            res[k] = _merge_dict(res[k], v)
        else:
            res[k] = v
    return res


def ensure_tuner_tables():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS tuner_state (
                        id INTEGER PRIMARY KEY CHECK(id = 1),
                        mode TEXT NOT NULL DEFAULT 'off',
                        auto_switch_enabled INTEGER NOT NULL DEFAULT 0,
                        manual_override_until REAL NOT NULL DEFAULT 0,
                        manual_override_mode TEXT NOT NULL DEFAULT '',
                        manual_override_policy TEXT NOT NULL DEFAULT '2h',
                        baseline_json TEXT NOT NULL DEFAULT '{}',
                        current_limits_json TEXT NOT NULL DEFAULT '{}',
                        dirty_flag INTEGER NOT NULL DEFAULT 0,
                        cooldown_until REAL NOT NULL DEFAULT 0,
                        last_action_ts REAL NOT NULL DEFAULT 0,
                        last_reason TEXT NOT NULL DEFAULT 'Выключен'
                    );
                    CREATE TABLE IF NOT EXISTS tuner_profiles (
                        mode TEXT PRIMARY KEY,
                        profile_json TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS tuner_switch_rules (
                        id INTEGER PRIMARY KEY CHECK(id = 1),
                        rules_json TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS tuner_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts REAL NOT NULL,
                        mode TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        disk_busy REAL NOT NULL DEFAULT 0,
                        cpu_ext REAL NOT NULL DEFAULT 0,
                        ram_free REAL NOT NULL DEFAULT 0,
                        net_pct REAL NOT NULL DEFAULT 0,
                        old_slots INTEGER NOT NULL DEFAULT 0,
                        new_slots INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE INDEX IF NOT EXISTS idx_tuner_hist_ts ON tuner_history(ts DESC);
                """)
                conn.execute("INSERT OR IGNORE INTO tuner_state (id) VALUES (1)")
                now = time.time()
                for m, prof in DEFAULT_PROFILES.items():
                    conn.execute(
                        "INSERT OR IGNORE INTO tuner_profiles (mode, profile_json, updated_at) VALUES (?, ?, ?)",
                        (m, json.dumps(prof, ensure_ascii=False), now)
                    )
                conn.execute(
                    "INSERT OR IGNORE INTO tuner_switch_rules (id, rules_json, updated_at) VALUES (1, ?, ?)",
                    (json.dumps(DEFAULT_SWITCH_RULES, ensure_ascii=False), now)
                )
        except Exception as e:
            write_error_log("ensure_tuner_tables", e)


ensure_tuner_tables()


def get_tuner_state():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                row = conn.execute("SELECT * FROM tuner_state WHERE id = 1").fetchone()
                if row:
                    d = dict(row)
                    d['baseline'] = json.loads(d.get('baseline_json') or '{}')
                    d['current_limits'] = json.loads(d.get('current_limits_json') or '{}')
                    return d
        except Exception as e:
            write_error_log("get_tuner_state", e)
    return {'id': 1, 'mode': 'off', 'auto_switch_enabled': 0, 'dirty_flag': 0, 'baseline': {}, 'current_limits': {}, 'last_reason': 'Выключен'}


def update_tuner_state(**fields):
    allowed = {
        'mode', 'auto_switch_enabled', 'manual_override_until', 'manual_override_mode',
        'manual_override_policy', 'baseline_json', 'current_limits_json', 'dirty_flag',
        'cooldown_until', 'last_action_ts', 'last_reason'
    }
    upd = {k: v for k, v in fields.items() if k in allowed}
    if not upd:
        return
    with app_state_db._lock:
        try:
            clause = ", ".join(f"{k} = ?" for k in upd)
            with app_state_db._get_conn() as conn:
                conn.execute(f"UPDATE tuner_state SET {clause} WHERE id = 1", list(upd.values()))
        except Exception as e:
            write_error_log("update_tuner_state", e)


def get_tuner_profiles():
    res = deepcopy(DEFAULT_PROFILES)
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                for r in conn.execute("SELECT mode, profile_json FROM tuner_profiles").fetchall():
                    if r['mode'] in res:
                        res[r['mode']] = _merge_dict(res[r['mode']], json.loads(r['profile_json'] or '{}'))
        except Exception:
            pass
    return res


def save_tuner_profile(mode, profile_dict):
    if mode not in DEFAULT_PROFILES:
        return None
    merged = _merge_dict(DEFAULT_PROFILES[mode], profile_dict)
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO tuner_profiles (mode, profile_json, updated_at) VALUES (?, ?, ?)",
                    (mode, json.dumps(merged, ensure_ascii=False), time.time())
                )
        except Exception as e:
            write_error_log("save_tuner_profile", e)
    return merged


def reset_tuner_profile(mode):
    if mode not in DEFAULT_PROFILES:
        return None
    return save_tuner_profile(mode, DEFAULT_PROFILES[mode])


def get_switch_rules():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                row = conn.execute("SELECT rules_json FROM tuner_switch_rules WHERE id = 1").fetchone()
                if row:
                    return _merge_dict(DEFAULT_SWITCH_RULES, json.loads(row['rules_json'] or '{}'))
        except Exception:
            pass
    return deepcopy(DEFAULT_SWITCH_RULES)


def save_switch_rules(rules_dict):
    merged = _merge_dict(DEFAULT_SWITCH_RULES, rules_dict)
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO tuner_switch_rules (id, rules_json, updated_at) VALUES (1, ?, ?)",
                    (json.dumps(merged, ensure_ascii=False), time.time())
                )
        except Exception as e:
            write_error_log("save_switch_rules", e)
    return merged


def add_tuner_history(mode, event_type, reason, metrics, old_slots, new_slots):
    now = time.time()
    cutoff = now - (48 * 3600)
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute(
                    """INSERT INTO tuner_history
                       (ts, mode, event_type, reason, disk_busy, cpu_ext, ram_free, net_pct, old_slots, new_slots)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        now, str(mode), str(event_type), str(reason)[:220],
                        round(float(metrics.get('disk_busy', 0)), 1),
                        round(float(metrics.get('cpu_ext', 0)), 1),
                        round(float(metrics.get('ram_free', 0)), 1),
                        round(float(metrics.get('channel_pct', 0)), 1),
                        int(old_slots or 0), int(new_slots or 0)
                    )
                )
                conn.execute("DELETE FROM tuner_history WHERE ts < ?", (cutoff,))
        except Exception as e:
            write_error_log("add_tuner_history", e)


def get_tuner_history(limit=30):
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = conn.execute("SELECT * FROM tuner_history ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []
```

---

#### `core/tuner_engine.py`
```python
# core/tuner_engine.py
import json
import time
import threading
from utils.config import cfg
from utils.helpers import write_log, write_error_log
from core.qb_api import (
    detect_qbittorrent_port, check_qb_api_alive, get_live_torrent_info,
    get_transfer_info, get_qb_preferences, set_qb_preferences
)
from core.tuner_db import (
    ALLOWED_PREFS_KEYS, get_tuner_state, update_tuner_state,
    get_tuner_profiles, get_switch_rules, add_tuner_history
)
from core.tuner_telemetry import telemetry_collector
from core.tuner_switcher import auto_switch_engine


def _pct_to_bps(pct, max_chan_bps):
    p = max(0, int(pct or 0))
    if p <= 0 or p >= 100:
        return 0
    return max(1024, int(max_chan_bps * (p / 100.0)))


def _compute_derived_limits(max_up, prof, max_chan_bps, squeezed=False, act_up_val=None, baseline=None):
    mu = max(int(prof.get('max_uploads_min', 8)), min(int(prof.get('max_uploads_max', 150)), int(max_up)))
    if prof.get('per_torrent_up_auto', True):
        pt_up = max(int(prof.get('per_torrent_up_min', 3)), min(int(prof.get('per_torrent_up_max', 40)), int(round(mu * 0.28))))
    else:
        pt_up = int(prof.get('per_torrent_up_max', 15))

    if prof.get('max_connec_auto', True):
        mc = max(int(prof.get('max_connec_min', 40)), min(int(prof.get('max_connec_max', 600)), mu * 4))
    else:
        mc = int(prof.get('max_connec_max', 200))

    pt_con = max(int(prof.get('per_torrent_connec_min', 10)), min(int(prof.get('per_torrent_connec_max', 150)), int(round(mc * 0.22))))

    if squeezed and prof.get('squeeze_enabled'):
        up_lim = _pct_to_bps(prof.get('squeeze_up_pct', 40), max_chan_bps)
        dl_lim = _pct_to_bps(prof.get('squeeze_dl_pct', 40), max_chan_bps)
    else:
        up_lim = _pct_to_bps(prof.get('up_limit_pct', 0), max_chan_bps)
        dl_lim = _pct_to_bps(prof.get('dl_limit_pct', 0), max_chan_bps)

    res = {
        'max_uploads': mu,
        'max_uploads_per_torrent': pt_up,
        'max_connec': mc,
        'max_connec_per_torrent': pt_con,
        'up_limit': up_lim,
        'dl_limit': dl_lim,
    }
    act_mode = prof.get('active_uploads_mode', 'keep')
    if act_mode == 'fixed':
        res['max_active_uploads'] = int(prof.get('active_uploads_min', 10))
    elif act_mode == 'range':
        if act_up_val is not None:
            res['max_active_uploads'] = max(int(prof.get('active_uploads_min', 4)), min(int(prof.get('active_uploads_max', 20)), int(act_up_val)))
        else:
            res['max_active_uploads'] = int(prof.get('active_uploads_max', 15))
    elif baseline and 'max_active_uploads' in baseline:
        res['max_active_uploads'] = int(baseline['max_active_uploads'])
    return res


def _evaluate_guards(prof, tel):
    g = prof.get('guards') or {}
    warn, crit, green = [], False, True

    d = g.get('disk') or {}
    if d.get('enabled'):
        if tel['disk_busy'] >= float(d.get('warn', 80)):
            warn.append(f"Диск {tel['disk_busy']}%")
        if tel['disk_busy'] >= float(d.get('crit', 95)):
            crit = True
        if tel['disk_busy'] > float(d.get('recover', 50)):
            green = False

    c = g.get('cpu') or {}
    if c.get('enabled'):
        if tel['cpu_ext'] >= float(c.get('warn', 70)):
            warn.append(f"Чужой CPU {tel['cpu_ext']}%")
        if tel['cpu_ext'] >= 95.0:
            crit = True
        if tel['cpu_ext'] > float(c.get('recover', 45)):
            green = False

    r = g.get('ram') or {}
    if r.get('enabled'):
        if tel['ram_free'] < float(r.get('min_free', 15)):
            warn.append(f"RAM своб. {tel['ram_free']}%")
        if tel['ram_free'] < max(5.0, float(r.get('min_free', 15)) * 0.5):
            crit = True
        if tel['ram_free'] < float(r.get('recover_free', 25)):
            green = False

    n = g.get('net') or {}
    if n.get('enabled'):
        if tel['net_ext_pct'] >= float(n.get('warn_pct', 30)):
            warn.append(f"Чужая сеть {tel['net_ext_pct']}%")
        if tel['net_ext_pct'] > float(n.get('recover_pct', 15)):
            green = False

    return warn, crit, green


class AdaptiveTunerEngine:
    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._warn_streak = 0
        self._last_step_down_ts = 0.0
        self._last_step_up_ts = 0.0
        self._last_telemetry = {}
        self._last_switch_reason = ''

    def get_live_snapshot(self):
        st = get_tuner_state()
        return {
            'state': st,
            'telemetry': dict(self._last_telemetry),
            'switch_reason': self._last_switch_reason
        }

    def _capture_baseline_if_needed(self, ip, port, st):
        if st.get('dirty_flag') and st.get('baseline'):
            return st['baseline']
        prefs = get_qb_preferences(ip, port)
        if not prefs:
            return None
        base = {k: int(prefs[k]) for k in ALLOWED_PREFS_KEYS if k in prefs and prefs[k] is not None}
        update_tuner_state(baseline_json=json.dumps(base), dirty_flag=1)
        return base

    def restore_baseline(self, reason='Возврат эталона'):
        st = get_tuner_state()
        base = st.get('baseline') or {}
        if not st.get('dirty_flag') or not base:
            update_tuner_state(mode='off', dirty_flag=0, last_reason=reason, current_limits_json='{}')
            return True, 'Эталон не требовал отката'

        ip, port = detect_qbittorrent_port(cfg.config)
        if port and check_qb_api_alive(ip, port):
            if set_qb_preferences(ip, port, base):
                update_tuner_state(mode='off', dirty_flag=0, last_reason=reason, current_limits_json=json.dumps(base))
                add_tuner_history('off', 'restore', reason, self._last_telemetry, st.get('current_limits', {}).get('max_uploads', 0), base.get('max_uploads', 0))
                write_log('automation', f"Авто-тюнер: {reason}")
                return True, 'Эталонные настройки qB восстановлены'
        return False, 'qBittorrent недоступен для отката эталона'

    def set_mode(self, new_mode, auto_switch=None, is_manual=True, override_policy=None, clear_override=False):
        with self._lock:
            st = get_tuner_state()
            upd = {}
            if auto_switch is not None:
                upd['auto_switch_enabled'] = 1 if auto_switch else 0
            if clear_override:
                upd['manual_override_until'] = 0
                upd['manual_override_mode'] = ''

            if new_mode == 'off':
                upd['mode'] = 'off'
                upd['manual_override_until'] = 0
                upd['manual_override_mode'] = ''
                update_tuner_state(**upd)
                ok, msg = self.restore_baseline('Выключен пользователем')
                return ok, msg

            if new_mode not in ('performance', 'comfort'):
                return False, 'Некорректный режим'

            if is_manual and (upd.get('auto_switch_enabled', st.get('auto_switch_enabled'))):
                pol = override_policy or st.get('manual_override_policy') or '2h'
                upd['manual_override_policy'] = pol
                upd['manual_override_mode'] = new_mode
                upd['manual_override_until'] = (time.time() + 7200) if pol == '2h' else 0

            upd['mode'] = new_mode
            upd['last_reason'] = f"Переключён в режим «{new_mode}»"
            update_tuner_state(**upd)
            self._warn_streak = 0
            return True, f"Режим тюнера: {new_mode}"

    def _apply_if_changed(self, ip, port, cur_limits, new_limits, mode, ev_type, reason):
        diff = {k: v for k, v in new_limits.items() if cur_limits.get(k) != v}
        if not diff:
            return False
        if set_qb_preferences(ip, port, new_limits):
            old_slots = cur_limits.get('max_uploads', 0)
            new_slots = new_limits.get('max_uploads', 0)
            update_tuner_state(current_limits_json=json.dumps(new_limits), last_action_ts=time.time(), last_reason=reason)
            add_tuner_history(mode, ev_type, reason, self._last_telemetry, old_slots, new_slots)
            write_log('automation', f"Авто-тюнер [{mode}] {ev_type}: {reason} (слоты {old_slots}->{new_slots})")
            return True
        return False

    def _tick(self):
        ip, port = detect_qbittorrent_port(cfg.config)
        qb_up = check_qb_api_alive(ip, port) if port else False
        live = get_live_torrent_info(ip, port) if qb_up else {}
        tr = get_transfer_info(ip, port) if qb_up else {}
        st = get_tuner_state()
        profiles = get_tuner_profiles()
        mode = st.get('mode')
        prof = profiles.get(mode) or profiles.get('performance', {})

        target_disk = prof.get('guards', {}).get('disk', {}).get('target_disk', '')
        cur_slots = int((st.get('current_limits') or {}).get('max_uploads') or (st.get('baseline') or {}).get('max_uploads') or 20)
        tel = telemetry_collector.collect(live, tr, cur_slots, target_disk=target_disk)
        self._last_telemetry = tel

        if not qb_up:
            return

        if st.get('mode') == 'off':
            if st.get('dirty_flag'):
                self.restore_baseline('Аварийное восстановление эталона (dirty_flag=1)')
            return

        if time.time() < cfg.getint('Panic_Active_Until', 0):
            update_tuner_state(last_reason='Пауза: активен Panic Killswitch')
            return

        base = self._capture_baseline_if_needed(ip, port, st)
        if base is None:
            return

        if st.get('auto_switch_enabled'):
            rules = get_switch_rules()
            sw_mode, sw_reason, _ = auto_switch_engine.evaluate(st, rules, tel)
            self._last_switch_reason = sw_reason
            if sw_mode in ('performance', 'comfort') and sw_mode != mode:
                mode = sw_mode
                prof = profiles.get(mode, prof)
                update_tuner_state(mode=mode, last_reason=sw_reason)
                add_tuner_history(mode, 'auto_switch', sw_reason, tel, cur_slots, cur_slots)
        else:
            self._last_switch_reason = ''

        if prof.get('yield_to_turtle', True) and tr.get('use_alt_speed_limits'):
            update_tuner_state(last_reason='Уступает ручной «Черепахе»')
            return

        cur_limits = st.get('current_limits') or {}
        if not cur_limits:
            init_lim = _compute_derived_limits(prof.get('max_uploads_start', 25), prof, tel['max_channel_bps'], baseline=base)
            self._apply_if_changed(ip, port, {}, init_lim, mode, 'hold', f"Старт режима {mode}")
            return

        now = time.time()
        warn_list, is_crit, all_green = _evaluate_guards(prof, tel)
        self._warn_streak = (self._warn_streak + 1) if warn_list else 0

        # Шаг ВНИЗ (раз в 20-30 сек при 2 замерах тревоги подряд)
        if self._warn_streak >= 2 and (now - self._last_step_down_ts) >= 20.0:
            self._last_step_down_ts = now
            old_mu = int(cur_limits.get('max_uploads', prof.get('max_uploads_start', 20)))
            step_d = max(5, int(round(old_mu * 0.2)))
            new_mu = max(int(prof.get('max_uploads_min', 8)), old_mu - step_d)
            act_up = cur_limits.get('max_active_uploads')
            if is_crit and prof.get('active_uploads_mode') == 'range' and act_up is not None:
                act_up = max(int(prof.get('active_uploads_min', 4)), int(act_up) - 2)
            new_lim = _compute_derived_limits(new_mu, prof, tel['max_channel_bps'], squeezed=True, act_up_val=act_up, baseline=base)
            cd = max(30, int(prof.get('cooldown_sec', 180)))
            update_tuner_state(cooldown_until=now + cd)
            self._apply_if_changed(ip, port, cur_limits, new_lim, mode, 'step_down', f"Защита: {', '.join(warn_list)}")
            return

        # Шаг ВВЕРХ (раз в 90-120 сек)
        if (now - self._last_step_up_ts) >= 90.0 and now >= float(st.get('cooldown_until') or 0):
            if all_green and tel['channel_pct'] < float(prof.get('channel_target_min', 85)) and tel['slots_fill_pct'] >= 75.0:
                self._last_step_up_ts = now
                old_mu = int(cur_limits.get('max_uploads', prof.get('max_uploads_start', 20)))
                step_u = max(1, int(prof.get('step_up_size', 5)))
                new_mu = min(int(prof.get('max_uploads_max', 150)), old_mu + step_u)
                act_up = cur_limits.get('max_active_uploads')
                if prof.get('active_uploads_mode') == 'range' and act_up is not None:
                    act_up = min(int(prof.get('active_uploads_max', 15)), int(act_up) + 1)
                new_lim = _compute_derived_limits(new_mu, prof, tel['max_channel_bps'], squeezed=False, act_up_val=act_up, baseline=base)
                self._apply_if_changed(ip, port, cur_limits, new_lim, mode, 'step_up', f"Разгон (канал {tel['channel_pct']}%, слоты {tel['slots_fill_pct']}%)")

    def start(self):
        if self._running:
            return
        self._running = True

        def loop():
            time.sleep(3)
            st = get_tuner_state()
            if st.get('dirty_flag') and st.get('mode') == 'off':
                self.restore_baseline('Восстановление эталона при старте tbr')
            while self._running:
                try:
                    self._tick()
                except Exception as e:
                    write_error_log("AdaptiveTunerEngine tick", e)
                for _ in range(10):
                    if not self._running:
                        return
                    time.sleep(1)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop_and_restore(self):
        self._running = False
        st = get_tuner_state()
        if st.get('dirty_flag'):
            self.restore_baseline('Штатный откат при выходе tbr')


tuner_engine = AdaptiveTunerEngine()
```

---

#### `web/routes/tuner_bp.py`
```python
# web/routes/tuner_bp.py
import datetime
from flask import Blueprint, request, jsonify, g
from utils.config import cfg
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info
from core.disk_monitor import list_active_disks
from core.tuner_db import (
    get_tuner_profiles, save_tuner_profile, reset_tuner_profile,
    get_switch_rules, save_switch_rules, get_tuner_history
)
from core.tuner_telemetry import list_running_processes
from core.tuner_engine import tuner_engine

tuner_bp = Blueprint('tuner_bp', __name__)


def _not_admin():
    return g.get('role') != 'admin'


@tuner_bp.route('/api/tuner/state')
def api_tuner_state():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    snap = tuner_engine.get_live_snapshot()
    hist = get_tuner_history(limit=30)
    for h in hist:
        h['time'] = datetime.datetime.fromtimestamp(h['ts']).strftime('%H:%M:%S')
    snap['history'] = hist
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    snap['available_disks'] = list_active_disks(live)
    return jsonify(snap)


@tuner_bp.route('/api/tuner/mode', methods=['POST'])
def api_tuner_mode():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    d = request.get_json(silent=True) or {}
    mode = str(d.get('mode', 'off')).strip()
    auto_sw = d.get('auto_switch')
    clear_ov = bool(d.get('clear_override', False))
    ov_pol = d.get('override_policy')
    is_manual = bool(d.get('is_manual', True))
    ok, msg = tuner_engine.set_mode(
        mode, auto_switch=auto_sw, is_manual=is_manual,
        override_policy=ov_pol, clear_override=clear_ov
    )
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@tuner_bp.route('/api/tuner/restore_baseline', methods=['POST'])
def api_tuner_restore_baseline():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    ok, msg = tuner_engine.restore_baseline('Ручной возврат эталона')
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@tuner_bp.route('/api/tuner/profiles', methods=['GET', 'POST'])
def api_tuner_profiles():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    if request.method == 'GET':
        return jsonify({'profiles': get_tuner_profiles()})
    d = request.get_json(silent=True) or {}
    reset_mode = d.get('reset_mode')
    if reset_mode in ('performance', 'comfort'):
        prof = reset_tuner_profile(reset_mode)
        return jsonify({'success': True, 'profile': prof})
    mode = d.get('mode')
    profile_data = d.get('profile')
    if mode not in ('performance', 'comfort') or not isinstance(profile_data, dict):
        return jsonify({'success': False, 'error': 'Некорректные данные профиля'}), 400
    saved = save_tuner_profile(mode, profile_data)
    return jsonify({'success': True, 'profile': saved})


@tuner_bp.route('/api/tuner/rules', methods=['GET', 'POST'])
def api_tuner_rules():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    if request.method == 'GET':
        return jsonify({'rules': get_switch_rules()})
    d = request.get_json(silent=True) or {}
    saved = save_switch_rules(d.get('rules') if isinstance(d.get('rules'), dict) else d)
    return jsonify({'success': True, 'rules': saved})


@tuner_bp.route('/api/tuner/processes')
def api_tuner_processes():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    return jsonify({'processes': list_running_processes()})
```

---

#### `web/templates/partials/tab_tuner.html`
```html
<!-- Адаптивный авто-тюнер qBittorrent (ТЗ #58) -->
<div class="card admin-only" id="tuner-main-card">
    <div class="row-between mb-8">
        <div class="row-gap" style="flex-wrap:wrap;">
            <div class="card-title" style="margin:0; white-space:nowrap;">🎛️ АВТО-ТЮНЕР qB</div>
            <span id="tuner-reason-badge" class="badge badge-pause">Выключен</span>
            <button id="tuner-btn-clear-ov" class="btn btn-secondary btn-xs hidden" onclick="clearTunerOverride()">🔄 Вернуть авто</button>
        </div>
        <div class="row-gap" style="flex-wrap:wrap;">
            <button id="tuner-btn-off" class="btn btn-secondary btn-xs" onclick="setTunerMode('off')">Выкл</button>
            <button id="tuner-btn-comfort" class="btn btn-secondary btn-xs" onclick="setTunerMode('comfort')">🛋️ Комфорт</button>
            <button id="tuner-btn-performance" class="btn btn-secondary btn-xs" onclick="setTunerMode('performance')">🚀 Производ.</button>
            <label class="row-gap pointer lbl-xs" style="margin-left:4px; white-space:nowrap;"><input type="checkbox" id="tuner-auto-chk" onchange="toggleTunerAutoSwitch()"> <b>Авто</b></label>
            <button class="btn btn-secondary btn-xs" onclick="restoreTunerBaseline()" title="Откатить настройки qB к исходному эталону">♻️ Эталон</button>
        </div>
    </div>

    <!-- Метрики в реальном времени -->
    <div class="tuner-telemetry-grid mb-10">
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap" id="tel-disk-title">Диск I/O</div><div id="tel-disk" class="val-sm">—</div></div>
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap">Чужой CPU</div><div id="tel-cpu" class="val-sm">—</div></div>
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap">RAM своб.</div><div id="tel-ram" class="val-sm">—</div></div>
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap">Канал qB</div><div id="tel-chan" class="val-sm accent-txt">—</div></div>
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap">Чужая сеть</div><div id="tel-net" class="val-sm">—</div></div>
        <div class="tuner-stat-card"><div class="lbl-xs muted-text no-wrap">Слоты / Заполн.</div><div id="tel-slots" class="val-sm blue-txt">—</div></div>
    </div>

    <!-- Лента решений -->
    <div class="scroll-box mb-12" style="max-height:140px; border:1px solid var(--border); border-radius:6px;">
        <table>
            <thead><tr><th>Время</th><th>Режим</th><th>Событие</th><th>Причина</th><th>Слоты</th></tr></thead>
            <tbody id="tuner-history-tbody"><tr><td colspan="5" class="center-msg">Нет событий</td></tr></tbody>
        </table>
    </div>

    <div class="tuner-columns-grid">
        <!-- Левая колонка: Профили -->
        <div class="tuner-box">
            <div class="row-between mb-8">
                <div class="row-gap">
                    <button id="tp-tab-performance" class="btn btn-xs" onclick="selectTunerProfileTab('performance')">🚀 Производительность</button>
                    <button id="tp-tab-comfort" class="btn btn-secondary btn-xs" onclick="selectTunerProfileTab('comfort')">🛋️ Комфорт</button>
                </div>
                <div class="row-gap">
                    <button class="btn btn-secondary btn-xs" onclick="resetTunerProfile()" title="Сбросить профиль к заводским">Сброс</button>
                    <button class="btn btn-xs" onclick="saveTunerProfile()">💾 Сохранить</button>
                </div>
            </div>

            <!-- Главные параметры слотов -->
            <div class="tuner-section-title">СЛОТЫ ОТДАЧИ (MAX_UPLOADS)</div>
            <div class="tuner-fields-row mb-8">
                <div class="tuner-field"><span class="lbl-micro">Мин. слотов</span><input id="tp-mu-min" type="number" class="form-control tuner-num-input"></div>
                <div class="tuner-field"><span class="lbl-micro">Макс. слотов</span><input id="tp-mu-max" type="number" class="form-control tuner-num-input"></div>
                <div class="tuner-field"><span class="lbl-micro">Стартовые</span><input id="tp-mu-start" type="number" class="form-control tuner-num-input"></div>
            </div>

            <div class="tuner-fields-row mb-8">
                <div class="tuner-field grow-1">
                    <span class="lbl-micro">max_active_uploads</span>
                    <select id="tp-act-mode" class="form-control" onchange="syncTunerDisabledStates()">
                        <option value="keep">Не менять (эталон)</option>
                        <option value="range">Диапазон Min..Max</option>
                        <option value="fixed">Фиксированное число</option>
                    </select>
                </div>
                <div class="tuner-field" id="wrap-tp-act-min"><span class="lbl-micro">Min</span><input id="tp-act-min" type="number" class="form-control tuner-num-input"></div>
                <div class="tuner-field" id="wrap-tp-act-max"><span class="lbl-micro">Max</span><input id="tp-act-max" type="number" class="form-control tuner-num-input"></div>
            </div>

            <!-- Скорость и канал -->
            <div class="tuner-section-title">ЦЕЛЬ КАНАЛА И СКОРОСТИ</div>
            <div class="tuner-fields-row mb-8">
                <div class="tuner-field"><span class="lbl-micro">Цель канала (От %)</span><input id="tp-ch-min" type="number" class="form-control tuner-num-input"></div>
                <div class="tuner-field"><span class="lbl-micro">Цель канала (До %)</span><input id="tp-ch-max" type="number" class="form-control tuner-num-input"></div>
                <div class="tuner-field"><span class="lbl-micro">Потолок Up (0=∞)</span><input id="tp-up-pct" type="number" class="form-control tuner-num-input"></div>
                <div class="tuner-field"><span class="lbl-micro">Потолок DL (0=∞)</span><input id="tp-dl-pct" type="number" class="form-control tuner-num-input"></div>
            </div>

            <div class="tuner-fields-row mb-8 align-end">
                <label class="row-gap pointer lbl-xs no-wrap grow-1" style="padding-bottom:5px;">
                    <input id="tp-sq-en" type="checkbox" onchange="syncTunerDisabledStates()"> <b>Ужимать при перегрузе</b>
                </label>
                <div class="tuner-field" id="wrap-tp-sq-up"><span class="lbl-micro">Сжать Up %</span><input id="tp-sq-up" type="number" class="form-control tuner-num-input"></div>
                <div class="tuner-field" id="wrap-tp-sq-dl"><span class="lbl-micro">Сжать DL %</span><input id="tp-sq-dl" type="number" class="form-control tuner-num-input"></div>
            </div>

            <!-- Ограничители железа -->
            <div class="tuner-section-title">ОГРАНИЧИТЕЛИ ЖЕЛЕЗА И СЕТИ</div>
            <div class="tuner-guards-list mb-8">
                <!-- Диск -->
                <div class="tuner-guard-row" id="guard-row-disk">
                    <label class="row-gap pointer lbl-xs tuner-guard-label no-wrap"><input id="tp-g-disk-en" type="checkbox" onchange="syncTunerDisabledStates()"> <span>Диск I/O</span></label>
                    <div class="tuner-field" style="flex: 1.5 1 125px; min-width: 110px;">
                        <span class="lbl-micro">Целевой диск</span>
                        <select id="tp-g-disk-target" class="form-control" style="padding:4px 6px; font-size:11px;" onchange="syncTunerDisabledStates()"></select>
                    </div>
                    <div class="tuner-field"><span class="lbl-micro">Тревога %</span><input id="tp-g-disk-warn" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Крит. %</span><input id="tp-g-disk-crit" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Возврат %</span><input id="tp-g-disk-rec" type="number" class="form-control tuner-num-input"></div>
                </div>

                <!-- CPU -->
                <div class="tuner-guard-row" id="guard-row-cpu">
                    <label class="row-gap pointer lbl-xs tuner-guard-label no-wrap"><input id="tp-g-cpu-en" type="checkbox" onchange="syncTunerDisabledStates()"> <span>Чужой CPU</span></label>
                    <div class="tuner-field"><span class="lbl-micro">Тревога %</span><input id="tp-g-cpu-warn" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Возврат %</span><input id="tp-g-cpu-rec" type="number" class="form-control tuner-num-input"></div>
                </div>

                <!-- RAM -->
                <div class="tuner-guard-row" id="guard-row-ram">
                    <label class="row-gap pointer lbl-xs tuner-guard-label no-wrap"><input id="tp-g-ram-en" type="checkbox" onchange="syncTunerDisabledStates()"> <span>Своб. RAM</span></label>
                    <div class="tuner-field"><span class="lbl-micro">Мин. % (тревога)</span><input id="tp-g-ram-min" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Возврат %</span><input id="tp-g-ram-rec" type="number" class="form-control tuner-num-input"></div>
                </div>

                <!-- Сеть -->
                <div class="tuner-guard-row" id="guard-row-net">
                    <label class="row-gap pointer lbl-xs tuner-guard-label no-wrap"><input id="tp-g-net-en" type="checkbox" onchange="syncTunerDisabledStates()"> <span>Чужая сеть</span></label>
                    <div class="tuner-field"><span class="lbl-micro">Тревога %</span><input id="tp-g-net-warn" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Возврат %</span><input id="tp-g-net-rec" type="number" class="form-control tuner-num-input"></div>
                </div>
            </div>

            <!-- Аккордеон: Тонкие настройки -->
            <details class="tuner-details">
                <summary>⚙️ Тонкие настройки слотов и задержек</summary>
                <div class="tuner-details-body">
                    <div class="tuner-fields-row mb-8 align-end">
                        <div class="tuner-field"><span class="lbl-micro">На торрент (Min)</span><input id="tp-pt-up-min" type="number" class="form-control tuner-num-input"></div>
                        <div class="tuner-field"><span class="lbl-micro">На торрент (Max)</span><input id="tp-pt-up-max" type="number" class="form-control tuner-num-input"></div>
                        <label class="row-gap pointer lbl-xs no-wrap" style="padding-bottom:5px;"><input id="tp-pt-up-auto" type="checkbox" onchange="syncTunerDisabledStates()"> Авто 28%</label>
                    </div>

                    <div class="tuner-fields-row mb-8 align-end">
                        <div class="tuner-field"><span class="lbl-micro">Соединений (Min)</span><input id="tp-mc-min" type="number" class="form-control tuner-num-input"></div>
                        <div class="tuner-field"><span class="lbl-micro">Соединений (Max)</span><input id="tp-mc-max" type="number" class="form-control tuner-num-input"></div>
                        <label class="row-gap pointer lbl-xs no-wrap" style="padding-bottom:5px;"><input id="tp-mc-auto" type="checkbox" onchange="syncTunerDisabledStates()"> Авто ×4</label>
                    </div>

                    <div class="tuner-fields-row mb-8">
                        <div class="tuner-field"><span class="lbl-micro">Connec/торр. (Min)</span><input id="tp-pt-con-min" type="number" class="form-control tuner-num-input"></div>
                        <div class="tuner-field"><span class="lbl-micro">Connec/торр. (Max)</span><input id="tp-pt-con-max" type="number" class="form-control tuner-num-input"></div>
                        <div class="tuner-field"><span class="lbl-micro">Кулдаун (сек)</span><input id="tp-cd-sec" type="number" class="form-control tuner-num-input"></div>
                        <div class="tuner-field"><span class="lbl-micro">Шаг разгона (+слоты)</span><input id="tp-step-up" type="number" class="form-control tuner-num-input"></div>
                    </div>

                    <label class="row-gap pointer lbl-xs no-wrap">
                        <input id="tp-yield-turtle" type="checkbox"> Уступать ручной «Черепахе» в клиенте
                    </label>
                </div>
            </details>
        </div>

        <!-- Правая колонка: Правила автопереключения -->
        <div class="tuner-box">
            <div class="row-between mb-8">
                <span class="lbl-sm" style="margin:0; font-weight:700;">🧠 ПРАВИЛА АВТОПЕРЕКЛЮЧЕНИЯ</span>
                <button class="btn btn-xs" onclick="saveTunerRules()">💾 Сохранить</button>
            </div>

            <div class="tuner-fields-row mb-8">
                <div class="tuner-field grow-1">
                    <span class="lbl-micro">Режим по умолчанию</span>
                    <select id="tr-def-mode" class="form-control">
                        <option value="performance">Производительность</option>
                        <option value="comfort">Комфорт</option>
                    </select>
                </div>
                <div class="tuner-field grow-1">
                    <span class="lbl-micro">Политика Manual Override</span>
                    <select id="tr-ov-policy" class="form-control">
                        <option value="2h">На 2 часа</option>
                        <option value="until_schedule">До смены расписания</option>
                        <option value="until_process_exit">До закрытия процесса</option>
                    </select>
                </div>
            </div>

            <!-- Расписание -->
            <div class="tuner-block-divider mb-8">
                <div class="row-between mb-6">
                    <span class="lbl-xs"><b>⏰ Расписание (с переходом через полночь)</b></span>
                    <button class="btn btn-secondary btn-xs" onclick="addTunerScheduleRow()">+ Окно</button>
                </div>
                <div id="tr-sched-list" class="col-gap" style="max-height:110px; overflow-y:auto;"></div>
            </div>

            <!-- Процессы (Watchlist) -->
            <div class="tuner-block-divider mb-8" id="rules-box-proc">
                <div class="row-between mb-6">
                    <label class="row-gap pointer lbl-xs no-wrap"><input id="tr-proc-en" type="checkbox" onchange="syncTunerDisabledStates()"> <b>🎮 Процессы (Watchlist)</b></label>
                    <div class="row-gap">
                        <select id="tr-proc-mode" class="form-control" style="padding:2px 4px; font-size:11px;">
                            <option value="comfort">→ Комфорт</option>
                            <option value="performance">→ Производ.</option>
                        </select>
                        <button class="btn btn-secondary btn-xs" onclick="loadRunningProcessesPicker()">🖥️ Процессы ПК</button>
                    </div>
                </div>
                <input id="tr-proc-names" class="form-control mb-6" placeholder="cs2.exe, dota2.exe, obs64.exe">
                <div id="tr-proc-picker" class="hidden row-wrap mb-6" style="max-height:85px; overflow-y:auto; gap:4px;"></div>
                <div class="tuner-fields-row">
                    <div class="tuner-field"><span class="lbl-micro">Задержка входа (сек)</span><input id="tr-proc-enter" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Задержка выхода (сек)</span><input id="tr-proc-exit" type="number" class="form-control tuner-num-input"></div>
                </div>
            </div>

            <!-- Внешняя нагрузка -->
            <div class="tuner-block-divider" id="rules-box-ext">
                <div class="row-between mb-6">
                    <label class="row-gap pointer lbl-xs no-wrap"><input id="tr-ext-en" type="checkbox" onchange="syncTunerDisabledStates()"> <b>⚡ Активность чужих программ</b></label>
                    <select id="tr-ext-mode" class="form-control" style="width:115px; padding:2px 4px; font-size:11px;">
                        <option value="comfort">→ Комфорт</option>
                        <option value="performance">→ Производ.</option>
                    </select>
                </div>
                <div class="tuner-fields-row mb-6">
                    <div class="tuner-field"><span class="lbl-micro">CPU Вход %</span><input id="tr-ext-cpu-w" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">CPU Выход %</span><input id="tr-ext-cpu-r" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Сеть Вход %</span><input id="tr-ext-net-w" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Сеть Выход %</span><input id="tr-ext-net-r" type="number" class="form-control tuner-num-input"></div>
                </div>
                <div class="tuner-fields-row mb-6">
                    <div class="tuner-field"><span class="lbl-micro">RAM Мин. %</span><input id="tr-ext-ram-w" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">RAM Возвр. %</span><input id="tr-ext-ram-r" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Вход (сек)</span><input id="tr-ext-enter" type="number" class="form-control tuner-num-input"></div>
                    <div class="tuner-field"><span class="lbl-micro">Выход (сек)</span><input id="tr-ext-exit" type="number" class="form-control tuner-num-input"></div>
                </div>
            </div>
        </div>
    </div>
</div>
```

---

#### `web/static/tuner_ui.js`
```javascript
// web/static/tuner_ui.js
let _tunerProfiles = {};
let _tunerCurProfile = 'performance';
let _tunerRules = {};
let _tunerAvailableDisks = [];

function syncTunerDisabledStates() {
    const setGroupState = (chkId, rowId, inputIds) => {
        const en = Boolean(document.getElementById(chkId)?.checked);
        const row = document.getElementById(rowId);
        if (row) row.classList.toggle('tuner-row-disabled', !en);
        inputIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.disabled = !en;
        });
    };

    setGroupState('tp-g-disk-en', 'guard-row-disk', ['tp-g-disk-target', 'tp-g-disk-warn', 'tp-g-disk-crit', 'tp-g-disk-rec']);
    setGroupState('tp-g-cpu-en', 'guard-row-cpu', ['tp-g-cpu-warn', 'tp-g-cpu-rec']);
    setGroupState('tp-g-ram-en', 'guard-row-ram', ['tp-g-ram-min', 'tp-g-ram-rec']);
    setGroupState('tp-g-net-en', 'guard-row-net', ['tp-g-net-warn', 'tp-g-net-rec']);

    const sqEn = Boolean(document.getElementById('tp-sq-en')?.checked);
    ['tp-sq-up', 'tp-sq-dl'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = !sqEn;
        document.getElementById(`wrap-${id}`)?.classList.toggle('tuner-row-disabled', !sqEn);
    });

    const actMode = document.getElementById('tp-act-mode')?.value || 'keep';
    const minEl = document.getElementById('tp-act-min');
    const maxEl = document.getElementById('tp-act-max');
    if (minEl) minEl.disabled = (actMode === 'keep');
    if (maxEl) maxEl.disabled = (actMode !== 'range');
    document.getElementById('wrap-tp-act-min')?.classList.toggle('tuner-row-disabled', actMode === 'keep');
    document.getElementById('wrap-tp-act-max')?.classList.toggle('tuner-row-disabled', actMode !== 'range');

    const ptUpAuto = Boolean(document.getElementById('tp-pt-up-auto')?.checked);
    ['tp-pt-up-min', 'tp-pt-up-max'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = ptUpAuto;
    });

    const mcAuto = Boolean(document.getElementById('tp-mc-auto')?.checked);
    ['tp-mc-min', 'tp-mc-max'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = mcAuto;
    });

    const prEn = Boolean(document.getElementById('tr-proc-en')?.checked);
    ['tr-proc-mode', 'tr-proc-names', 'tr-proc-enter', 'tr-proc-exit'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = !prEn;
    });
    document.getElementById('rules-box-proc')?.classList.toggle('tuner-row-disabled', !prEn);

    const extEn = Boolean(document.getElementById('tr-ext-en')?.checked);
    ['tr-ext-mode', 'tr-ext-cpu-w', 'tr-ext-cpu-r', 'tr-ext-net-w', 'tr-ext-net-r', 'tr-ext-ram-w', 'tr-ext-ram-r', 'tr-ext-enter', 'tr-ext-exit'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = !extEn;
    });
    document.getElementById('rules-box-ext')?.classList.toggle('tuner-row-disabled', !extEn);
}

function _updateDiskSelectorOptions(selectedVal) {
    const sel = document.getElementById('tp-g-disk-target');
    if (!sel) return;
    sel.innerHTML = '';
    sel.add(new Option('Авто (по раздачам)', ''));
    sel.add(new Option('Все диски (Max)', 'ALL'));
    _tunerAvailableDisks.forEach(d => {
        sel.add(new Option(`${d.path} (${d.free_fmt} своб.)`, d.path));
    });
    sel.value = selectedVal || '';
}

async function loadTunerTab() {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
    await Promise.all([refreshTunerState(), loadTunerProfiles(), loadTunerRules()]);
}

async function refreshTunerState() {
    if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
    try {
        const res = await api('/api/tuner/state');
        if (!res.ok) return;
        const d = await res.json();
        const st = d.state || {}, tel = d.telemetry || {}, mode = st.mode || 'off';
        _tunerAvailableDisks = d.available_disks || [];

        ['off', 'comfort', 'performance'].forEach(m => {
            const b = document.getElementById(`tuner-btn-${m}`);
            if (b) b.className = (m === mode) ? 'btn btn-xs' : 'btn btn-secondary btn-xs';
        });
        const chk = document.getElementById('tuner-auto-chk');
        if (chk) chk.checked = Boolean(st.auto_switch_enabled);

        const reason = d.switch_reason || st.last_reason || 'Выключен';
        const badge = document.getElementById('tuner-reason-badge');
        if (badge) {
            badge.textContent = reason;
            badge.className = mode === 'off' ? 'badge badge-pause' : (mode === 'performance' ? 'badge badge-up' : 'badge badge-dl');
        }
        const hb = document.getElementById('tuner-header-badge');
        if (hb) {
            hb.textContent = mode === 'off' ? '🎛️ Тюнер: Выкл' : (mode === 'performance' ? '🚀 Тюнер: Произв.' : '🛋️ Тюнер: Комф.');
            hb.className = mode === 'off' ? 'badge badge-pause pointer admin-only' : (mode === 'performance' ? 'badge badge-up pointer admin-only' : 'badge badge-dl pointer admin-only');
        }
        document.getElementById('tuner-btn-clear-ov')?.classList.toggle('hidden', !st.manual_override_mode);

        const setTxt = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
        const diskTitle = tel.monitored_disk_label ? `Диск I/O (${tel.monitored_disk_label})` : 'Диск I/O';
        setTxt('tel-disk-title', diskTitle);
        setTxt('tel-disk', tel.psutil_available === false ? 'нет psutil' : `${tel.disk_busy ?? 0}%`);
        setTxt('tel-cpu', `${tel.cpu_ext ?? 0}%`);
        setTxt('tel-ram', `${tel.ram_free ?? 0}%`);
        setTxt('tel-chan', `${tel.channel_pct ?? 0}%`);
        setTxt('tel-net', `${tel.net_ext_pct ?? 0}%`);
        const curMu = (st.current_limits || {}).max_uploads || (st.baseline || {}).max_uploads || '—';
        setTxt('tel-slots', `${curMu} (${tel.slots_fill_pct ?? 0}%)`);

        const tbody = document.getElementById('tuner-history-tbody');
        if (tbody) {
            const hist = d.history || [];
            tbody.innerHTML = hist.length ? hist.map(h => `
                <tr><td>${escapeHtml(h.time)}</td><td>${escapeHtml(h.mode)}</td><td><span class="badge badge-pause">${escapeHtml(h.event_type)}</span></td><td style="white-space:normal;">${escapeHtml(h.reason)}</td><td>${h.old_slots}→${h.new_slots}</td></tr>
            `).join('') : '<tr><td colspan="5" class="center-msg">Нет событий</td></tr>';
        }
    } catch (e) {}
}

async function setTunerMode(mode) {
    const res = await api('/api/tuner/mode', 'POST', { mode, is_manual: true });
    if (!res.ok) return alert((await res.json()).error || 'Ошибка');
    refreshTunerState();
}

async function toggleTunerAutoSwitch() {
    const auto_switch = document.getElementById('tuner-auto-chk')?.checked || false;
    const mode = auto_switch ? (_tunerRules.default_mode || 'performance') : 'off';
    await api('/api/tuner/mode', 'POST', { mode, auto_switch, is_manual: false });
    refreshTunerState();
}

async function clearTunerOverride() {
    await api('/api/tuner/mode', 'POST', { mode: _tunerRules.default_mode || 'performance', clear_override: true, is_manual: false });
    refreshTunerState();
}

async function restoreTunerBaseline() {
    if (!confirm('Выключить тюнер и восстановить эталонные настройки qBittorrent?')) return;
    const res = await api('/api/tuner/restore_baseline', 'POST');
    alert((await res.json()).message || 'Готово');
    refreshTunerState();
}

async function loadTunerProfiles() {
    const res = await api('/api/tuner/profiles');
    if (res.ok) { _tunerProfiles = (await res.json()).profiles || {}; selectTunerProfileTab(_tunerCurProfile); }
}

function selectTunerProfileTab(mode) {
    _tunerCurProfile = mode;
    document.getElementById('tp-tab-performance').className = mode === 'performance' ? 'btn btn-xs' : 'btn btn-secondary btn-xs';
    document.getElementById('tp-tab-comfort').className = mode === 'comfort' ? 'btn btn-xs' : 'btn btn-secondary btn-xs';
    const p = _tunerProfiles[mode] || {}, g = p.guards || {};
    const sv = (id, v) => { const e = document.getElementById(id); if (e) e.value = v ?? ''; };
    const sc = (id, v) => { const e = document.getElementById(id); if (e) e.checked = Boolean(v); };

    sv('tp-mu-min', p.max_uploads_min); sv('tp-mu-max', p.max_uploads_max); sv('tp-mu-start', p.max_uploads_start);
    sv('tp-pt-up-min', p.per_torrent_up_min); sv('tp-pt-up-max', p.per_torrent_up_max); sc('tp-pt-up-auto', p.per_torrent_up_auto);
    sv('tp-mc-min', p.max_connec_min); sv('tp-mc-max', p.max_connec_max); sc('tp-mc-auto', p.max_connec_auto);
    sv('tp-pt-con-min', p.per_torrent_connec_min); sv('tp-pt-con-max', p.per_torrent_connec_max);
    sv('tp-act-mode', p.active_uploads_mode || 'keep'); sv('tp-act-min', p.active_uploads_min); sv('tp-act-max', p.active_uploads_max);
    sv('tp-ch-min', p.channel_target_min); sv('tp-ch-max', p.channel_target_max);
    sv('tp-up-pct', p.up_limit_pct); sv('tp-dl-pct', p.dl_limit_pct);
    sc('tp-sq-en', p.squeeze_enabled); sv('tp-sq-up', p.squeeze_up_pct); sv('tp-sq-dl', p.squeeze_dl_pct);
    sv('tp-cd-sec', p.cooldown_sec); sv('tp-step-up', p.step_up_size); sc('tp-yield-turtle', p.yield_to_turtle);

    _updateDiskSelectorOptions(g.disk?.target_disk || '');
    sc('tp-g-disk-en', g.disk?.enabled); sv('tp-g-disk-warn', g.disk?.warn); sv('tp-g-disk-crit', g.disk?.crit); sv('tp-g-disk-rec', g.disk?.recover);
    sc('tp-g-cpu-en', g.cpu?.enabled); sv('tp-g-cpu-warn', g.cpu?.warn); sv('tp-g-cpu-rec', g.cpu?.recover);
    sc('tp-g-ram-en', g.ram?.enabled); sv('tp-g-ram-min', g.ram?.min_free); sv('tp-g-ram-rec', g.ram?.recover_free);
    sc('tp-g-net-en', g.net?.enabled); sv('tp-g-net-warn', g.net?.warn_pct); sv('tp-g-net-rec', g.net?.recover_pct);

    syncTunerDisabledStates();
}

async function saveTunerProfile() {
    const iv = id => parseInt(document.getElementById(id)?.value) || 0;
    const cb = id => Boolean(document.getElementById(id)?.checked);
    const profile = {
        max_uploads_min: iv('tp-mu-min'), max_uploads_max: iv('tp-mu-max'), max_uploads_start: iv('tp-mu-start'),
        per_torrent_up_min: iv('tp-pt-up-min'), per_torrent_up_max: iv('tp-pt-up-max'), per_torrent_up_auto: cb('tp-pt-up-auto'),
        max_connec_min: iv('tp-mc-min'), max_connec_max: iv('tp-mc-max'), max_connec_auto: cb('tp-mc-auto'),
        per_torrent_connec_min: iv('tp-pt-con-min'), per_torrent_connec_max: iv('tp-pt-con-max'),
        active_uploads_mode: document.getElementById('tp-act-mode')?.value || 'keep',
        active_uploads_min: iv('tp-act-min'), active_uploads_max: iv('tp-act-max'),
        channel_target_min: iv('tp-ch-min'), channel_target_max: iv('tp-ch-max'),
        up_limit_pct: iv('tp-up-pct'), dl_limit_pct: iv('tp-dl-pct'),
        squeeze_enabled: cb('tp-sq-en'), squeeze_up_pct: iv('tp-sq-up'), squeeze_dl_pct: iv('tp-sq-dl'),
        cooldown_sec: iv('tp-cd-sec'), step_up_size: iv('tp-step-up'), yield_to_turtle: cb('tp-yield-turtle'),
        guards: {
            disk: {
                enabled: cb('tp-g-disk-en'),
                target_disk: document.getElementById('tp-g-disk-target')?.value || '',
                warn: iv('tp-g-disk-warn'), crit: iv('tp-g-disk-crit'), recover: iv('tp-g-disk-rec')
            },
            cpu:  { enabled: cb('tp-g-cpu-en'), warn: iv('tp-g-cpu-warn'), recover: iv('tp-g-cpu-rec') },
            ram:  { enabled: cb('tp-g-ram-en'), min_free: iv('tp-g-ram-min'), recover_free: iv('tp-g-ram-rec') },
            net:  { enabled: cb('tp-g-net-en'), warn_pct: iv('tp-g-net-warn'), recover_pct: iv('tp-g-net-rec') }
        }
    };
    const res = await api('/api/tuner/profiles', 'POST', { mode: _tunerCurProfile, profile });
    if (res.ok) { _tunerProfiles[_tunerCurProfile] = (await res.json()).profile; alert(`✅ Профиль «${_tunerCurProfile}» сохранён`); }
}

async function resetTunerProfile() {
    if (!confirm(`Сбросить профиль «${_tunerCurProfile}» к заводским значениям?`)) return;
    const res = await api('/api/tuner/profiles', 'POST', { reset_mode: _tunerCurProfile });
    if (res.ok) { _tunerProfiles[_tunerCurProfile] = (await res.json()).profile; selectTunerProfileTab(_tunerCurProfile); }
}

async function loadTunerRules() {
    const res = await api('/api/tuner/rules');
    if (!res.ok) return;
    _tunerRules = (await res.json()).rules || {};
    const sv = (id, v) => { const e = document.getElementById(id); if (e) e.value = v ?? ''; };
    const sc = (id, v) => { const e = document.getElementById(id); if (e) e.checked = Boolean(v); };

    sv('tr-def-mode', _tunerRules.default_mode || 'performance');
    sv('tr-ov-policy', _tunerRules.override_policy || '2h');
    const pr = _tunerRules.processes || {}, ex = _tunerRules.external_load || {};
    sc('tr-proc-en', pr.enabled); sv('tr-proc-mode', pr.target_mode || 'comfort');
    sv('tr-proc-names', (pr.names || []).join(', ')); sv('tr-proc-enter', pr.enter_sec); sv('tr-proc-exit', pr.exit_sec);
    sc('tr-ext-en', ex.enabled); sv('tr-ext-mode', ex.target_mode || 'comfort');
    sv('tr-ext-cpu-w', ex.cpu_warn); sv('tr-ext-cpu-r', ex.cpu_recover);
    sv('tr-ext-net-w', ex.net_warn_pct); sv('tr-ext-net-r', ex.net_recover_pct);
    sv('tr-ext-ram-w', ex.ram_min_free); sv('tr-ext-ram-r', ex.ram_recover_free);
    sv('tr-ext-enter', ex.enter_sec); sv('tr-ext-exit', ex.exit_sec);

    renderTunerSchedules();
    syncTunerDisabledStates();
}

function renderTunerSchedules() {
    const box = document.getElementById('tr-sched-list');
    if (!box) return;
    const list = _tunerRules.schedules || [];
    box.innerHTML = list.map((s, idx) => `
        <div class="row-gap" style="gap:4px;">
            <input type="time" class="form-control" style="width:96px; padding:3px 4px;" value="${escapeHtml(s.start)}" onchange="_tunerRules.schedules[${idx}].start=this.value">
            <span>—</span>
            <input type="time" class="form-control" style="width:96px; padding:3px 4px;" value="${escapeHtml(s.end)}" onchange="_tunerRules.schedules[${idx}].end=this.value">
            <select class="form-control grow-1" style="padding:3px 4px;" onchange="_tunerRules.schedules[${idx}].mode=this.value">
                <option value="performance" ${s.mode==='performance'?'selected':''}>Производ.</option>
                <option value="comfort" ${s.mode==='comfort'?'selected':''}>Комфорт</option>
            </select>
            <button class="btn btn-danger btn-xs" onclick="_tunerRules.schedules.splice(${idx},1);renderTunerSchedules()">✕</button>
        </div>
    `).join('') || '<span class="lbl-xs muted-text">Окон расписания нет</span>';
}

function addTunerScheduleRow() {
    _tunerRules.schedules = _tunerRules.schedules || [];
    _tunerRules.schedules.push({ start: '01:00', end: '08:00', days: [0, 1, 2, 3, 4, 5, 6], mode: 'performance' });
    renderTunerSchedules();
}

async function loadRunningProcessesPicker() {
    const box = document.getElementById('tr-proc-picker');
    if (!box) return;
    box.classList.remove('hidden'); box.innerHTML = '<span class="lbl-xs muted-text">⏳ Сканирую процессы...</span>';
    const res = await api('/api/tuner/processes');
    if (!res.ok) return;
    const list = (await res.json()).processes || [];
    box.innerHTML = list.map(p => `<button type="button" class="btn btn-secondary btn-xs" onclick="appendProcessToWatchlist('${escapeHtml(p)}')">+ ${escapeHtml(p)}</button>`).join('');
}

function appendProcessToWatchlist(name) {
    const inp = document.getElementById('tr-proc-names');
    const cur = inp.value.split(',').map(x => x.trim()).filter(Boolean);
    if (!cur.some(x => x.toLowerCase() === name.toLowerCase())) { cur.push(name); inp.value = cur.join(', '); }
}

async function saveTunerRules() {
    const iv = id => parseInt(document.getElementById(id)?.value) || 0;
    const cb = id => Boolean(document.getElementById(id)?.checked);
    const rules = {
        default_mode: document.getElementById('tr-def-mode')?.value || 'performance',
        override_policy: document.getElementById('tr-ov-policy')?.value || '2h',
        schedules: _tunerRules.schedules || [],
        processes: {
            enabled: cb('tr-proc-en'), target_mode: document.getElementById('tr-proc-mode')?.value || 'comfort',
            names: (document.getElementById('tr-proc-names')?.value || '').split(',').map(x => x.trim()).filter(Boolean),
            enter_sec: iv('tr-proc-enter'), exit_sec: iv('tr-proc-exit')
        },
        external_load: {
            enabled: cb('tr-ext-en'), target_mode: document.getElementById('tr-ext-mode')?.value || 'comfort',
            cpu_warn: iv('tr-ext-cpu-w'), cpu_recover: iv('tr-ext-cpu-r'),
            net_warn_pct: iv('tr-ext-net-w'), net_recover_pct: iv('tr-ext-net-r'),
            ram_min_free: iv('tr-ext-ram-w'), ram_recover_free: iv('tr-ext-ram-r'),
            enter_sec: iv('tr-ext-enter'), exit_sec: iv('tr-ext-exit')
        }
    };
    const res = await api('/api/tuner/rules', 'POST', { rules });
    if (res.ok) { _tunerRules = (await res.json()).rules; alert('✅ Правила автопереключения сохранены'); }
}

setInterval(() => {
    if (!document.hidden && (typeof CURRENT_ROLE === 'undefined' || CURRENT_ROLE === 'admin')) refreshTunerState();
}, 10000);
```

---

Копируй в `patch.md`, прогоняй `python apply_patch.py`, и обновляй страницу (`Ctrl+F5`):
1. Прямо в строке «Диск I/O» теперь селектор: можно выбрать **«Авто (по раздачам)»**, **«Все диски (Max)»** или конкретный диск (`D:\ (1.2 TiB своб.)`).
2. В карточке телеметрии сверху теперь явно пишется: **`Диск I/O (D:)`**, **`Диск I/O (Авто: D:)`** или **`Диск I/O (Все)`** — сразу понятно, кто под наблюдением.
3. Под капотом Windows отрабатывает IOCTL на уровне ядра, точно привязывая букву диска к правильному счетчику `PhysicalDriveX`!