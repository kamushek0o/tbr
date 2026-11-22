# core/preflight_inbox.py
import os
import json
import time
import uuid
import shutil
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from utils.config import cfg
from utils.bencode import decode_bencode
from utils.helpers import APP_DATA_DIR, format_file_size
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info, add_torrent_url, opener, qb_login, _norm_ip
from core.torrent_parser import get_all_torrents
from core.torrent_diff import _clean_title
from core.disk_monitor import get_monitored_disk_info
from core.updater import check_for_updates
from core.config_vault import create_config_backup
from core.torrent_archiver import sync_torrent_archive
from core.backup_manager import create_backup_zip

_RADAR_CACHE = {'ts': 0.0, 'qb_latest': '', 'qb_url': ''}


def preflight_analyze(magnet_or_url='', torrent_bytes=None, save_path=''):
    """Pre-Flight проверка перед добавлением раздачи."""
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    queue_left = sum(int(v.get('amount_left', 0) or 0) for v in live.values() if int(v.get('amount_left', 0) or 0) > 0)

    disk_free = 0
    if save_path and os.path.exists(save_path):
        try:
            disk_free = shutil.disk_usage(save_path).free
        except Exception:
            pass
    if disk_free <= 0:
        disk_free = int(get_monitored_disk_info(live).get('free_bytes') or 0)

    real_free = max(0, disk_free - queue_left)
    name, size, is_magnet, info_hash = '', 0, False, ''
    warning = ''

    if torrent_bytes:
        try:
            meta = decode_bencode(torrent_bytes) or {}
            info = meta.get('info') or meta.get(b'info') or {}
            raw_nm = info.get('name.utf-8') or info.get('name') or info.get(b'name') or ''
            name = raw_nm.decode('utf-8', errors='replace') if isinstance(raw_nm, bytes) else str(raw_nm)
            if 'length' in info or b'length' in info:
                size = int(info.get('length') or info.get(b'length') or 0)
            else:
                size = sum(int(f.get('length') or f.get(b'length') or 0) for f in (info.get('files') or info.get(b'files') or []))
        except Exception as e:
            return {'success': False, 'error': f'Битый .torrent файл: {e}'}
    else:
        raw_u = str(magnet_or_url or '').strip()
        if raw_u.lower().startswith('magnet:'):
            is_magnet = True
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_u).query)
            name = (qs.get('dn') or [''])[0]
            xt = (qs.get('xt') or [''])[0]
            if 'btih:' in xt.lower():
                info_hash = xt.lower().split('btih:')[-1][:40]
            warning = 'Для magnet-ссылок размер и состав файлов неизвестны до загрузки метаданных (рекомендуется добавить на паузе).'
        else:
            name = raw_u[:60]

    similar = []
    if name:
        clean_new = _clean_title(name)
        existing = list(live.values()) if live else list(get_all_torrents(use_cache=True).values())
        for ex in existing:
            ex_nm = str(ex.get('name') or '')
            sim = SequenceMatcher(None, clean_new, _clean_title(ex_nm)).ratio() if clean_new else 0.0
            if sim >= 0.72 or (info_hash and str(ex.get('hash', ex.get('hash_id', ''))).lower() == info_hash):
                similar.append({'name': ex_nm, 'similarity': int(sim * 100)})
        similar.sort(key=lambda x: x['similarity'], reverse=True)

    return {
        'success': True,
        'name': name or 'Без имени',
        'size': size,
        'size_fmt': format_file_size(size) if size > 0 else 'Неизвестно',
        'is_magnet': is_magnet,
        'warning': warning,
        'disk_free_fmt': format_file_size(disk_free),
        'queue_left_fmt': format_file_size(queue_left),
        'real_free_fmt': format_file_size(real_free),
        'space_ok': True if (size == 0 or real_free > size) else False,
        'similar': similar[:5]
    }


def add_torrent_to_qb(magnet_or_url='', torrent_bytes=None, filename='upload.torrent', savepath='', tags='', paused=False):
    ip, port = detect_qbittorrent_port(cfg.config)
    if not port:
        return False, 'qBittorrent недоступен'

    if not torrent_bytes:
        ok = add_torrent_url(ip, port, str(magnet_or_url).strip(), savepath=savepath, tags=tags, paused=paused)
        return ok, 'Раздача добавлена' if ok else 'WebUI отклонил ссылку'

    boundary = f"----tbrProBoundary{uuid.uuid4().hex}"
    parts = []
    fields = {}
    if savepath:
        fields['savepath'] = savepath
    if tags:
        fields['tags'] = tags
    if paused:
        fields['paused'] = 'true'
        fields['stopped'] = 'true'

    for k, v in fields.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode('utf-8'))

    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"torrents\"; filename=\"{filename}\"\r\nContent-Type: application/x-bittorrent\r\n\r\n".encode('utf-8')
        + torrent_bytes + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode('utf-8'))
    body = b"".join(parts)

    base_url = f"http://{_norm_ip(ip)}:{port}"
    req = urllib.request.Request(
        f"{base_url}/api/v2/torrents/add",
        data=body, method='POST',
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}', 'Referer': base_url, 'Origin': base_url}
    )
    for attempt in range(2):
        try:
            with opener.open(req, timeout=8) as resp:
                ok = 200 <= resp.getcode() < 300
                return ok, 'Файл .torrent отправлен в qBittorrent' if ok else f'HTTP {resp.getcode()}'
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) and attempt == 0 and qb_login(ip, port):
                continue
            return False, f'HTTP {e.code}'
        except Exception as e:
            return False, str(e)
    return False, 'Ошибка добавления'


def get_update_radar(force=False):
    """Радар обновлений tbr PRO + qBittorrent (кэш 12 часов)."""
    tbr_upd = check_for_updates(force=force)
    now = time.time()
    if force or not _RADAR_CACHE['qb_latest'] or (now - _RADAR_CACHE['ts']) >= 43200:
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/qbittorrent/qBittorrent/releases/latest",
                headers={"User-Agent": "tbr-pro-radar/4.0", "Accept": "application/vnd.github+json"}
            )
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                rel = json.loads(resp.read().decode('utf-8'))
                _RADAR_CACHE['qb_latest'] = str(rel.get('tag_name') or '').strip()
                _RADAR_CACHE['qb_url'] = str(rel.get('html_url') or '')
                _RADAR_CACHE['ts'] = now
        except Exception:
            pass
    return {'tbr': tbr_upd, 'qb_latest': _RADAR_CACHE['qb_latest'] or '—', 'qb_url': _RADAR_CACHE['qb_url']}


def prepare_qb_update_safe():
    """Подготовка к обновлению qB: Config Vault + ZIP БД + Архивариус .torrent."""
    ok_cfg, res_cfg = create_config_backup(reason='pre_update')
    res_arch = sync_torrent_archive()
    os.makedirs(os.path.join(APP_DATA_DIR, 'pre_update_backups'), exist_ok=True)
    zip_bytes = create_backup_zip(exclude_history=False, strip_secrets=False)
    zname = f"pre_update_db_{int(time.time())}.zip"
    with open(os.path.join(APP_DATA_DIR, 'pre_update_backups', zname), 'wb') as f:
        f.write(zip_bytes)
    return {
        'success': True,
        'config_vault': res_cfg if ok_cfg else str(res_cfg),
        'archive_added': res_arch.get('added', 0),
        'db_backup': zname
    }