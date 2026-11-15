# core/qb_api.py
import os
import re
import time
import socket
import subprocess
import urllib.request
import urllib.parse
import http.cookiejar
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.config import cfg
from utils.helpers import write_error_log, write_log

cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
_WIN_FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def reset_qb_session():
    cookie_jar.clear()


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
        # На Linux/Docker проверяем доступность порта WebUI
        try:
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


def qb_login(qb_ip, qb_port, username=None, password=None):
    if qb_ip in ('*', '0.0.0.0'):
        qb_ip = '127.0.0.1'
    user = username if username is not None else cfg.get('WebUI_User', 'admin')
    pwd = password if password is not None else cfg.get('WebUI_Password', '')

    base_url = f"http://{qb_ip}:{qb_port}"
    login_url = f"{base_url}/api/v2/auth/login"
    data = urllib.parse.urlencode({'username': user, 'password': pwd}).encode('utf-8')
    req = urllib.request.Request(
        login_url,
        data=data,
        headers={'Referer': base_url, 'Origin': base_url, 'User-Agent': 'Mozilla/5.0'}
    )
    try:
        with opener.open(req, timeout=2.0) as resp:
            body = resp.read().decode('utf-8', errors='ignore')
            return "Ok." in body
    except Exception:
        return False


def detect_qbittorrent_port(config=None):
    env_ip = os.environ.get('TBR_QB_HOST', '').strip()
    env_port = os.environ.get('TBR_QB_PORT', '').strip()
    if env_ip and env_port.isdigit():
        return env_ip, int(env_port)

    if config:
        try:
            address = config.get('Settings', 'WebUI_Address', fallback='').strip()
            raw_port = config.get('Settings', 'WebUI_Port', fallback='').strip()
            port = int(raw_port) if raw_port.isdigit() else None
            if address and port:
                return address, port
        except Exception:
            pass

    if os.name == 'nt':
        config_path = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'qBittorrent', 'qBittorrent.conf')
    else:
        config_path = os.path.join(os.path.expanduser('~'), '.config', 'qBittorrent', 'qBittorrent.conf')

    port_from_conf = None
    address_from_conf = '127.0.0.1'

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            m_port = re.search(r'(?:WebUI\\Port|Port)=(\d+)', content, re.IGNORECASE)
            if m_port:
                port_from_conf = int(m_port.group(1))
            m_addr = re.search(r'(?:WebUI\\Address|Address)=([^\s\r\n]+)', content, re.IGNORECASE)
            if m_addr:
                addr = m_addr.group(1).strip()
                if addr not in ('*', '0.0.0.0', ''):
                    address_from_conf = addr
        except Exception:
            pass

        if port_from_conf:
            return address_from_conf, port_from_conf

    ports_to_check = [port_from_conf] if port_from_conf else [8080, 8081, 1488, 8888]
    for port in filter(None, ports_to_check):
        for ip in ['127.0.0.1', 'localhost']:
            try:
                base_url = f"http://{ip}:{port}"
                req = urllib.request.Request(f"{base_url}/api/v2/app/version", headers={'Referer': base_url})
                with opener.open(req, timeout=0.8) as resp:
                    if resp.getcode() == 200:
                        return ip, port
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    qb_login(ip, port)
                    return ip, port
            except Exception:
                continue

    return '127.0.0.1', (port_from_conf or 8080)


