# core/hygiene_disk.py
import os
import time
import datetime
from utils.config import cfg
from utils.helpers import BT_BACKUP_PATH, format_file_size, write_error_log
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info, get_torrent_files
from core.soft_trash import move_to_trash
from core.app_state_db import app_state_db

_JUNK_EXTS = {'.!qb', '.tmp', '.bak', '.nfo', '.txt', '.url', '.lnk'}
_ARCHIVE_EXTS = {'.zip', '.rar', '.7z', '.tar', '.gz'}
_SUB_EXTS = {'.srt', '.ass', '.ssa', '.vtt', '.sub'}


def scan_bt_backup_garbage():
    """#31 Санитар BT_backup: безпарные, 0-байтные и призраки старше 24ч, отсутствующие в API qB."""
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    if not live:
        return {'success': False, 'error': 'Для безопасной чистки BT_backup необходим запущенный WebUI qBittorrent.', 'items': []}
    if not os.path.isdir(BT_BACKUP_PATH):
        return {'success': False, 'error': 'Папка BT_backup не найдена', 'items': []}

    live_hashes = {h.lower() for h in live.keys()}
    now = time.time()
    min_age = 86400.0  # 24 часа

    by_hash = {}
    for ent in os.scandir(BT_BACKUP_PATH):
        if not ent.is_file():
            continue
        low = ent.name.lower()
        if low.endswith('.fastresume'):
            h, kind = low[:-11], 'fastresume'
        elif low.endswith('.torrent'):
            h, kind = low[:-8], 'torrent'
        else:
            continue
        st = ent.stat()
        by_hash.setdefault(h, {})[kind] = {'path': ent.path, 'name': ent.name, 'size': st.st_size, 'mtime': st.st_mtime}

    items = []
    for h, pair in by_hash.items():
        for kind, info in pair.items():
            if (now - info['mtime']) < min_age:
                continue
            reason = None
            if info['size'] == 0:
                reason = 'Битый файл (0 байт)'
            elif h not in live_hashes:
                reason = 'Призрак (нет в qBittorrent)'
            elif len(pair) == 1:
                reason = f"Без пары (нет .{'torrent' if kind == 'fastresume' else 'fastresume'})"
            if reason:
                items.append({
                    'path': info['path'], 'name': info['name'], 'hash': h,
                    'reason': reason, 'size': info['size'], 'size_fmt': format_file_size(info['size']),
                    'mtime': info['mtime'],
                    'date': datetime.datetime.fromtimestamp(info['mtime']).strftime('%Y-%m-%d %H:%M')
                })

    items.sort(key=lambda x: x['mtime'])
    return {'success': True, 'items': items, 'total_size_fmt': format_file_size(sum(x['size'] for x in items))}


def _classify_inner_file(fname, progress):
    low = fname.lower()
    if low.endswith('.!qb'):
        return 'junk' if progress >= 0.9999 else 'active_part'
    if low.endswith('.parts'):
        return 'active_part'
    _, ext = os.path.splitext(low)
    if ext in _JUNK_EXTS:
        return 'junk'
    if ext in _ARCHIVE_EXTS:
        return 'archive'
    if ext in _SUB_EXTS:
        return 'subtitle'
    return 'other'


def scan_inner_content_junk(limit_torrents=80):
    """#51 Пылесос мусора внутри content_path живых раздач (без авто-удаления)."""
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    if not live:
        return {'success': False, 'error': 'qBittorrent недоступен', 'items': []}

    found = []
    scanned = 0
    for t_hash, info in live.items():
        cp = str(info.get('content_path') or '').strip()
        if not cp or not os.path.isdir(cp):
            continue
        sp = str(info.get('save_path') or '').strip()
        if sp and os.path.normcase(os.path.abspath(cp)) == os.path.normcase(os.path.abspath(sp)):
            continue
        scanned += 1
        if scanned > limit_torrents:
            break

        files = get_torrent_files(ip, port, t_hash)
        if not files:
            continue
        expected = set()
        for f in files:
            rel = str(f.get('name', '')).replace('\\', '/').strip('/')
            parts = rel.split('/', 1)
            rel_inner = parts[1] if len(parts) > 1 else parts[0]
            expected.add(os.path.normcase(rel_inner.replace('/', os.sep)))

        prog = float(info.get('progress', 0.0) or 0.0)
        cp_abs = os.path.abspath(cp)
        try:
            for root, dirs, fnames in os.walk(cp_abs):
                # Не трогаем служебную папку .unwanted (частично снятые файлы qBittorrent)
                dirs[:] = [d for d in dirs if d.lower() != '.unwanted']
                for fn in fnames:
                    full_p = os.path.join(root, fn)
                    rel_disk = os.path.relpath(full_p, cp_abs)
                    rel_check = rel_disk[:-4] if (prog < 0.9999 and rel_disk.lower().endswith('.!qb')) else rel_disk
                    if os.path.normcase(rel_check) in expected or os.path.normcase(rel_disk) in expected:
                        continue
                    cat = _classify_inner_file(fn, prog)
                    if cat == 'active_part':
                        continue
                    try:
                        sz = os.path.getsize(full_p)
                    except OSError:
                        sz = 0
                    found.append({
                        'path': full_p, 'name': fn, 'rel_path': rel_disk,
                        'torrent_name': info.get('name', t_hash), 'category': cat,
                        'size': sz, 'size_fmt': format_file_size(sz)
                    })
        except Exception as e:
            write_error_log(f"scan_inner_content_junk {cp_abs}", e)

    found.sort(key=lambda x: x['size'], reverse=True)
    return {'success': True, 'items': found[:500], 'scanned': scanned}


def trash_paths_list(paths, actor='admin', reason='hygiene'):
    moved, errors = [], []
    for p in (paths or []):
        ok, res = move_to_trash(p, name=os.path.basename(str(p)), actor=actor)
        if ok:
            moved.append(p)
        else:
            errors.append(f"{os.path.basename(str(p))}: {res}")
    if moved:
        app_state_db.add_audit_event('system', f'Гигиена ({reason}) -> _tbr_trash', f'Объектов: {len(moved)}', actor=actor)
    return len(errors) == 0, moved, errors