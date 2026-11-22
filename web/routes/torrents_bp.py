# web/routes/torrents_bp.py
import time
import urllib.parse
from flask import Blueprint, request, jsonify, g

from utils.config import cfg
from utils.helpers import format_file_size
from core.torrent_parser import get_all_torrents, force_clear_cache
from core.qb_api import (
    detect_qbittorrent_port, get_live_torrent_info, send_qb_command,
    add_torrent_tags, remove_torrent_tags, delete_torrents,
    is_qb_running, close_qbittorrent, launch_qbittorrent, scan_dead_torrents
)
from core.autostart import set_autostart, is_autostart_enabled
from core.fastresume_merger import (
    run_fastresume_merge, execute_source_deletion,
    VALID_DELETE_MODES, VALID_MERGE_MODES
)
from core.torrent_diff import compute_torrent_diff, find_smart_merge_candidates
from core.private_vault import get_hidden_hashes, filter_torrents_for_role
from core.torrent_targets import list_targets
from core.health_score import enrich_live_metrics
from core.tracker_inspector import inspect_tracker_errors
from core.app_state_db import app_state_db
from core.tracker_replacer import push_undo_record
from core.lineage_notes_events import record_torrent_event, push_activity
from web.security import HASH_RE

torrents_bp = Blueprint('torrents_bp', __name__)


def _build_torrents_list(ip, port):
    data_dict = get_all_torrents(use_cache=True)
    live_info = get_live_torrent_info(ip, port) if port else {}
    targets = list_targets()

    result = []
    for t_id, static in data_dict.items():
        live = live_info.get(t_id) or live_info.get(t_id.lower()) or live_info.get(t_id.upper()) or {}
        size = live.get('total_size', static.get('size', 1))
        uploaded = live.get('uploaded', static.get('uploaded', 0))
        ratio = round(uploaded / size, 4) if size > 0 else 0.0
        state = live.get('state', 'seeding' if static.get('active_seconds', 0) > 0 else 'unknown')
        save_path = live.get('save_path', static.get('save_path', ''))
        content_path = live.get('content_path', '')
        tags = str(live.get('tags', '') or '')
        added_on = int(live.get('added_on') or static.get('created_ts') or 0)

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

        item = {
            'hash': t_id, 'name': name, 'size': size, 'size_fmt': format_file_size(size),
            'uploaded': uploaded, 'uploaded_fmt': format_file_size(uploaded),
            'ratio': ratio, 'state': state, 'save_path': save_path, 'content_path': content_path,
            'tags': tags, 'tracker': tracker_host, 'added_on': added_on,
            'active_seconds': static.get('active_seconds', 0)
        }
        enrich_live_metrics(item, live, targets.get(t_id.lower()))
        result.append(item)
    result.sort(key=lambda x: str(x['name']).lower())
    return result, live_info


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
    result, live_info = _build_torrents_list(ip, port)
    role = g.get('role') or 'viewer'
    hidden = get_hidden_hashes(live_info)
    result = filter_torrents_for_role(result, role, hidden)
    return jsonify({'torrents': result, 'qb_connected': bool(port), 'qb_running': is_qb_running()})


@torrents_bp.route('/api/torrents/tracker_errors')
def api_torrents_tracker_errors():
    ip, port = detect_qbittorrent_port(cfg.config)
    live_info = get_live_torrent_info(ip, port) if port else {}
    force = request.args.get('force', '0') == '1'
    err_map = inspect_tracker_errors(ip, port, live_info, force=force)
    if g.get('role') != 'admin':
        hidden = get_hidden_hashes(live_info)
        if hidden:
            err_map = {k: v for k, v in err_map.items() if k not in hidden}
    return jsonify({'errors': err_map})


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
    if action in ('addTags', 'removeTags'):
        ok = add_torrent_tags(ip, port, joined, tag) if action == 'addTags' else remove_torrent_tags(ip, port, joined, tag)
        if ok:
            lbl = f"{'+Тег' if action == 'addTags' else '-Тег'} '{tag}' ({len(hashes)} шт.)"
            push_undo_record('tags_bulk', lbl, {'action': action, 'hashes': joined, 'tag': tag})
            if len(hashes) == 1:
                record_torrent_event(hashes[0], 'tag', lbl)
            else:
                push_activity('tag', lbl)
        return jsonify({'success': ok})

    ok = send_qb_command(ip, port, action, joined)
    if ok:
        if action in ('stop', 'start'):
            lbl = f"{'Пауза' if action == 'stop' else 'Пуск'} ({len(hashes)} шт.)"
            if len(hashes) > 1:
                push_undo_record('pause_start_bulk', lbl, {'action': action, 'hashes': joined})
                push_activity('control', lbl)
            else:
                record_torrent_event(hashes[0], 'control', 'Поставлено на паузу' if action == 'stop' else 'Возобновлено')
        elif action == 'setForceStart' and len(hashes) == 1:
            record_torrent_event(hashes[0], 'control', 'Включён форсированный старт')
    return jsonify({'success': ok})