def get_live_torrent_info(qb_ip, qb_port):
    if not qb_ip or not qb_port:
        return {}
    if qb_ip in ('*', '0.0.0.0'):
        qb_ip = '127.0.0.1'

    base_url = f"http://{qb_ip}:{qb_port}"
    req = urllib.request.Request(
        f"{base_url}/api/v2/torrents/info",
        headers={'Referer': base_url, 'Origin': base_url, 'User-Agent': 'Mozilla/5.0'}
    )

    try:
        with opener.open(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return {t['hash']: t for t in data}
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            if qb_login(qb_ip, qb_port):
                try:
                    with opener.open(req, timeout=1.5) as resp:
                        data = json.loads(resp.read().decode('utf-8'))
                        return {t['hash']: t for t in data}
                except Exception:
                    pass
        return {}
    except Exception:
        return {}


def get_torrent_trackers(qb_ip, qb_port, t_hash):
    if qb_ip in ('*', '0.0.0.0'):
        qb_ip = '127.0.0.1'
    base_url = f"http://{qb_ip}:{qb_port}"
    url = f"{base_url}/api/v2/torrents/trackers?hash={urllib.parse.quote(t_hash)}"
    req = urllib.request.Request(url, headers={'Referer': base_url, 'Origin': base_url, 'User-Agent': 'Mozilla/5.0'})
    try:
        with opener.open(req, timeout=2.0) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return []


def scan_dead_torrents(qb_ip, qb_port):
    live = get_live_torrent_info(qb_ip, qb_port)
    if not live:
        return {'success': False, 'error': 'Не удалось подключиться к WebUI qBittorrent (проверьте запуск или логин/пароль).'}

    dead_items = []
    groups = {}

    def check_one(t_hash, t_info):
        state = str(t_info.get('state', '')).lower()
        name = t_info.get('name', t_hash)
        size = t_info.get('total_size', 0)

        if state in ('error', 'missingfiles'):
            return {
                'hash': t_hash,
                'name': name,
                'size': size,
                'state': state,
                'error_msg': 'Ошибка клиента / отсутствуют файлы' if state == 'missingfiles' else 'Ошибка торрента в клиенте'
            }

        trackers = get_torrent_trackers(qb_ip, qb_port, t_hash)
        real_trackers = [
            tr for tr in trackers
            if not str(tr.get('url', '')).startswith('**[') and tr.get('status', 0) != 0
        ]
        if not real_trackers:
            return None

        any_working = any(tr.get('status') == 2 for tr in real_trackers)
        if any_working:
            return None

        err_msgs = [str(tr.get('msg', '')).strip() for tr in real_trackers if tr.get('status') == 4 and str(tr.get('msg', '')).strip()]
        if not err_msgs:
            if any(tr.get('status') == 4 for tr in real_trackers):
                err_msg = 'Трекер не отвечает (пустой ответ)'
            else:
                return None
        else:
            err_msg = err_msgs[0]

        return {
            'hash': t_hash,
            'name': name,
            'size': size,
            'state': state,
            'error_msg': err_msg
        }

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(check_one, h, info): h for h, info in live.items()}
        for fut in as_completed(futures):
            try:
                res = fut.result()
                if res:
                    dead_items.append(res)
                    msg = res['error_msg']
                    groups[msg] = groups.get(msg, 0) + 1
            except Exception:
                pass

    dead_items.sort(key=lambda x: (x['error_msg'].lower(), x['name'].lower()))
    grouped_list = [{'error_msg': k, 'count': v} for k, v in sorted(groups.items(), key=lambda x: -x[1])]

    return {
        'success': True,
        'total_scanned': len(live),
        'dead_count': len(dead_items),
        'groups': grouped_list,
        'items': dead_items
    }


def add_torrent_tags(qb_ip, qb_port, hash_val, tags):
    if not qb_ip or not qb_port or not hash_val or not tags:
        return False
    if qb_ip in ('*', '0.0.0.0'):
        qb_ip = '127.0.0.1'

    base_url = f"http://{qb_ip}:{qb_port}"
    payload = {'hashes': hash_val, 'tags': tags}
    req = urllib.request.Request(
        f"{base_url}/api/v2/torrents/addTags",
        data=urllib.parse.urlencode(payload).encode('utf-8'),
        method='POST',
        headers={'Content-Type': 'application/x-www-form-urlencoded', 'Referer': base_url, 'Origin': base_url}
    )
    try:
        with opener.open(req, timeout=3) as resp:
            return resp.getcode() == 200
    except urllib.error.HTTPError as e:
        if e.code in (401, 403) and qb_login(qb_ip, qb_port):
            try:
                with opener.open(req, timeout=3) as resp2:
                    return resp2.getcode() == 200
            except Exception:
                pass
        return False
    except Exception:
        return False


def send_qb_command(qb_ip, qb_port, action, hash_val):
    if not qb_ip or not qb_port or not hash_val:
        return False
    if qb_ip in ('*', '0.0.0.0'):
        qb_ip = '127.0.0.1'

    base_url = f"http://{qb_ip}:{qb_port}"
    payload = {'hashes': hash_val}
    if action == 'setForceStart':
        payload['value'] = 'true'

    req = urllib.request.Request(
        f"{base_url}/api/v2/torrents/{action}",
        data=urllib.parse.urlencode(payload).encode('utf-8'),
        method='POST',
        headers={'Content-Type': 'application/x-www-form-urlencoded', 'Referer': base_url, 'Origin': base_url}
    )

    try:
        with opener.open(req, timeout=3) as resp:
            return resp.getcode() == 200
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            if qb_login(qb_ip, qb_port):
                try:
                    with opener.open(req, timeout=3) as resp2:
                        return resp2.getcode() == 200
                except Exception:
                    pass
        return False
    except Exception:
        return False