# core/orphan_scanner.py
import os
import re
import shutil
import datetime
from utils.config import cfg
from utils.helpers import format_file_size, write_error_log
from core.torrent_parser import get_all_torrents
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info
from core.app_state_db import app_state_db
from core.soft_trash import move_to_trash


def _norm(p):
    return os.path.normcase(os.path.normpath(os.path.abspath(str(p).strip())))


def _read_qb_default_save_path():
    if os.name == 'nt':
        conf = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'qBittorrent', 'qBittorrent.conf')
    else:
        conf = os.path.join(os.path.expanduser('~'), '.config', 'qBittorrent', 'qBittorrent.conf')
    if not os.path.isfile(conf):
        return ''
    try:
        with open(conf, 'r', encoding='utf-8', errors='ignore') as f:
            txt = f.read()
        m = re.search(r'(?:SavePath|DefaultSavePath)=([^\r\n]+)', txt, re.IGNORECASE)
        return m.group(1).strip() if m else ''
    except Exception:
        return ''


def get_download_roots():
    roots = {}

    def add_root(p):
        if not p or not str(p).strip():
            return
        ap = os.path.abspath(str(p).strip())
        if os.path.isdir(ap):
            nk = os.path.normcase(ap)
            if nk not in roots:
                roots[nk] = ap

    add_root(_read_qb_default_save_path())
    for t in get_all_torrents(use_cache=True).values():
        add_root(t.get('save_path'))

    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    for t in live.values():
        add_root(t.get('save_path'))

    sorted_paths = sorted(roots.values(), key=lambda x: len(os.path.normpath(x)))
    top_roots = []
    for p in sorted_paths:
        np = _norm(p)
        if not any(os.path.commonpath([_norm(r), np]) == _norm(r) for r in top_roots):
            top_roots.append(p)
    return top_roots


def _collect_active_paths():
    active = set()
    parsed = get_all_torrents(use_cache=True)
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}

    for t in parsed.values():
        sp = str(t.get('save_path') or '').strip()
        nm = str(t.get('name') or '').strip()
        if sp:
            active.add(_norm(sp))
            if nm:
                active.add(_norm(os.path.join(sp, nm)))

    for t in live.values():
        sp = str(t.get('save_path') or '').strip()
        cp = str(t.get('content_path') or '').strip()
        nm = str(t.get('name') or '').strip()
        if sp:
            active.add(_norm(sp))
        if cp:
            active.add(_norm(cp))
        if sp and nm:
            active.add(_norm(os.path.join(sp, nm)))

    return active


def _entry_size(path):
    if os.path.isfile(path) or os.path.islink(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, _, files in os.walk(path, followlinks=False):
        for fname in files:
            try:
                total += os.path.getsize(os.path.join(root, fname))
            except OSError:
                pass
    return total


def _is_path_protected(entry_norm, active_paths):
    for ap in active_paths:
        try:
            common = os.path.commonpath([entry_norm, ap])
            if common == entry_norm or common == ap:
                return True
        except ValueError:
            continue
    return False


def scan_orphan_entries(custom_roots=None):
    valid_roots = get_download_roots()
    roots = [os.path.abspath(str(r).strip()) for r in custom_roots if r and os.path.isdir(str(r).strip())] if custom_roots else valid_roots
    active_paths = _collect_active_paths()
    orphans, total_bytes = [], 0

    for root_dir in roots:
        try:
            with os.scandir(root_dir) as it:
                for ent in it:
                    if ent.name.startswith('.') or ent.name in ('$RECYCLE.BIN', 'System Volume Information', '_tbr_trash'):
                        continue
                    ent_abs = os.path.abspath(ent.path)
                    if _is_path_protected(_norm(ent_abs), active_paths):
                        continue
                    sz = _entry_size(ent_abs)
                    try:
                        mtime = ent.stat().st_mtime
                    except OSError:
                        mtime = 0
                    total_bytes += sz
                    orphans.append({
                        'path': ent_abs, 'name': ent.name, 'root': root_dir,
                        'is_dir': ent.is_dir(follow_symlinks=False), 'size': sz,
                        'size_fmt': format_file_size(sz), 'mtime': int(mtime),
                        'date': datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M') if mtime else '—'
                    })
        except Exception as e:
            write_error_log(f"scan_orphan_entries {root_dir}", e)

    orphans.sort(key=lambda x: x['size'], reverse=True)
    return {'roots': roots, 'orphans': orphans, 'count': len(orphans), 'total_size': total_bytes, 'total_size_fmt': format_file_size(total_bytes)}


def delete_orphan_entries(paths, actor='admin', use_trash=True):
    allowed_roots = [_norm(r) for r in get_download_roots()]
    active_paths = _collect_active_paths()
    deleted, errors = [], []

    for raw_p in paths:
        if not raw_p or not isinstance(raw_p, str):
            continue
        target_abs = os.path.abspath(raw_p.strip())
        target_norm = _norm(target_abs)

        inside_allowed = False
        for r_norm in allowed_roots:
            try:
                if os.path.commonpath([r_norm, target_norm]) == r_norm and target_norm != r_norm:
                    inside_allowed = True
                    break
            except ValueError:
                continue

        if not inside_allowed:
            errors.append(f"Отклонено (вне корневых папок загрузок): {raw_p}")
            continue
        if _is_path_protected(target_norm, active_paths):
            errors.append(f"Отклонено (путь используется активным торрентом): {raw_p}")
            continue

        try:
            if use_trash:
                ok, res = move_to_trash(target_abs, name=os.path.basename(target_abs), actor=actor)
                if not ok:
                    errors.append(f"Ошибка корзины {os.path.basename(target_abs)}: {res}")
                    continue
            else:
                if os.path.isdir(target_abs) and not os.path.islink(target_abs):
                    shutil.rmtree(target_abs)
                elif os.path.exists(target_abs) or os.path.islink(target_abs):
                    os.remove(target_abs)
                else:
                    errors.append(f"Не найдено: {raw_p}")
                    continue
            deleted.append(target_abs)
        except Exception as e:
            errors.append(f"Ошибка удаления {os.path.basename(target_abs)}: {e}")

    if deleted:
        act = 'В корзину _tbr_trash' if use_trash else 'Удаление сирот навсегда'
        app_state_db.add_audit_event('system', act, f'Объектов: {len(deleted)}', actor=actor)
    return len(errors) == 0, deleted, errors