# core/system_alerts.py
import time
from utils.config import cfg
from utils.helpers import format_file_size, write_log
from core.notifiers import notify_all
from core.disk_monitor import get_monitored_disk_info


class SystemAlertsMonitor:
    def __init__(self):
        self.disk_state = 'OK'  # OK | ALERT
        self.qb_state = 'OK'    # OK | ALERT
        self._qb_down_since = None

    def check(self, qb_available, live=None):
        now = time.time()

        if cfg.getboolean('Alert_QB_Down', False):
            if not qb_available:
                if self._qb_down_since is None:
                    self._qb_down_since = now
                elif (now - self._qb_down_since) >= 150 and self.qb_state == 'OK':
                    self.qb_state = 'ALERT'
                    write_log('automation', "ALERT: WebUI qBittorrent недоступен > 2.5 мин")
                    notify_all("🚨 tbr PRO — qBittorrent недоступен", ["WebUI qBittorrent не отвечает уже более 2.5 минут."], critical=True)
            else:
                self._qb_down_since = None
                if self.qb_state == 'ALERT':
                    self.qb_state = 'OK'
                    write_log('automation', "RECOVERED: WebUI qBittorrent снова в сети")
                    notify_all("✅ tbr PRO — qBittorrent восстановлен", ["Связь с WebUI qBittorrent успешно восстановлена."], critical=True)

        min_gib = float(cfg.getint('Alert_Disk_Min_GiB', 0) or 0)
        if min_gib > 0:
            disk = get_monitored_disk_info(live)
            if disk.get('total_bytes', 0) > 0:
                free_gib = float(disk['free_bytes']) / (1024 ** 3)
                free_fmt = format_file_size(disk['free_bytes'])
                if free_gib < min_gib and self.disk_state == 'OK':
                    self.disk_state = 'ALERT'
                    write_log('automation', f"ALERT: мало места на {disk['path']} ({free_fmt} < {min_gib:.0f} GiB)")
                    notify_all("⚠️ tbr PRO — Мало места на диске!", [f"Диск: {disk['path']}", f"Свободно: {free_fmt} (порог: {min_gib:.0f} GiB)"], critical=True)
                elif free_gib >= (min_gib + 5.0) and self.disk_state == 'ALERT':
                    self.disk_state = 'OK'
                    write_log('automation', f"RECOVERED: место на {disk['path']} в норме ({free_fmt})")
                    notify_all("✅ tbr PRO — Место на диске в норме", [f"Диск: {disk['path']}", f"Свободно: {free_fmt}"], critical=True)


system_alerts = SystemAlertsMonitor()