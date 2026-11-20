# web/routes/hardcore_bp.py
from flask import Blueprint, request, jsonify, g
from utils.config import cfg
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info
from core.private_vault import get_hidden_hashes
from core.hdd_smart_queue import enqueue_recheck, list_recheck_queue, tick_recheck_queue, get_smart_disks_status
from core.rss_dedup import check_rss_duplicates
from core.mediainfo_lite import inspect_torrent_media
from web.security import HASH_RE

hardcore_bp = Blueprint('hardcore_bp', __name__)


@hardcore_bp.route('/api/hdd/smart')
def api_hdd_smart():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    return jsonify(get_smart_disks_status())


@hardcore_bp.route('/api/recheck_queue', methods=['GET', 'POST'])
def api_recheck_queue():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    if request.method == 'POST':
        h = str((request.get_json(silent=True) or {}).get('hash', '')).strip()
        if not HASH_RE.fullmatch(h):
            return jsonify({'success': False, 'error': 'Некорректный хэш'}), 400
        info = live.get(h) or {}
        enqueue_recheck(h, save_path=info.get('save_path', ''), name=info.get('name', h))
        tick_recheck_queue(ip, port, live)
    return jsonify({'queue': list_recheck_queue()})


@hardcore_bp.route('/api/rss/dedup')
def api_rss_dedup():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    return jsonify(check_rss_duplicates())


@hardcore_bp.route('/api/torrents/mediainfo')
def api_torrents_mediainfo():
    h = str(request.args.get('hash', '')).strip()
    if not HASH_RE.fullmatch(h):
        return jsonify({'success': False, 'error': 'Некорректный хэш'}), 400
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    if g.get('role') != 'admin' and h.lower() in get_hidden_hashes(live):
        return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403
    info = live.get(h) or {}
    return jsonify(inspect_torrent_media(info.get('content_path') or info.get('save_path') or ''))