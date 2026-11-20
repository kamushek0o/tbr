# core/path_remapper.py
import os
from utils.bencode import decode_bencode, encode_bencode
from utils.helpers import BT_BACKUP_PATH, write_error_log
from core.qb_process import is_qb_running
from core.soft_trash import create_fastresume_snapshot
from core.torrent_parser import force_clear_cache
from core.app_state_db import app_state_db


def _get_str_val(data, key):
    val = data.get(key)
    if val is None:
        val = data.get(key.encode('ascii'))
    if val is None:
        return ''
    return val.decode('utf-8', errors='replace') if isinstance(val, bytes) else str(val)


def _set_str_val(data, key, new_val):
    kb = key.encode('ascii')
    if kb in data or any(isinstance(k, bytes) for k in data.keys()):
        data[kb] = new_val
        data.pop(key, None)
    else:
        data[key] = new_val
        data.pop(kb, None)


def _remap_single_path(orig_path, old_prefix, new_prefix):
    if not orig_path:
        return None
    norm_orig = orig_path.replace('\\', '/')
    norm_old = old_prefix.replace('\\', '/').rstrip('/')
    norm_new = new_prefix.replace('\\', '/').rstrip('/')

    orig_cmp = norm_orig.lower() if os.name == 'nt' else norm_orig
    old_cmp = norm_old.lower() if os.name == 'nt' else norm_old

    if orig_cmp == old_cmp or orig_cmp.startswith(old_cmp + '/'):
        remapped = norm_new + norm_orig[len(norm_old):]
        if '\\' in orig_path and '/' not in orig_path:
            remapped = remapped.replace('/', '\\')
        return remapped
    return None


def preview_fastresume_remap(old_prefix, new_prefix):
    op = str(old_prefix or '').strip()
    np = str(new_prefix or '').strip()
    if not op or not np or op == np:
        return {'success': False, 'error': 'Укажите разные префиксы пути', 'items': []}
    if not os.path.isdir(BT_BACKUP_PATH):
        return {'success': False, 'error': 'Папка BT_backup не найдена', 'items': []}

    items = []
    for ent in os.scandir(BT_BACKUP_PATH):
        if not ent.is_file() or not ent.name.lower().endswith('.fastresume'):
            continue
        h = ent.name[:-11].lower()
        try:
            with open(ent.path, 'rb') as f:
                data = decode_bencode(f.read())
            if not isinstance(data, dict):
                continue
            sp = _get_str_val(data, 'save_path') or _get_str_val(data, 'qBt-savePath')
            new_sp = _remap_single_path(sp, op, np)
            if new_sp and new_sp != sp:
                items.append({'hash': h, 'name': _get_str_val(data, 'qBt-name') or h, 'old_path': sp, 'new_path': new_sp})
        except Exception:
            continue

    return {'success': True, 'items': items, 'count': len(items), 'qb_running': is_qb_running()}


def apply_fastresume_remap(old_prefix, new_prefix, actor='admin'):
    if is_qb_running():
        return {'success': False, 'error': '🛑 Остановите qBittorrent перед редактированием .fastresume!'}

    prev = preview_fastresume_remap(old_prefix, new_prefix)
    if not prev.get('success'):
        return prev
    items = prev.get('items') or []
    if not items:
        return {'success': False, 'error': 'Совпадающих .fastresume не найдено'}

    create_fastresume_snapshot([it['hash'] for it in items], reason='remap')
    updated = 0
    errors = []

    for it in items:
        fpath = os.path.join(BT_BACKUP_PATH, it['hash'] + '.fastresume')
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, 'rb') as f:
                data = decode_bencode(f.read())
            for key in ('save_path', 'qBt-savePath'):
                cur = _get_str_val(data, key)
                rem = _remap_single_path(cur, old_prefix, new_prefix)
                if rem:
                    _set_str_val(data, key, rem)
            encoded = encode_bencode(data)
            tmp = fpath + '.tmp'
            with open(tmp, 'wb') as out:
                out.write(encoded)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, fpath)
            updated += 1
        except Exception as e:
            write_error_log(f"remap {it['hash']}", e)
            errors.append(f"{it['hash'][:8]}: {e}")

    force_clear_cache()
    if updated:
        app_state_db.add_audit_event('system', 'Remap .fastresume путей', f'{old_prefix} -> {new_prefix} ({updated} шт.)', actor=actor)
    return {'success': len(errors) == 0, 'updated': updated, 'errors': errors}