# core/qb_process.py
import os
import re
import time
import socket
import subprocess
from utils.config import cfg
from utils.helpers import write_error_log, write_log

_WIN_FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def get_local_ips():
    ips = []
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip != '127.0.0.1' and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    try:
        import netifaces
        for iface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(iface).get(netifaces.AF_INET, [])
            for addr in addrs:
                ip = addr.get('addr')
                if ip and ip != '127.0.0.1' and ip not in ips:
                    ips.append(ip)
    except ImportError:
        pass
    return ips


def get_arp_ips():
    ips = []
    try:
        res = subprocess.run(['arp', '-a'], capture_output=True, text=True, creationflags=_WIN_FLAGS)
        for line in res.stdout.splitlines():
            m = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', line)
            if m and m.group(1) != '127.0.0.1' and m.group(1) not in ips:
                ips.append(m.group(1))
    except Exception:
        pass
    return ips


def get_qb_executable_path():
    if os.name != 'nt':
        return "qbittorrent-nox"
    try:
        cmd = ["powershell", "-NoProfile", "-Command", "(Get-Process qbittorrent -ErrorAction SilentlyContinue).Path"]
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=_WIN_FLAGS)
        path = r.stdout.strip().splitlines()[0] if r.stdout.strip() else None
        if path and os.path.exists(path):
            return path
    except Exception:
        pass
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\qBittorrent\qbittorrent.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\qBittorrent\qbittorrent.exe"),
        os.path.expandvars(r"%LocalAppData%\Programs\qBittorrent\qbittorrent.exe")
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "qbittorrent.exe"


def _is_qb_running_windows():
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        h_snap = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        if h_snap == -1 or h_snap == wintypes.HANDLE(-1).value:
            raise OSError("CreateToolhelp32Snapshot failed")

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ('dwSize', wintypes.DWORD),
                ('cntUsage', wintypes.DWORD),
                ('th32ProcessID', wintypes.DWORD),
                ('th32DefaultHeapID', ctypes.c_size_t),
                ('th32ModuleID', wintypes.DWORD),
                ('cntThreads', wintypes.DWORD),
                ('th32ParentProcessID', wintypes.DWORD),
                ('pcPriClassBase', wintypes.LONG),
                ('dwFlags', wintypes.DWORD),
                ('szExeFile', wintypes.WCHAR * 260)
            ]

        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        try:
            if kernel32.Process32FirstW(h_snap, ctypes.byref(entry)):
                while True:
                    if entry.szExeFile.lower() == 'qbittorrent.exe':
                        return True
                    if not kernel32.Process32NextW(h_snap, ctypes.byref(entry)):
                        break
            return False
        finally:
            kernel32.CloseHandle(h_snap)
    except Exception:
        try:
            r = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq qbittorrent.exe'],
                capture_output=True, text=True, creationflags=_WIN_FLAGS
            )
            return 'qbittorrent.exe' in r.stdout.lower()
        except Exception:
            return False


def is_qb_running():
    if os.name != 'nt':
        try:
            from core.qb_api import detect_qbittorrent_port
            ip, port = detect_qbittorrent_port(cfg.config)
            check_ip = '127.0.0.1' if ip in ('*', '0.0.0.0') else ip
            with socket.create_connection((check_ip, int(port)), timeout=0.6):
                return True
        except Exception:
            return False
    return _is_qb_running_windows()


def close_qbittorrent(max_wait_sec=30.0):
    if os.name != 'nt':
        write_log('api', "Управление процессом qBittorrent недоступно в Docker/Linux")
        return False
    if not is_qb_running():
        return True

    write_log('api', "Завершение процесса qBittorrent...")

    # 1. Сначала пробуем WebUI API app/shutdown:
    # Работает даже если qB запущен от Администратора, обходя ошибку 'Access Denied' в taskkill.
    try:
        from core.qb_api import detect_qbittorrent_port, shutdown_qb_webui
        ip, port = detect_qbittorrent_port(cfg.config)
        if port:
            shutdown_qb_webui(ip, port)
    except Exception:
        pass

    # 2. Мягкий taskkill (WM_CLOSE) на случай отключенного WebUI
    try:
        subprocess.run(['taskkill', '/IM', 'qbittorrent.exe'], capture_output=True, creationflags=_WIN_FLAGS)
    except Exception:
        pass

    # 3. Ждём завершения процесса до 30 секунд (клиент сбрасывает кэш на диск)
    deadline = time.monotonic() + max(5.0, float(max_wait_sec))
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if not is_qb_running():
            write_log('api', "qBittorrent успешно завершил работу.")
            return True

    # 4. Если не вышел за 30с — пробуем принудительный taskkill /F
    try:
        subprocess.run(['taskkill', '/F', '/IM', 'qbittorrent.exe'], capture_output=True, creationflags=_WIN_FLAGS)
    except Exception:
        pass

    deadline_force = time.monotonic() + 3.0
    while time.monotonic() < deadline_force:
        time.sleep(0.5)
        if not is_qb_running():
            write_log('api', "qBittorrent принудительно завершён.")
            return True

    write_log('api', "Не удалось завершить qBittorrent: процесс всё ещё в памяти.")
    return False


def launch_qbittorrent(exe_path=None):
    if os.name != 'nt':
        return False
    path = exe_path or get_qb_executable_path()
    try:
        flags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        subprocess.Popen([path], creationflags=flags)
        return True
    except Exception as e:
        write_error_log("Ошибка запуска qBittorrent", e)
        return False