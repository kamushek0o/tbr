# core/single_instance.py
import os
import time
from utils.helpers import APP_DATA_DIR


class SingleInstanceLock:
    def __init__(self, name="tbr_swiss_knife_single_instance"):
        self.name = name
        self._handle = None
        self._fd = None
        self._lock_path = os.path.join(APP_DATA_DIR, "tbr.lock")

    def acquire(self, wait_sec=1.5):
        deadline = time.monotonic() + max(0.0, float(wait_sec))
        if os.name == 'nt':
            return self._acquire_windows(deadline)
        return self._acquire_posix(deadline)

    def _acquire_windows(self, deadline):
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        CreateMutexW = kernel32.CreateMutexW
        CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        CreateMutexW.restype = wintypes.HANDLE
        CloseHandle = kernel32.CloseHandle
        ERROR_ALREADY_EXISTS = 183

        mutex_name = f"Local\\{self.name}"
        while True:
            ctypes.set_last_error(0)
            handle = CreateMutexW(None, False, mutex_name)
            err = ctypes.get_last_error()
            if handle and err != ERROR_ALREADY_EXISTS:
                self._handle = handle
                return True
            if handle:
                CloseHandle(handle)
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.15)

    def _acquire_posix(self, deadline):
        import fcntl
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fd = fd
                return True
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    return False
                time.sleep(0.15)
            except Exception:
                os.close(fd)
                return True

    def release(self):
        if os.name == 'nt' and self._handle:
            try:
                import ctypes
                ctypes.WinDLL('kernel32', use_last_error=True).CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None
        elif self._fd is not None:
            try:
                import fcntl
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None