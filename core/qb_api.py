# core/qb_api.py
import os
import re
import json
import socket
import threading
import urllib.request
import urllib.parse
import http.cookiejar
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.config import cfg
from core.qb_process import (
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


def _can_tcp_connect(ip, port, timeout=0.6):
    try:
        with socket.create_connection((_norm_ip(ip), int(port)), timeout=timeout):
            return True
    except Exception:
        return False


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
                content = f.read()
            m_port = re.search(r'(?im)^(?:WebUI\\Port|Port)=(\d+)\s*$', content)
            if m_port:
                port_from_conf = int(m_port.group(1))
            m_addr = re.search(r'(?im)^(?:WebUI\\Address|Address)=([^\s\r\n]+)\s*$', content)
            if m_addr:
                addr = m_addr.group(1).strip()
                if addr not in ('*', '0.0.0.0', ''):
                    address_from_conf = addr
            if port_from_conf or address_from_conf:
                break
        except Exception:
            pass

    if cfg_addr or cfg_port:
        final_ip = cfg_addr or address_from_conf or '127.0.0.1'
        final_port = cfg_port or port_from_conf or 8080
        return final_ip, final_port

    if port_from_conf:
        cand_ip = address_from_conf or '127.0.0.1'
        if cand_ip != '127.0.0.1' and not _can_tcp_connect(cand_ip, port_from_conf) and _can_tcp_connect('127.0.0.1', port_from_conf):
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
    """Пингует API qBittorrent (отличает 0 раздач от реально упавшего клиента)."""
    if not qb_ip or not qb_port:
        return False
    code, _ = _open_qb_raw(qb_ip, qb_port, "app/version", timeout=timeout)
    return code == 200


def get_qb_version(qb_ip, qb_port, timeout=2.0):
    """Возвращает строку версии qBittorrent (app/version отдаёт plain text, не JSON)."""
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


def _post_qb_api(qb_ip, qb_port, path, payload=None):
    if not qb_ip or not qb_port:
        return False
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
            return resp.getcode() == 200
    except urllib.error.HTTPError as e:
        if e.code in (401, 403) and qb_login(ip, qb_port):
            try:
                with opener.open(req, timeout=3) as resp2:
                    return resp2.getcode() == 200
            except Exception:
                pass
        return False
    except Exception:
        return False


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


def scan_dead_torrents(qb_ip, qb_port):
    if not check_qb_api_alive(qb_ip, qb_port):
        return {'success': False, 'error': 'Не удалось подключиться к WebUI qBittorrent.'}
    live = get_live_torrent_info(qb_ip, qb_port)
    dead_items, groups = [], {}

    def check_one(t_hash, t_info):
        state = str(t_info.get('state', '')).lower()
        name, size = t_info.get('name', t_hash), t_info.get('total_size', 0)
        if state in ('error', 'missingfiles'):
            return {'hash': t_hash, 'name': name, 'size': size, 'state': state, 'error_msg': 'Отсутствуют файлы' if state == 'missingfiles' else 'Ошибка торрента в клиенте'}
        trackers = get_torrent_trackers(qb_ip, qb_port, t_hash)
        real_trackers = [tr for tr in trackers if not str(tr.get('url', '')).startswith('**[') and tr.get('status', 0) != 0]
        if not real_trackers or any(tr.get('status') == 2 for tr in real_trackers):
            return None
        err_msgs = [str(tr.get('msg', '')).strip() for tr in real_trackers if tr.get('status') == 4 and str(tr.get('msg', '')).strip()]
        if not err_msgs:
            if any(tr.get('status') == 4 for tr in real_trackers):
                err_msg = 'Трекер не отвечает (пустой ответ)'
            else:
                return None
        else:
            err_msg = err_msgs[0]
        return {'hash': t_hash, 'name': name, 'size': size, 'state': state, 'error_msg': err_msg}

    with ThreadPoolExecutor(max_workers=12) as pool:
        for fut in as_completed([pool.submit(check_one, h, info) for h, info in live.items()]):
            try:
                res = fut.result()
                if res:
                    dead_items.append(res)
                    groups[res['error_msg']] = groups.get(res['error_msg'], 0) + 1
            except Exception:
                pass

    dead_items.sort(key=lambda x: (x['error_msg'].lower(), x['name'].lower()))
    grouped_list = [{'error_msg': k, 'count': v} for k, v in sorted(groups.items(), key=lambda x: -x[1])]
    return {'success': True, 'total_scanned': len(live), 'dead_count': len(dead_items), 'groups': grouped_list, 'items': dead_items}


def add_torrent_tags(qb_ip, qb_port, hash_val, tags):
    return bool(hash_val and tags and _post_qb_api(qb_ip, qb_port, 'torrents/addTags', {'hashes': hash_val, 'tags': tags}))


def remove_torrent_tags(qb_ip, qb_port, hash_val, tags):
    return bool(hash_val and tags and _post_qb_api(qb_ip, qb_port, 'torrents/removeTags', {'hashes': hash_val, 'tags': tags}))


def delete_torrents(qb_ip, qb_port, hashes, delete_files=False):
    return bool(hashes and _post_qb_api(qb_ip, qb_port, 'torrents/delete', {'hashes': hashes, 'deleteFiles': 'true' if delete_files else 'false'}))


def recheck_torrents(qb_ip, qb_port, hashes):
    return bool(hashes and _post_qb_api(qb_ip, qb_port, 'torrents/recheck', {'hashes': hashes}))


def edit_torrent_tracker(qb_ip, qb_port, t_hash, orig_url, new_url):
    return bool(t_hash and orig_url and new_url and _post_qb_api(qb_ip, qb_port, 'torrents/editTracker', {'hash': t_hash, 'origUrl': orig_url, 'newUrl': new_url}))


def set_torrent_location(qb_ip, qb_port, hashes, location):
    return bool(hashes and location and _post_qb_api(qb_ip, qb_port, 'torrents/setLocation', {'hashes': hashes, 'location': location}))


def set_torrent_file_prio(qb_ip, qb_port, t_hash, file_ids, priority):
    return bool(t_hash and _post_qb_api(qb_ip, qb_port, 'torrents/filePrio', {'hash': t_hash, 'id': str(file_ids), 'priority': str(int(priority))}))


def add_torrent_url(qb_ip, qb_port, urls, savepath='', tags='', paused=False):
    payload = {'urls': urls}
    if savepath:
        payload['savepath'] = savepath
    if tags:
        payload['tags'] = tags
    if paused:
        payload['paused'] = 'true'
    return _post_qb_api(qb_ip, qb_port, 'torrents/add', payload)


def set_global_speed_limits(qb_ip, qb_port, dl_limit_bps, up_limit_bps):
    return _post_qb_api(qb_ip, qb_port, 'transfer/setDownloadLimit', {'limit': str(max(0, int(dl_limit_bps)))}) and \
           _post_qb_api(qb_ip, qb_port, 'transfer/setUploadLimit', {'limit': str(max(0, int(up_limit_bps)))})


def shutdown_qb_webui(qb_ip, qb_port):
    return _post_qb_api(qb_ip, qb_port, 'app/shutdown', {})


def send_qb_command(qb_ip, qb_port, action, hash_val):
    if not hash_val:
        return False
    payload = {'hashes': hash_val}
    if action == 'setForceStart':
        payload['value'] = 'true'
    return _post_qb_api(qb_ip, qb_port, f'torrents/{action}', payload)