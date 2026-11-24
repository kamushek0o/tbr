# core/qb_actions.py
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.qb_api import (
    _post_qb_api, _post_qb_api_code, check_qb_api_alive,
    get_live_torrent_info, get_torrent_trackers
)


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
        payload['stopped'] = 'true'
    return _post_qb_api(qb_ip, qb_port, 'torrents/add', payload)


def set_global_speed_limits(qb_ip, qb_port, dl_limit_bps, up_limit_bps):
    return _post_qb_api(qb_ip, qb_port, 'transfer/setDownloadLimit', {'limit': str(max(0, int(dl_limit_bps)))}) and \
           _post_qb_api(qb_ip, qb_port, 'transfer/setUploadLimit', {'limit': str(max(0, int(up_limit_bps)))})


def set_qb_preferences(qb_ip, qb_port, prefs_dict):
    if not isinstance(prefs_dict, dict) or not prefs_dict:
        return False
    return _post_qb_api(qb_ip, qb_port, 'app/setPreferences', {'json': json.dumps(prefs_dict)})


def shutdown_qb_webui(qb_ip, qb_port):
    return _post_qb_api(qb_ip, qb_port, 'app/shutdown', {})


def send_qb_command(qb_ip, qb_port, action, hash_val):
    if not hash_val:
        return False
    payload = {'hashes': hash_val}
    if action == 'setForceStart':
        payload['value'] = 'true'
    code = _post_qb_api_code(qb_ip, qb_port, f'torrents/{action}', payload)
    if 200 <= code < 300:
        return True
    if code == 404 and action in ('stop', 'start'):
        legacy = 'pause' if action == 'stop' else 'resume'
        return _post_qb_api(qb_ip, qb_port, f'torrents/{legacy}', payload)
    return False