# core/qb_api.py
import os
import re
import json
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


def reset_qb_session():
    cookie_jar.clear()


def _norm_ip(qb_ip):
    return '127.0.0.1' if qb_ip in ('*', '0.0.0.0') else qb_ip


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
    try:
        with opener.open(req, timeout=2.0) as resp:
            return "Ok." in resp.read().decode('utf-8', errors='ignore')
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


def _get_qb_json(qb_ip, qb_port, path, timeout=1.8):
    if not qb_ip or not qb_port:
        return None
    qb_ip = _norm_ip(qb_ip)
    base_url = f"http://{qb_ip}:{qb_port}"
    req = urllib.request.Request(
        f"{base_url}/api/v2/{path}",
        headers={'Referer': base_url, 'Origin': base_url, 'User-Agent': 'Mozilla/5.0'}
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403) and qb_login(qb_ip, qb_port):
            try:
                with opener.open(req, timeout=timeout) as resp2:
                    return json.loads(resp2.read().decode('utf-8'))
            except Exception:
                pass
        return None
    except Exception:
        return None


def _post_qb_api(qb_ip, qb_port, path, payload=None):
    if not qb_ip or not qb_port:
        return False
    qb_ip = _norm_ip(qb_ip)
    base_url = f"http://{qb_ip}:{qb_port}"
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
        if e.code in (401, 403) and qb_login(qb_ip, qb_port):
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
                'hash': t_hash, 'name': name, 'size': size, 'state': state,
                'error_msg': 'Ошибка клиента / отсутствуют файлы' if state == 'missingfiles' else 'Ошибка торрента в клиенте'
            }

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

    return {'success': True, 'total_scanned': len(live), 'dead_count': len(dead_items), 'groups': grouped_list, 'items': dead_items}


def add_torrent_tags(qb_ip, qb_port, hash_val, tags):
    return bool(hash_val and tags and _post_qb_api(qb_ip, qb_port, 'torrents/addTags', {'hashes': hash_val, 'tags': tags}))


def remove_torrent_tags(qb_ip, qb_port, hash_val, tags):
    return bool(hash_val and tags and _post_qb_api(qb_ip, qb_port, 'torrents/removeTags', {'hashes': hash_val, 'tags': tags}))


def delete_torrents(qb_ip, qb_port, hashes, delete_files=False):
    if not hashes:
        return False
    return _post_qb_api(qb_ip, qb_port, 'torrents/delete', {'hashes': hashes, 'deleteFiles': 'true' if delete_files else 'false'})


def recheck_torrents(qb_ip, qb_port, hashes):
    return bool(hashes and _post_qb_api(qb_ip, qb_port, 'torrents/recheck', {'hashes': hashes}))


def set_global_speed_limits(qb_ip, qb_port, dl_limit_bps, up_limit_bps):
    ok1 = _post_qb_api(qb_ip, qb_port, 'transfer/setDownloadLimit', {'limit': str(max(0, int(dl_limit_bps)))})
    ok2 = _post_qb_api(qb_ip, qb_port, 'transfer/setUploadLimit', {'limit': str(max(0, int(up_limit_bps)))})
    return ok1 and ok2


def shutdown_qb_webui(qb_ip, qb_port):
    return _post_qb_api(qb_ip, qb_port, 'app/shutdown', {})


def send_qb_command(qb_ip, qb_port, action, hash_val):
    if not hash_val:
        return False
    payload = {'hashes': hash_val}
    if action == 'setForceStart':
        payload['value'] = 'true'
    return _post_qb_api(qb_ip, qb_port, f'torrents/{action}', payload)