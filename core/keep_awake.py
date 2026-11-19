# core/keep_awake.py
import os
import threading
from utils.config import cfg
from utils.helpers import write_log, write_error_log

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

_ACTIVE_DL_STATES = ("downloading", "forceddl", "metadl", "allocating", "stalleddl")


class KeepAwakeController:
    def __init__(self):
        self._lock = threading.Lock()
        self._active = False
        self._display_on = False
        self._want_keep = False
        self._want_display = False
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread = None

    @staticmethod
    def is_supported():
        return os.name == "nt"

    def _set_win_state(self, keep, with_display):
        if not self.is_supported():
            return
        try:
            import ctypes
            flags = ES_CONTINUOUS
            if keep:
                flags |= ES_SYSTEM_REQUIRED
                if with_display:
                    flags |= ES_DISPLAY_REQUIRED
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
        except Exception as e:
            write_error_log("KeepAwake SetThreadExecutionState", e)

    def _ensure_thread(self):
        if not self.is_supported():
            return
        if self._thread and self._thread.is_alive():
            return

        def worker():
            while not self._stop_event.is_set():
                with self._lock:
                    w_keep = self._want_keep
                    w_disp = self._want_display
                if w_keep != self._active or (w_keep and w_disp != self._display_on):
                    self._set_win_state(w_keep, w_disp)
                    self._active = w_keep
                    self._display_on = w_disp if w_keep else False
                    write_log("app", f"Keep-Awake: {'ВКЛ' if w_keep else 'ВЫКЛ'} (display={w_disp})")
                elif w_keep:
                    # Поддерживаем актуальность состояния пока идёт активность
                    self._set_win_state(True, w_disp)
                self._wake_event.wait(timeout=30.0)
                self._wake_event.clear()

            if self._active:
                self._set_win_state(False, False)
                self._active = False
                self._display_on = False

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()

    def evaluate(self, live_torrents):
        if not self.is_supported():
            return False

        enabled = cfg.getboolean("KeepAwake_Enabled", False)
        if not enabled:
            self.release()
            return False

        min_kb = max(0, cfg.getint("KeepAwake_Min_KB", 500))
        with_display = cfg.getboolean("KeepAwake_Display", False)

        has_dl = False
        total_up_bps = 0
        for info in (live_torrents or {}).values():
            st = str(info.get("state", "")).lower()
            amt_left = int(info.get("amount_left", 0) or 0)
            dl_spd = int(info.get("dlspeed", 0) or 0)
            if (st in _ACTIVE_DL_STATES and amt_left > 0) or dl_spd > 0:
                has_dl = True
            total_up_bps += int(info.get("upspeed", 0) or 0)

        should_keep = has_dl or (total_up_bps >= (min_kb * 1024))
        with self._lock:
            self._want_keep = should_keep
            self._want_display = with_display
        self._ensure_thread()
        self._wake_event.set()
        return should_keep

    def release(self):
        with self._lock:
            changed = self._want_keep
            self._want_keep = False
            self._want_display = False
        if changed and self._thread and self._thread.is_alive():
            self._wake_event.set()

    def stop(self):
        with self._lock:
            self._want_keep = False
            self._want_display = False
        self._stop_event.set()
        self._wake_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)


keep_awake = KeepAwakeController()