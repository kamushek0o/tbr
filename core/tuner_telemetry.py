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

    def _measure_disk_busy(self, dt_ms, live):
        if not HAS_PSUTIL or dt_ms <= 0:
            return 0.0
        try:
            counters = psutil.disk_io_counters(perdisk=True) or {}
        except Exception:
            return 0.0
        if self._prev_disk is None:
            self._prev_disk = counters
            return 0.0

        target_key = None
        if os.name == 'nt':
            try:
                disk_path = str(get_monitored_disk_info(live).get('path') or '')
                drive_letter = os.path.splitdrive(disk_path)[0].upper().rstrip(':')
                if drive_letter:
                    for k in counters:
                        if drive_letter in k.upper():
                            target_key = k
                            break
            except Exception:
                pass

        max_busy = 0.0
        keys = [target_key] if (target_key and target_key in counters and target_key in self._prev_disk) else list(counters.keys())
        for k in keys:
            if k not in self._prev_disk:
                continue
            c_now, c_old = counters[k], self._prev_disk[k]
            d_read = max(0, getattr(c_now, 'read_time', 0) - getattr(c_old, 'read_time', 0))
            d_write = max(0, getattr(c_now, 'write_time', 0) - getattr(c_old, 'write_time', 0))
            busy = min(100.0, ((d_read + d_write) / dt_ms) * 100.0)
            if busy > max_busy:
                max_busy = busy

        self._prev_disk = counters
        return max_busy

    def collect(self, live, transfer_info, current_max_uploads):
        now = time.monotonic()
        dt_sec = max(0.5, now - self._prev_ts) if self._prev_ts else 10.0
        dt_ms = dt_sec * 1000.0
        self._prev_ts = now

        qb_up = float(transfer_info.get('up_info_speed') or 0)
        qb_dl = float(transfer_info.get('dl_info_speed') or 0)
        max_mbps = max(10, cfg.getint('Max_Channel_Mbps', 1000))
        max_chan_bps = (max_mbps * 1_000_000) / 8.0

        disk_raw = self._measure_disk_busy(dt_ms, live)
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