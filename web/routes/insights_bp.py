# web/routes/insights_bp.py
from flask import Blueprint, request, jsonify, g
from utils.config import cfg
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info
from core.torrent_parser import get_global_torrent_summaries
from core.summary_tracker import summary_tracker
from core.private_vault import get_hidden_hashes
from core.analytics_insights import (
    fetch_torrent_peers_safe, get_peer_clients_breakdown,
    get_tracker_analytics, get_heatmap_365,
    get_records_and_comparisons, detect_isp_throttling
)
from web.security import HASH_RE

insights_bp = Blueprint('insights_bp', __name__)


@insights_bp.route('/api/torrents/peers')
def api_torrents_peers():
    t_hash = str(request.args.get('hash', '')).strip()
    if not HASH_RE.fullmatch(t_hash):
        return jsonify({'success': False, 'error': 'Некорректный хэш'}), 400

    ip, port = detect_qbittorrent_port(cfg.config)
    if g.get('role') != 'admin' and port:
        live = get_live_torrent_info(ip, port)
        if t_hash.lower() in get_hidden_hashes(live):
            return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403

    peers = fetch_torrent_peers_safe(ip, port, t_hash)
    return jsonify({'success': True, 'peers': peers})


@insights_bp.route('/api/torrents/chart')
def api_torrents_chart():
    t_hash = str(request.args.get('hash', '')).strip()
    period = str(request.args.get('period', '24h')).strip()
    if period not in ('24h', '7d', '30d'):
        period = '24h'
    if not HASH_RE.fullmatch(t_hash):
        return jsonify({'success': False, 'error': 'Некорректный хэш'}), 400

    if g.get('role') != 'admin':
        ip, port = detect_qbittorrent_port(cfg.config)
        live = get_live_torrent_info(ip, port) if port else {}
        if t_hash.lower() in get_hidden_hashes(live):
            return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403

    pts = summary_tracker.get_torrent_chart_series(t_hash, period=period)
    return jsonify({'success': True, 'period': period, 'points': pts})


@insights_bp.route('/api/analytics/recalculate_records', methods=['POST'])
def api_recalculate_records():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    heatmap = get_heatmap_365(summary_tracker.db)
    records = get_records_and_comparisons(summary_tracker.db, heatmap_cells=heatmap, force_recalc=True)
    return jsonify({'success': True, 'records': records})


@insights_bp.route('/api/analytics/insights')
def api_analytics_insights():
    tracker_period = str(request.args.get('tracker_period', '7d')).strip()
    force_clients = request.args.get('force_clients', '0') == '1'

    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    summaries = get_global_torrent_summaries()

    allowed_hashes = None
    if g.get('role') != 'admin':
        hidden = get_hidden_hashes(live)
        if hidden:
            allowed_hashes = [
                (s.get('hash_id') or s.get('hash') or '').lower()
                for s in summaries
                if (s.get('hash_id') or s.get('hash') or '').lower() not in hidden
            ]

    heatmap = get_heatmap_365(summary_tracker.db)
    records = get_records_and_comparisons(summary_tracker.db, heatmap_cells=heatmap)
    clients = get_peer_clients_breakdown(ip, port, live, force=force_clients)
    trackers = get_tracker_analytics(summary_tracker.db, summaries, live=live, period=tracker_period, allowed_hashes=allowed_hashes)
    throttle = detect_isp_throttling(summary_tracker.db, ip, port)

    return jsonify({
        'heatmap': heatmap,
        'records': records,
        'clients': clients,
        'trackers': trackers,
        'throttle': throttle
    })