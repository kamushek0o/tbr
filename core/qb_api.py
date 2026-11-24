# core/qb_api.py
import os
import re
import json
import threading
import urllib.request
import urllib.parse
import http.cookiejar
from utils.config import cfg
from core.qb_process import (  # noqa: F401
    get_local_ips, get_arp_ips, get_qb_executable_path,
    is_qb_running, close_qbittorrent, launch_qbittorrent
)

cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
_AUTH_LOCK = threading.Lock()


def reset_qb_session():
    with _AUTH_LOCK:
        cookie_jar.clear()


def _norm_ip(qb_ip):
    return '127.0.0.1' if qb_ip in ('*', '0.0.0.0', '') else qb_ip


def qb_login(qb_ip, qb_port, username=None, password=None):
    qb_ip = _norm_ip(qb_ip)
    user = username if username is not None else cfg.get('WebUI_User', 'admin')
    pwd = password if password is not None else cfg.get('WebUI_Password', '')

    base_url = f"http://{qb_ip}:{qb_port}"
    data = urllib.parse.urlencode({'username': user, 'password': pwd}).encode('utf-8')
    req = urllib.request.Request(
        f"{base_url}/api/v2/auth/login",
        data=data,
        headers={'Referer': base_url, 'Origin': base_url, 'User-Agent': 'Mozilla/5.0'}
    )
    with _AUTH_LOCK:
        try:
            with opener.open(req, timeout=2.5) as resp:
                return "Ok." in resp.read().decode('utf-8', errors='ignore')
        except Exception:
            return False


def _qb_config_candidates():
    if os.name == 'nt':
        return [
            os.path.join(os.environ.get('APPDATA', ''), 'qBittorrent', 'qBittorrent.ini'),
            os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming', 'qBittorrent', 'qBittorrent.ini'),
            os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'qBittorrent', 'qBittorrent.conf'),
        ]
    return [
        '/config/qBittorrent/qBittorrent.conf',
        '/config/qBittorrent.conf',
        os.path.join(os.path.expanduser('~'), '.config', 'qBittorrent', 'qBittorrent.conf'),
    ]


def _parse_qb_conf_file(content):
    m_port = re.search(r'(?im)^WebUI\\Port=(\d+)\s*$', content) or re.search(r'(?im)^Port=(\d+)\s*$', content)
    m_addr = re.search(r'(?im)^WebUI\\Address=([^\s\r\n]+)\s*$', content) or re.search(r'(?im)^Address=([^\s\r\n]+)\s*$', content)
    port = int(m_port.group(1)) if m_port else None
    addr = m_addr.group(1).strip() if m_addr else ''
    if addr in ('*', '0.0.0.0'):
        addr = ''
    return addr, port


def detect_qbittorrent_port(config=None):
    env_ip = os.environ.get('TBR_QB_HOST', '').strip()
    env_port = os.environ.get('TBR_QB_PORT', '').strip()
    if env_ip and env_port.isdigit():
        return env_ip, int(env_port)

    cfg_addr, cfg_port = '', None
    if config:
        try:
            cfg_addr = config.get('Settings', 'WebUI_Address', fallback='').strip()
            raw_port = config.get('Settings', 'WebUI_Port', fallback='').strip()
            cfg_port = int(raw_port) if raw_port.isdigit() else None
            if cfg_addr and cfg_port:
                return cfg_addr, cfg_port
        except Exception:
            pass

    port_from_conf, address_from_conf = None, ''
    for config_path in _qb_config_candidates():
        if not config_path or not os.path.exists(config_path):
            continue
        try:
            with open(config_path, 'r', encoding='utf-8', errors='ignore') as f:
                address_from_conf, port_from_conf = _parse_qb_conf_file(f.read())
            if port_from_conf or address_from_conf:
                break
        except Exception:
            pass

    if cfg_addr or cfg_port:
        return (cfg_addr or address_from_conf or '127.0.0.1'), (cfg_port or port_from_conf or 8080)

    if port_from_conf:
        cand_ip = address_from_conf or '127.0.0.1'
        if cand_ip != '127.0.0.1' and not check_qb_api_alive(cand_ip, port_from_conf, timeout=0.6):
            if check_qb_api_alive('127.0.0.1', port_from_conf, timeout=0.6):
                return '127.0.0.1', port_from_conf
        return cand_ip, port_from_conf

    for port in (8080, 8081, 1488, 8888):
        for ip in ('127.0.0.1', 'localhost'):
            if check_qb_api_alive(ip, port, timeout=0.8):
                return ip, port

    return address_from_conf or '127.0.0.1', 8080


