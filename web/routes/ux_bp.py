# web/routes/ux_bp.py
from flask import Blueprint, request, jsonify, g
from utils.config import cfg
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info, set_torrent_file_prio
from core.torrent_parser import get_global_torrent_summaries
from core.private_vault import get_hidden_hashes
from core.lineage_notes_events import (
    get_torrent_timeline, get_torrent_note, set_torrent_note,
    list_all_notes, get_activity_feed, resolve_uid
)
from core.file_fts_index import reindex_torrent_files, search_files_fts, build_treemap_data, get_torrent_files_paginated
from web.security import HASH_RE

ux_bp = Blueprint('ux_bp', __name__)
_VALID_FILE_PRIOS = {0, 1, 6, 7}


def _hidden_for_role():
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    hidden = get_hidden_hashes(live)
    return ip, port, live, (hidden if g.get('role') != 'admin' else set())


def _find_live_ci(live, t_hash):
    hl = str(t_hash or '').lower()
    return next((v for k, v in (live or {}).items() if k.lower() == hl), {})


@ux_bp.route('/api/torrent/timeline')
def api_torrent_timeline():
    h = str(request.args.get('hash', '')).strip()
    if not HASH_RE.fullmatch(h):
        return jsonify({'events': []}), 400
    _, _, _, hidden = _hidden_for_role()
    if h.lower() in hidden:
        return jsonify({'events': []}), 403
    return jsonify({'events': get_torrent_timeline(h)})


@ux_bp.route('/api/torrent/notes', methods=['GET', 'POST'])
def api_torrent_notes():
    h = str(request.args.get('hash', '') or (request.get_json(silent=True) or {}).get('hash', '')).strip()
    if not HASH_RE.fullmatch(h):
        return jsonify({'success': False, 'error': 'Некорректный хэш'}), 400
    _, _, live, hidden = _hidden_for_role()
    if h.lower() in hidden:
        return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403
    if request.method == 'GET':
        return jsonify({'note': get_torrent_note(h)})
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    d = request.get_json(silent=True) or {}
    nm = _find_live_ci(live, h).get('name', '')
    ok = set_torrent_note(h, d.get('note', ''), last_name=nm)
    return jsonify({'success': ok})


@ux_bp.route('/api/notes/all')
def api_notes_all():
    _, _, _, hidden = _hidden_for_role()
    hidden_uids = {resolve_uid(h) for h in hidden}
    return jsonify({'notes': list_all_notes(hidden_uids=hidden_uids)})


@ux_bp.route('/api/activity/ticker')
def api_activity_ticker():
    _, _, _, hidden = _hidden_for_role()
    return jsonify({'events': get_activity_feed(hidden_hashes=hidden)})


@ux_bp.route('/api/search/reindex', methods=['POST'])
def api_search_reindex():
    if g.get('role') != 'admin':
        return jsonify({'success': False}), 403
    force = bool((request.get_json(silent=True) or {}).get('force', False))
    return jsonify(reindex_torrent_files(force=force))


@ux_bp.route('/api/search/files')
def api_search_files():
    q = request.args.get('q', '')
    _, _, _, hidden = _hidden_for_role()
    return jsonify({'items': search_files_fts(q, limit=25, hidden_hashes=hidden)})


@ux_bp.route('/api/analytics/treemap')
def api_analytics_treemap():
    group_by = request.args.get('group_by', 'tags')
    _, _, live, hidden = _hidden_for_role()
    return jsonify({'items': build_treemap_data(get_global_torrent_summaries(), live, group_by=group_by, hidden_hashes=hidden)})


@ux_bp.route('/api/torrents/files')
def api_torrents_files():
    h = str(request.args.get('hash', '')).strip()
    if not HASH_RE.fullmatch(h):
        return jsonify({'files': []}), 400
    ip, port, _, hidden = _hidden_for_role()
    if h.lower() in hidden:
        return jsonify({'files': []}), 403
    page = request.args.get('page', 1, type=int)
    return jsonify(get_torrent_files_paginated(ip, port, h, page=page, per_page=100))


@ux_bp.route('/api/torrents/file_prio', methods=['POST'])
def api_torrents_file_prio():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    d = request.get_json(silent=True) or {}
    h = str(d.get('hash', '')).strip()
    if not HASH_RE.fullmatch(h):
        return jsonify({'success': False, 'error': 'Некорректный хэш'}), 400
    try:
        fid = int(d.get('id', 0))
        prio = int(d.get('priority', 1))
        if fid < 0 or prio not in _VALID_FILE_PRIOS:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Некорректные id или priority'}), 400
    ip, port = detect_qbittorrent_port(cfg.config)
    ok = set_torrent_file_prio(ip, port, h, fid, prio)
    return jsonify({'success': ok})