# core/torrent_parser.py
import os
import time
import shutil
import datetime
import threading
from utils.bencode import decode_bencode
from utils.helpers import BT_BACKUP_PATH, write_error_log

_LOCK = threading.Lock()
# { hash_id: {'sig': (mtime_ns, size), 'data': dict} }
_FILE_CACHE = {}


def force_clear_cache():
    with _LOCK:
        _FILE_CACHE.clear()


def _extract_str(val):
    if val is None:
        return ""
    if isinstance(val, bytes):
        try:
            return val.decode('utf-8')
        except UnicodeDecodeError:
            try:
                return val.decode('cp1251')
            except Exception:
                return val.decode('latin1', errors='ignore')
    return str(val).strip()


def _get_field(data, *keys):
    if not isinstance(data, dict):
        return None
    for k in keys:
        if k in data and data[k] is not None:
            return data[k]
        if isinstance(k, str):
            kb = k.encode('ascii', errors='ignore')
            if kb in data and data[kb] is not None:
                return data[kb]
    return None


def parse_single_torrent(fastresume_path, tor_map=None):
    t_hash = os.path.splitext(os.path.basename(fastresume_path))[0].lower()
    base_dir = os.path.dirname(fastresume_path)

    with open(fastresume_path, 'rb') as f:
        fr_data = decode_bencode(f.read())
    if not isinstance(fr_data, dict):
        raise ValueError(f"Битый или неполный fastresume: {t_hash}")

    tor_data = {}
    tor_path = (tor_map or {}).get(t_hash) or os.path.join(base_dir, t_hash + '.torrent')
    if os.path.exists(tor_path):
        try:
            with open(tor_path, 'rb') as f:
                tor_data = decode_bencode(f.read()) or {}
        except Exception as e:
            write_error_log(f"decode torrent {t_hash}", e)

    info_dict = _get_field(tor_data, 'info') or {}

    name = ""
    tor_name = _extract_str(_get_field(info_dict, 'name.utf-8', 'name'))
    if tor_name and tor_name.lower() != t_hash:
        name = tor_name
    if not name:
        qbt_name = _extract_str(_get_field(fr_data, 'qBt-name'))
        if qbt_name and qbt_name.lower() != t_hash:
            name = qbt_name
    if not name:
        fr_name = _extract_str(_get_field(fr_data, 'name'))
        if fr_name and fr_name.lower() != t_hash:
            name = fr_name

    save_path = _extract_str(_get_field(fr_data, 'save_path', 'qBt-savePath'))
    if not name and save_path:
        base_name = os.path.basename(os.path.normpath(save_path))
        if base_name and len(base_name) > 2 and base_name.lower() != t_hash:
            name = base_name
    if not name:
        name = t_hash

    size = 0
    if 'length' in info_dict or b'length' in info_dict:
        size = int(_get_field(info_dict, 'length') or 0)
    elif 'files' in info_dict or b'files' in info_dict:
        files = _get_field(info_dict, 'files') or []
        size = sum(int(_get_field(f, 'length') or 0) for f in files)
    if size <= 0:
        size = int(_get_field(fr_data, 'total_size', 'total_downloaded') or 1)

    uploaded = int(_get_field(fr_data, 'total_uploaded') or 0)
    active_seconds = int(_get_field(fr_data, 'active_time', 'seeding_time') or 0)

    added_time = _get_field(fr_data, 'added_time', 'completed_time', 'creation date')
    if added_time and int(added_time) > 0:
        created_ts = int(added_time)
        created_str = datetime.datetime.fromtimestamp(created_ts).strftime('%d.%m.%Y %H:%M')
    else:
        try:
            mtime = int(os.path.getmtime(fastresume_path))
            created_ts = mtime
            created_str = datetime.datetime.fromtimestamp(mtime).strftime('%d.%m.%Y %H:%M')
        except Exception:
            created_ts = 0
            created_str = "Дата неизвестна"

    trackers = []
    raw_trackers = _get_field(fr_data, 'trackers')
    if raw_trackers and isinstance(raw_trackers, list):
        for tr in raw_trackers:
            if isinstance(tr, list) and tr:
                trackers.append(_extract_str(tr[0]))
            elif isinstance(tr, (str, bytes)):
                trackers.append(_extract_str(tr))

    return {
        'name': name,
        'hash_id': t_hash,
        'size': size,
        'uploaded': uploaded,
        'ratio': round(uploaded / size, 2) if size > 0 else 0.0,
        'active_seconds': active_seconds,
        'save_path': save_path,
        'trackers': trackers,
        'created': created_str,
        'created_ts': created_ts,
        'info_hash': t_hash,
        'files': []
    }


def get_all_torrents(use_cache=True):
    if not os.path.exists(BT_BACKUP_PATH):
        return {}

    try:
        entries = list(os.scandir(BT_BACKUP_PATH))
    except Exception as e:
        write_error_log("scandir BT_backup", e)
        return {}

    tor_map = {}
    fr_entries = []
    for ent in entries:
        low = ent.name.lower()
        if low.endswith('.torrent'):
            tor_map[low[:-8]] = ent.path
        elif low.endswith('.fastresume'):
            fr_entries.append((low[:-11], ent))

    seen_hashes = set()
    result = {}

    with _LOCK:
        if not use_cache:
            _FILE_CACHE.clear()

        for t_hash, ent in fr_entries:
            seen_hashes.add(t_hash)
            try:
                st = ent.stat()
                sig = (st.st_mtime_ns, st.st_size)
            except OSError:
                continue

            cached = _FILE_CACHE.get(t_hash)
            if cached and cached['sig'] == sig:
                result[t_hash] = cached['data']
                continue

            try:
                item = parse_single_torrent(ent.path, tor_map=tor_map)
                _FILE_CACHE[t_hash] = {'sig': sig, 'data': item}
                result[t_hash] = item
            except Exception:
                # Файл в процессе перезаписи клиентом: сохраняем прошлое валидное значение или пропускаем тик
                if cached:
                    result[t_hash] = cached['data']

        # Авточистка «призраков» (файлы, исчезнувшие из BT_backup)
        ghosts = [h for h in _FILE_CACHE if h not in seen_hashes]
        for g in ghosts:
            del _FILE_CACHE[g]

    return result


def get_global_torrent_summaries():
    return list(get_all_torrents(use_cache=True).values())


def copy_torrent_to_watch(t_hash):
    if not os.path.exists(BT_BACKUP_PATH):
        return False, "Папка BT_backup не найдена"
    tor_path = os.path.join(BT_BACKUP_PATH, t_hash.lower() + '.torrent')
    if not os.path.exists(tor_path):
        for candidate in os.listdir(BT_BACKUP_PATH):
            if candidate.lower() == (t_hash.lower() + '.torrent'):
                tor_path = os.path.join(BT_BACKUP_PATH, candidate)
                break
    if not os.path.exists(tor_path):
        return False, f"Файл {t_hash}.torrent не найден"

    watch_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
    os.makedirs(watch_dir, exist_ok=True)
    try:
        dest = os.path.join(watch_dir, os.path.basename(tor_path))
        shutil.copy2(tor_path, dest)
        return True, f"Скопировано в {dest}"
    except Exception as e:
        return False, str(e)