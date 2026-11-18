# web/routes/torrents_bp.py
import time
import urllib.parse
from flask import Blueprint, request, jsonify

from utils.config import cfg
from utils.helpers import format_file_size
from core.torrent_parser import get_all_torrents, force_clear_cache
from core.qb_api import (
    detect_qbittorrent_port, get_live_torrent_info, send_qb_command,
    add_torrent_tags, remove_torrent_tags,
    is_qb_running, close_qbittorrent, launch_qbittorrent, scan_dead_torrents
)
from core.autostart import set_autostart, is_autostart_enabled
from core.fastresume_merger import run_fastresume_merge, execute_source_deletion, VALID_DELETE_MODES
from web.security import HASH_RE

torrents_bp = Blueprint('torrents_bp', __name__)


@torrents_bp.route('/api/qb/status')
def api_qb_status():
    running = is_qb_running()
    ip, port = detect_qbittorrent_port(cfg.config)
    return jsonify({'running': running, 'ip': ip, 'port': port})


@torrents_bp.route('/api/qb/start', methods=['POST'])
def api_qb_start():
    ok = launch_qbittorrent()
    return jsonify({'success': ok, 'message': 'qBittorrent запущен' if ok else 'Не удалось запустить'})


@torrents_bp.route('/api/qb/stop', methods=['POST'])
def api_qb_stop():
    ok = close_qbittorrent()
    return jsonify({'success': ok, 'message': 'qBittorrent остановлен' if ok else 'Не удалось остановить'})


@torrents_bp.route('/api/qb/restart', methods=['POST'])
def api_qb_restart():
    close_qbittorrent()
    time.sleep(1.5)
    ok = launch_qbittorrent()
    return jsonify({'success': ok, 'message': 'qBittorrent перезапущен'})


@torrents_bp.route('/api/autostart/status')
def api_autostart_status():
    return jsonify({'enabled': is_autostart_enabled()})


@torrents_bp.route('/api/autostart/toggle', methods=['POST'])
def api_autostart_toggle():
    curr = is_autostart_enabled()
    ok, msg = set_autostart(not curr)
    return jsonify({'success': ok, 'enabled': not curr if ok else curr, 'message': msg})


@torrents_bp.route('/api/torrents')
def api_torrents():
    ip, port = detect_qbittorrent_port(cfg.config)
    data_dict = get_all_torrents(use_cache=True)
    live_info = get_live_torrent_info(ip, port) if port else {}

    result = []
    for t_id, static in data_dict.items():
        live = live_info.get(t_id, {})
        size = live.get('total_size', static.get('size', 1))
        uploaded = live.get('uploaded', static.get('uploaded', 0))
        ratio = round(uploaded / size, 4) if size > 0 else 0.0
        state = live.get('state', 'seeding' if static.get('active_seconds', 0) > 0 else 'unknown')
        save_path = live.get('save_path', static.get('save_path', ''))
        tags = str(live.get('tags', '') or '')

        # Домен трекера для фильтрации
        tracker_host = ''
        tr_url = str(live.get('tracker', '') or '')
        if not tr_url and static.get('trackers'):
            tr_url = str(static['trackers'][0] or '')
        if tr_url:
            tracker_host = urllib.parse.urlparse(tr_url).netloc.lower()

        name = static.get('name', '')
        if not name or name.lower() == t_id.lower() or len(name) in (40, 64):
            if live.get('name'):
                name = live['name']
        if not name:
            name = t_id

        result.append({
            'hash': t_id, 'name': name, 'size': size, 'size_fmt': format_file_size(size),
            'uploaded': uploaded, 'uploaded_fmt': format_file_size(uploaded),
            'ratio': ratio, 'state': state, 'save_path': save_path,
            'tags': tags, 'tracker': tracker_host,
            'active_seconds': static.get('active_seconds', 0)
        })
    result.sort(key=lambda x: str(x['name']).lower())
    return jsonify({'torrents': result, 'qb_connected': bool(port), 'qb_running': is_qb_running()})


@torrents_bp.route('/api/torrents/refresh', methods=['POST'])
def api_torrents_refresh():
    force_clear_cache()
    return jsonify({'status': 'ok'})


