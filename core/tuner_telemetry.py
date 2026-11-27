# core/tuner_telemetry.py
import os
import time
from utils.config import cfg
from core.disk_monitor import get_monitored_disk_info
from core.tuner_presets import APP_FRIENDLY_NAMES

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False

_SYS_EXE_NAMES = {
    'system', 'system idle process', 'registry', 'smss.exe', 'csrss.exe', 'wininit.exe',
    'services.exe', 'lsass.exe', 'svchost.exe', 'fontdrvhost.exe', 'dwm.exe', 'conhost.exe',
    'sihost.exe', 'taskhostw.exe', 'runtimebroker.exe', 'searchindexer.exe', 'searchhost.exe',
    'dllhost.exe', 'audiodg.exe', 'spoolsv.exe', 'ctfmon.exe', 'WmiPrvSE.exe'.lower(),
    'memory compression', 'vmmem', 'vmmemwsl', 'msedgewebview2.exe', 'crashpad_handler.exe'
}
_SKIP_DIR_NAMES = {'bin', 'x64', 'x86', 'win64', 'win32', 'release', 'debug', 'binaries', 'application', 'app', 'program files', 'program files (x86)'}


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
                _fields_ = [('DeviceType', wintypes.DWORD), ('DeviceNumber', wintypes.DWORD), ('PartitionNumber', wintypes.DWORD)]
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
        sys_path = f"/sys/dev/block/{os.major(st.st_dev)}:{os.minor(st.st_dev)}"
        if os.path.exists(sys_path):
            parts = os.path.realpath(sys_path).split(os.sep)
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
        self._proc_cache_ts = 0.0
        self._proc_cache_map = {}

    def _smooth(self, key, val):
        self._ema[key] = float(val) if key not in self._ema else (0.3 * float(val) + 0.7 * self._ema[key])
        return self._ema[key]

    def get_running_exe_map(self):
        """Легковесный кэшируемый опрос имён процессов для 2–3с цикла без нагрузки на CPU."""
        if not HAS_PSUTIL:
            return {}
        now = time.monotonic()
        if (now - self._proc_cache_ts) < 1.5 and self._proc_cache_map:
            return self._proc_cache_map
        found = {}
        for p in psutil.process_iter(['name']):
            try:
                nm = str(p.info.get('name') or '').strip()
                if nm:
                    low = nm.lower()
                    found[low] = nm
                    if low.endswith('.exe'):
                        found[low[:-4]] = nm
            except Exception:
                continue
        self._proc_cache_map = found
        self._proc_cache_ts = now
        return found

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
                target_key = _get_windows_physical_drive(clean_p.rstrip(':\\/'))
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
        dt_sec = max(0.5, now - self._prev_ts) if self._prev_ts else 3.0
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
                    net_ext_raw = max(0.0, (d_tot / dt_sec) - (qb_dl + qb_up))
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
            'disk_busy': round(ema_disk, 1), 'monitored_disk_label': disk_label,
            'cpu_ext': round(ema_cpu, 1), 'ram_free': round(ema_ram, 1),
            'net_ext_bps': int(ema_net_ext), 'net_ext_pct': round(net_ext_pct, 1),
            'qb_up_bps': int(ema_qb_up), 'channel_pct': round(chan_pct, 1),
            'active_up_peers': active_up_peers, 'slots_fill_pct': round(slots_fill_pct, 1),
            'max_channel_bps': int(max_chan_bps)
        }


def _guess_friendly_name(exe_name, exe_path):
    low = exe_name.lower()
    if low in APP_FRIENDLY_NAMES:
        return APP_FRIENDLY_NAMES[low]['name'], APP_FRIENDLY_NAMES[low]['icon']
    if exe_path:
        parts = [p for p in os.path.dirname(exe_path).replace('\\', '/').split('/') if p]
        for folder in reversed(parts):
            fl = folder.lower()
            if fl not in _SKIP_DIR_NAMES and not fl.endswith(':'):
                return folder[:32], '📦'
    base = exe_name[:-4] if low.endswith('.exe') else exe_name
    return base.replace('_', ' ').title()[:32], '🖥️'


def list_running_processes_smart(include_system=False):
    if not HAS_PSUTIL:
        return []
    grouped = {}
    for p in psutil.process_iter(['name', 'exe']):
        try:
            nm = str(p.info.get('name') or '').strip()
            if not nm:
                continue
            low = nm.lower()
            exe_path = str(p.info.get('exe') or '').strip()
            path_low = exe_path.lower().replace('/', '\\')
            is_sys = (low in _SYS_EXE_NAMES) or ('\\windows\\system32\\' in path_low) or ('\\windows\\syswow64\\' in path_low) or ('\\windows\\winsxs\\' in path_low)
            if not include_system and is_sys:
                continue
            if low in grouped:
                grouped[low]['count'] += 1
            else:
                label, icon = _guess_friendly_name(nm, exe_path)
                grouped[low] = {'exe': nm, 'label': label, 'icon': icon, 'is_system': is_sys, 'count': 1}
        except Exception:
            continue
    return sorted(grouped.values(), key=lambda x: (x['is_system'], x['label'].lower()))


telemetry_collector = TelemetryCollector()
