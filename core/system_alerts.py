# core/system_alerts.py
import os
import time
import shutil
from utils.config import cfg
from utils.helpers import BT_BACKUP_PATH, APP_DATA_DIR, format_file_size, write_log
from core.notifiers import notify_all


class SystemAlertsMonitor:
    def __init__(self):
        self.disk_state = 'OK'  # OK | ALERT
        self.qb_state = 'OK'    # OK | ALERT
        self._qb_down_since = None

    def _get_free_gib(self, live):
        paths = []
        if live:
            for info in live.values():
                sp = info.get('save_path')
                if sp and os.path.exists(sp):
                    paths.append(sp)
                    break
        paths.extend([BT_BACKUP_PATH, APP_DATA_DIR])
        for p in paths:
            try:
                if p and os.path.exists(p):
                    return shutil.disk_usage(p).free / (1024 ** 3)
            except Exception:
                continue
        return None

    def check(self, qb_available, live=None):
        now = time.time()

        # 1. Мониторинг WebUI qBittorrent (отвал > 150 сек, чтобы игнорить рестарт при мердже)
        if cfg.getboolean('Alert_QB_Down', False):
            if not qb_available:
                if self._qb_down_since is None:
                    self._qb_down_since = now
                elif (now - self._qb_down_since) >= 150 and self.qb_state == 'OK':
                    self.qb_state = 'ALERT'
                    write_log('automation', "ALERT: WebUI qBittorrent недоступен > 2.5 мин")
                    notify_all("🚨 tbr PRO — qBittorrent недоступен", ["WebUI qBittorrent не отвечает уже более 2.5 минут."])
            else:
                self._qb_down_since = None
                if self.qb_state == 'ALERT':
                    self.qb_state = 'OK'
                    write_log('automation', "RECOVERED: WebUI qBittorrent снова в сети")
                    notify_all("✅ tbr PRO — qBittorrent восстановлен", ["Связь с WebUI qBittorrent успешно восстановлена."])

        # 2. Мониторинг свободного места на диске (гистерезис +5 GiB)
        min_gib = float(cfg.getint('Alert_Disk_Min_GiB', 0) or 0)
        if min_gib > 0:
            free_gib = self._get_free_gib(live)
            if free_gib is not None:
                if free_gib < min_gib and self.disk_state == 'OK':
                    self.disk_state = 'ALERT'
                    free_fmt = format_file_size(int(free_gib * (1024 ** 3)))
                    write_log('automation', f"ALERT: мало места на диске ({free_fmt} < {min_gib:.0f} GiB)")
                    notify_all("⚠️ tbr PRO — Мало места на диске!", [f"Свободно: {free_fmt} (порог: {min_gib:.0f} GiB)"])
                elif free_gib >= (min_gib + 5.0) and self.disk_state == 'ALERT':
                    self.disk_state = 'OK'
                    free_fmt = format_file_size(int(free_gib * (1024 ** 3)))
                    write_log('automation', f"RECOVERED: место на диске в норме ({free_fmt})")
                    notify_all("✅ tbr PRO — Место на диске в норме", [f"Свободно: {free_fmt}"])


system_alerts = SystemAlertsMonitor()