@torrents_bp.route('/api/torrents/scan_dead', methods=['POST'])
def api_torrents_scan_dead():
    ip, port = detect_qbittorrent_port(cfg.config)
    if not port:
        return jsonify({'success': False, 'error': 'qBittorrent недоступен'}), 400
    res = scan_dead_torrents(ip, port)
    if res.get('success'):
        for item in res.get('items', []):
            item['size_fmt'] = format_file_size(item.get('size', 0))
    return jsonify(res)


@torrents_bp.route('/api/torrents/action', methods=['POST'])
def api_torrent_action():
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    t_hash = data.get('hash', '')
    tag = str(data.get('tag', '')).strip()
    if action not in ('stop', 'start', 'setForceStart', 'addTags', 'removeTags'):
        return jsonify({'success': False, 'error': 'Неизвестная команда'}), 400

    hashes = [h.strip() for h in str(t_hash).split('|') if h.strip()]
    if not hashes or not all(HASH_RE.fullmatch(h) for h in hashes):
        return jsonify({'success': False, 'error': 'Некорректные хэши'}), 400

    ip, port = detect_qbittorrent_port(cfg.config)
    if not port:
        return jsonify({'success': False, 'error': 'qBittorrent недоступен'}), 400

    joined = '|'.join(hashes)
    if action == 'addTags':
        return jsonify({'success': add_torrent_tags(ip, port, joined, tag)})
    if action == 'removeTags':
        return jsonify({'success': remove_torrent_tags(ip, port, joined, tag)})
    return jsonify({'success': send_qb_command(ip, port, action, joined)})


@torrents_bp.route('/api/torrents/action_all', methods=['POST'])
def api_torrents_action_all():
    data = request.get_json(silent=True) or {}
    action = data.get('action', 'stop')
    if action not in ('stop', 'start'):
        return jsonify({'success': False, 'error': 'Неизвестная команда'}), 400
    ip, port = detect_qbittorrent_port(cfg.config)
    if not port:
        return jsonify({'success': False, 'error': 'qBittorrent не запущен'}), 400
    ok = send_qb_command(ip, port, action, 'all')
    msg = "Все раздачи поставлены на паузу" if action == 'stop' else "Все раздачи возобновлены"
    return jsonify({'success': ok, 'message': msg})


@torrents_bp.route('/api/merger/run', methods=['POST'])
def api_merger_run():
    data = request.get_json(silent=True) or {}
    old_hash = str(data.get('old_hash', '')).strip()
    new_hash = str(data.get('new_hash', '')).strip()
    delete_mode = str(data.get('delete_mode', 'none')).strip()
    if delete_mode not in VALID_DELETE_MODES:
        delete_mode = 'none'

    if not HASH_RE.fullmatch(old_hash) or not HASH_RE.fullmatch(new_hash) or old_hash.lower() == new_hash.lower():
        return jsonify({'success': False, 'log': ['❌ Некорректные или одинаковые хэши торрентов!']}), 400

    ok, log, confirm_info, code = run_fastresume_merge(old_hash, new_hash, delete_mode=delete_mode)
    return jsonify({'success': ok, 'log': log, 'needs_delete_confirm': bool(ok and confirm_info), 'confirm_info': confirm_info}), code


@torrents_bp.route('/api/merger/delete_source', methods=['POST'])
def api_merger_delete_source():
    data = request.get_json(silent=True) or {}
    old_hash, new_hash = str(data.get('old_hash', '')).strip(), str(data.get('new_hash', '')).strip()
    delete_mode, confirmed = str(data.get('delete_mode', '')).strip(), bool(data.get('confirmed', False))

    if not confirmed or delete_mode not in ('safe', 'force'):
        return jsonify({'success': False, 'log': ['❌ Удаление не подтверждено!']}), 400
    if not HASH_RE.fullmatch(old_hash) or not HASH_RE.fullmatch(new_hash) or old_hash.lower() == new_hash.lower():
        return jsonify({'success': False, 'log': ['❌ Некорректные или одинаковые хэши!']}), 400

    ok, log = execute_source_deletion(old_hash, new_hash, delete_mode)
    return jsonify({'success': ok, 'log': log}), (200 if ok else 400)