def _open_qb_raw(qb_ip, qb_port, path, timeout=2.0):
    ip = _norm_ip(qb_ip)
    base_url = f"http://{ip}:{qb_port}"
    req = urllib.request.Request(
        f"{base_url}/api/v2/{path}",
        headers={'Referer': base_url, 'Origin': base_url, 'User-Agent': 'Mozilla/5.0'}
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        if e.code in (401, 403) and qb_login(ip, qb_port):
            try:
                with opener.open(req, timeout=timeout) as resp2:
                    return resp2.getcode(), resp2.read().decode('utf-8', errors='replace')
            except Exception:
                return None, None
        return e.code, None
    except Exception:
        return None, None


def check_qb_api_alive(qb_ip, qb_port, timeout=1.5):
    if not qb_ip or not qb_port:
        return False
    code, _ = _open_qb_raw(qb_ip, qb_port, "app/version", timeout=timeout)
    return code == 200


def get_qb_version(qb_ip, qb_port, timeout=2.0):
    if not qb_ip or not qb_port:
        return None
    code, body = _open_qb_raw(qb_ip, qb_port, "app/version", timeout=timeout)
    return body.strip() if (code == 200 and body) else None


def _get_qb_json(qb_ip, qb_port, path, timeout=1.8):
    if not qb_ip or not qb_port:
        return None
    code, body = _open_qb_raw(qb_ip, qb_port, path, timeout=timeout)
    if code == 200 and body is not None:
        try:
            return json.loads(body)
        except Exception:
            return None
    return None


def _post_qb_api_code(qb_ip, qb_port, path, payload=None):
    if not qb_ip or not qb_port:
        return 0
    ip = _norm_ip(qb_ip)
    base_url = f"http://{ip}:{qb_port}"
    body = urllib.parse.urlencode(payload or {}).encode('utf-8')
    req = urllib.request.Request(
        f"{base_url}/api/v2/{path}",
        data=body,
        method='POST',
        headers={'Content-Type': 'application/x-www-form-urlencoded', 'Referer': base_url, 'Origin': base_url}
    )
    try:
        with opener.open(req, timeout=3) as resp:
            return resp.getcode()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403) and qb_login(ip, qb_port):
            try:
                with opener.open(req, timeout=3) as resp2:
                    return resp2.getcode()
            except urllib.error.HTTPError as e2:
                return e2.code
            except Exception:
                return 0
        return e.code
    except Exception:
        return 0


def _post_qb_api(qb_ip, qb_port, path, payload=None):
    code = _post_qb_api_code(qb_ip, qb_port, path, payload)
    return 200 <= code < 300


def get_live_torrent_info(qb_ip, qb_port):
    data = _get_qb_json(qb_ip, qb_port, "torrents/info", timeout=1.8)
    return {t['hash']: t for t in data} if isinstance(data, list) else {}


def get_transfer_info(qb_ip, qb_port):
    data = _get_qb_json(qb_ip, qb_port, "transfer/info", timeout=1.5)
    return data if isinstance(data, dict) else {}


def get_torrent_trackers(qb_ip, qb_port, t_hash):
    data = _get_qb_json(qb_ip, qb_port, f"torrents/trackers?hash={urllib.parse.quote(t_hash)}", timeout=2.0)
    return data if isinstance(data, list) else []


def get_torrent_files(qb_ip, qb_port, t_hash):
    data = _get_qb_json(qb_ip, qb_port, f"torrents/files?hash={urllib.parse.quote(t_hash)}", timeout=3.0)
    return data if isinstance(data, list) else []


def get_torrent_peers(qb_ip, qb_port, t_hash):
    data = _get_qb_json(qb_ip, qb_port, f"sync/torrentPeers?hash={urllib.parse.quote(t_hash)}&rid=0", timeout=2.0)
    return data if isinstance(data, dict) else {}


from core.qb_actions import (  # noqa: E402, F401
    scan_dead_torrents, add_torrent_tags, remove_torrent_tags, delete_torrents,
    recheck_torrents, edit_torrent_tracker, set_torrent_location,
    set_torrent_file_prio, add_torrent_url, set_global_speed_limits,
    shutdown_qb_webui, send_qb_command
)