@torrents_bp.route('/api/torrents/delete', methods=['POST'])
def api_torrents_delete():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    data = request.get_json(silent=True) or {}
    t_hash = str(data.get('hash', '')).strip()
    delete_files = bool(data.get('delete_files', False))
    hashes = [h.strip() for h in t_hash.split('|') if h.strip()]
    if not hashes or not all(HASH_RE.fullmatch(h) for h in hashes):
        return jsonify({'success': False, 'error': 'Некорректные хэши'}), 400
    ip, port = detect_qbittorrent_port(cfg.config)
    if not port:
        return jsonify({'success': False, 'error': 'qBittorrent недоступен'}), 400
    ok = delete_torrents(ip, port, '|'.join(hashes), delete_files=delete_files)
    if ok:
        force_clear_cache()
        app_state_db.add_audit_event('system', 'Удаление торрента', f'count={len(hashes)}, files={delete_files}', actor='admin')
        push_activity('delete', f"Удалено раздач: {len(hashes)} (файлы={delete_files})", t_hash=hashes[0] if len(hashes) == 1 else '')
    return jsonify({'success': ok})


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
    if ok:
        push_activity('control', msg)
    return jsonify({'success': ok, 'message': msg})


@torrents_bp.route('/api/merger/diff')
def api_merger_diff():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    old_hash = str(request.args.get('old_hash', '')).strip()
    new_hash = str(request.args.get('new_hash', '')).strip()
    if not HASH_RE.fullmatch(old_hash) or not HASH_RE.fullmatch(new_hash) or old_hash.lower() == new_hash.lower():
        return jsonify({'success': False, 'error': 'Укажите два разных корректных хэша'}), 400
    ip, port = detect_qbittorrent_port(cfg.config)
    return jsonify(compute_torrent_diff(ip, port, old_hash, new_hash))


@torrents_bp.route('/api/merger/candidates')
def api_merger_candidates():
    if g.get('role') != 'admin':
        return jsonify({'candidates': []}), 403
    ip, port = detect_qbittorrent_port(cfg.config)
    items, _ = _build_torrents_list(ip, port)
    return jsonify({'candidates': find_smart_merge_candidates(items)})


@torrents_bp.route('/api/merger/check_pair')
def api_merger_check_pair():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    old_h = str(request.args.get('old_hash', '')).strip().lower()
    new_h = str(request.args.get('new_hash', '')).strip().lower()
    if not HASH_RE.fullmatch(old_h) or not HASH_RE.fullmatch(new_h) or old_h == new_h:
        return jsonify({'has_history': False})
    hist = app_state_db.get_merger_history(old_h, new_h)
    return jsonify({
        'has_history': len(hist) > 0,
        'count': len(hist),
        'last_merged_at': hist[0]['created_at'] if hist else None
    })


@torrents_bp.route('/api/merger/run', methods=['POST'])
def api_merger_run():
    data = request.get_json(silent=True) or {}
    old_hash = str(data.get('old_hash', '')).strip()
    new_hash = str(data.get('new_hash', '')).strip()
    delete_mode = str(data.get('delete_mode', 'none')).strip()
    merge_mode = str(data.get('merge_mode', 'add')).strip()
    force_dup = bool(data.get('force_duplicate', False))

    if delete_mode not in VALID_DELETE_MODES:
        delete_mode = 'none'
    if merge_mode not in VALID_MERGE_MODES:
        merge_mode = 'add'

    if not HASH_RE.fullmatch(old_hash) or not HASH_RE.fullmatch(new_hash) or old_hash.lower() == new_hash.lower():
        return jsonify({'success': False, 'log': ['❌ Некорректные или одинаковые хэши торрентов!']}), 400

    ok, log, confirm_info, code, extra = run_fastresume_merge(
        old_hash, new_hash, delete_mode=delete_mode, merge_mode=merge_mode, force_duplicate=force_dup
    )

    if code == 409 and extra and extra.get('is_duplicate'):
        return jsonify({
            'success': False,
            'needs_duplicate_confirm': True,
            'warning': extra.get('warning'),
            'log': log
        }), 409

    if ok:
        app_state_db.add_audit_event(
            'merger', f'Перенос .fastresume ({merge_mode})',
            f'{old_hash[:8]} -> {new_hash[:8]} (del={delete_mode})', actor='admin'
        )

    return jsonify({
        'success': ok, 'log': log, 'needs_delete_confirm': bool(ok and confirm_info),
        'confirm_info': confirm_info, 'calc_info': extra
    }), code


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
    if ok:
        app_state_db.add_audit_event('merger', 'Удалён исходник', f'{old_hash[:8]} (mode={delete_mode})', actor='admin')
    return jsonify({'success': ok, 'log': log}), (200 if ok else 400)