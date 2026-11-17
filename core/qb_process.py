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
    try:
        r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq qbittorrent.exe'],
                           capture_output=True, text=True, creationflags=_WIN_FLAGS)
        return 'qbittorrent.exe' in r.stdout.lower()
    except Exception:
        return False


def close_qbittorrent():
    if os.name != 'nt':
        write_log('api', "Управление процессом qBittorrent недоступно в Docker/Linux")
        return False
    if not is_qb_running():
        return True
    write_log('api', "Завершение процесса qBittorrent...")
    subprocess.run(['taskkill', '/IM', 'qbittorrent.exe'], capture_output=True, creationflags=_WIN_FLAGS)
    for _ in range(15):
        time.sleep(0.5)
        if not is_qb_running():
            return True
    subprocess.run(['taskkill', '/F', '/IM', 'qbittorrent.exe'], capture_output=True, creationflags=_WIN_FLAGS)
    time.sleep(1)
    return not is_qb_running()


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