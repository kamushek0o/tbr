# web/routes/deep_analytics_bp.py
from flask import Blueprint, request, jsonify, render_template, Response, g
from utils.config import cfg
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info
from core.torrent_parser import get_global_torrent_summaries
from core.summary_tracker import summary_tracker
from core.private_vault import get_hidden_hashes
from core.app_state_db import app_state_db
from core.deep_analytics import get_rhythm_7x24, get_day_hourly_breakdown, get_storage_runway, compare_periods_ab, get_monthly_quota_status
from core.swarm_analytics import get_tracker_survivability, get_protocol_efficiency, get_qb_slot_recommendations, find_normalized_title_groups
from core.wrapped_service import build_wrapped_summary, export_full_inventory

deep_analytics_bp = Blueprint('deep_analytics_bp', __name__)


def _live_and_hidden():
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    return ip, port, live, get_hidden_hashes(live)


@deep_analytics_bp.route('/kiosk')
def kiosk_view():
    """#35 Read-Only режим Киоск / Второй монитор."""
    return render_template('kiosk.html')


@deep_analytics_bp.route('/api/analytics/rhythm')
def api_rhythm():
    return jsonify(get_rhythm_7x24(summary_tracker.db))


@deep_analytics_bp.route('/api/analytics/day_hourly')
def api_day_hourly():
    return jsonify(get_day_hourly_breakdown(summary_tracker.db, request.args.get('date', '')))


@deep_analytics_bp.route('/api/analytics/runway')
def api_runway():
    _, _, live, _ = _live_and_hidden()
    return jsonify(get_storage_runway(live, get_global_torrent_summaries()))


@deep_analytics_bp.route('/api/analytics/ab_compare', methods=['POST'])
def api_ab_compare():
    d = request.get_json(silent=True) or {}
    return jsonify(compare_periods_ab(
        summary_tracker.db,
        d.get('start_a', ''), d.get('end_a', ''),
        d.get('start_b', ''), d.get('end_b', ''),
        same_n_days=bool(d.get('same_n_days', True))
    ))


@deep_analytics_bp.route('/api/analytics/quota', methods=['GET', 'POST'])
def api_quota():
    if request.method == 'POST':
        if g.get('role') != 'admin':
            return jsonify({'error': 'Только для Admin'}), 403
        d = request.get_json(silent=True) or {}
        if 'quota_tib' in d:
            cfg.set('Monthly_Quota_TiB', str(max(0.0, float(d['quota_tib'] or 0))))
        if 'reserve_gib' in d:
            cfg.set('Disk_Reserve_GiB', str(max(0, int(d['reserve_gib'] or 0))))
        cfg.save()
    return jsonify(get_monthly_quota_status(summary_tracker.db))


@deep_analytics_bp.route('/api/analytics/swarm')
def api_swarm():
    ip, port, live, hidden = _live_and_hidden()
    role = g.get('role') or 'viewer'
    hid = hidden if role != 'admin' else set()
    summaries = get_global_torrent_summaries()
    return jsonify({
        'survivability': get_tracker_survivability(summaries, live, hidden_hashes=hid),
        'protocols': get_protocol_efficiency(ip, port, live, hidden_hashes=hid),
        'slot_recs': get_qb_slot_recommendations(ip, port, live, cfg.getint('Max_Channel_Mbps', 1000))
    })


@deep_analytics_bp.route('/api/analytics/title_groups')
def api_title_groups():
    _, _, live, hidden = _live_and_hidden()
    hid = hidden if g.get('role') != 'admin' else set()
    summaries = get_global_torrent_summaries()
    return jsonify({'groups': find_normalized_title_groups(summaries, hidden_hashes=hid)})


@deep_analytics_bp.route('/api/analytics/wrapped')
def api_wrapped():
    period = 'year' if request.args.get('period') == 'year' else 'month'
    _, _, live, hidden = _live_and_hidden()
    hid = hidden if g.get('role') != 'admin' else set()
    return jsonify(build_wrapped_summary(summary_tracker.db, get_global_torrent_summaries(), live, period=period, hidden_hashes=hid))


@deep_analytics_bp.route('/api/inventory/export')
def api_inventory_export():
    fmt = request.args.get('fmt', 'json')
    if fmt not in ('json', 'csv', 'md'):
        fmt = 'json'
    include_vault = (g.get('role') == 'admin' and request.args.get('include_vault') == '1')
    _, _, live, hidden = _live_and_hidden()
    hid = set() if include_vault else hidden

    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            try:
                lineage_map = {r['torrent_hash']: r['torrent_uid'] for r in conn.execute("SELECT torrent_hash, torrent_uid FROM torrent_lineage").fetchall()}
            except Exception:
                lineage_map = {}
            try:
                notes_map = {r['uid']: r['note'] for r in conn.execute("SELECT uid, note FROM torrent_notes").fetchall()}
            except Exception:
                notes_map = {}

    data_bytes, mime, fname = export_full_inventory(get_global_torrent_summaries(), live, lineage_map, notes_map, fmt=fmt, hidden_hashes=hid)
    return Response(data_bytes, mimetype=mime, headers={'Content-Disposition': f'attachment; filename={fname}'})