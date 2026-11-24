# web/routes/merger_bp.py
from flask import Blueprint, request, jsonify, g
from utils.config import cfg
from core.qb_api import detect_qbittorrent_port
from core.fastresume_merger import (
    run_fastresume_merge, execute_source_deletion,
    VALID_DELETE_MODES, VALID_MERGE_MODES
)
from core.torrent_diff import compute_torrent_diff, find_smart_merge_candidates
from core.app_state_db import app_state_db
from web.routes.torrents_bp import _build_torrents_list
from web.security import HASH_RE

merger_bp = Blueprint('merger_bp', __name__)


@merger_bp.route('/api/merger/diff')
def api_merger_diff():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    old_hash = str(request.args.get('old_hash', '')).strip()
    new_hash = str(request.args.get('new_hash', '')).strip()
    if not HASH_RE.fullmatch(old_hash) or not HASH_RE.fullmatch(new_hash) or old_hash.lower() == new_hash.lower():
        return jsonify({'success': False, 'error': 'Укажите два разных корректных хэша'}), 400
    ip, port = detect_qbittorrent_port(cfg.config)
    return jsonify(compute_torrent_diff(ip, port, old_hash, new_hash))


@merger_bp.route('/api/merger/candidates')
def api_merger_candidates():
    if g.get('role') != 'admin':
        return jsonify({'candidates': []}), 403
    ip, port = detect_qbittorrent_port(cfg.config)
    items, _ = _build_torrents_list(ip, port)
    return jsonify({'candidates': find_smart_merge_candidates(items)})


@merger_bp.route('/api/merger/check_pair')
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


@merger_bp.route('/api/merger/run', methods=['POST'])
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


@merger_bp.route('/api/merger/delete_source', methods=['POST'])
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