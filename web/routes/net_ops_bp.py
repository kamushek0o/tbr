# web/routes/net_ops_bp.py
import json
import datetime
from flask import Blueprint, request, jsonify, Response, g
from utils.config import cfg
from core.summary_tracker import summary_tracker
from core.network_tools import (
    diagnose_bottleneck, ping_trackers_dns_tcp,
    check_network_interface_guard, read_sanitized_qb_log, reanimate_qb
)
from core.webhooks_bundler import get_webhook_deliveries, emit_webhook
from core.undo_presets import list_undo_stack, execute_undo, export_presets_json, import_presets_json

net_ops_bp = Blueprint('net_ops_bp', __name__)


def _not_admin():
    return g.get('role') != 'admin'


@net_ops_bp.route('/api/net/bottleneck')
def api_net_bottleneck():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    return jsonify(diagnose_bottleneck(summary_tracker.db))


@net_ops_bp.route('/api/net/ping_trackers')
def api_net_ping_trackers():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    return jsonify(ping_trackers_dns_tcp())


@net_ops_bp.route('/api/net/iface_guard', methods=['GET', 'POST'])
def api_net_iface_guard():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    if request.method == 'GET':
        res = check_network_interface_guard()
        res['expected_cfg'] = cfg.get('Expected_Net_Interface', '')
        res['panic_on_drop'] = cfg.getboolean('Interface_Guard_Panic', False)
        return jsonify(res)
    d = request.get_json(silent=True) or {}
    cfg.set('Interface_Guard_Enabled', str(bool(d.get('enabled', False))))
    cfg.set('Expected_Net_Interface', str(d.get('expected', '')).strip())
    cfg.set('Interface_Guard_Panic', str(bool(d.get('panic_on_drop', False))))
    cfg.save()
    return jsonify({'success': True})


@net_ops_bp.route('/api/qb/log')
def api_qb_log():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    ok, txt = read_sanitized_qb_log(lines_count=80)
    return jsonify({'success': ok, 'log': txt if ok else '', 'error': None if ok else txt})


@net_ops_bp.route('/api/qb/reanimate', methods=['POST'])
def api_qb_reanimate():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    force = bool((request.get_json(silent=True) or {}).get('force', False))
    ok, msg = reanimate_qb(force_kill=force)
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@net_ops_bp.route('/api/webhooks', methods=['GET', 'POST'])
def api_webhooks():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    if request.method == 'GET':
        return jsonify({
            'urls': cfg.get('Outbound_Webhooks', ''),
            'bundler_enabled': cfg.getboolean('Alert_Bundler_Enabled', True),
            'deliveries': get_webhook_deliveries()
        })
    d = request.get_json(silent=True) or {}
    cfg.set('Outbound_Webhooks', str(d.get('urls', '')).strip())
    cfg.set('Alert_Bundler_Enabled', str(bool(d.get('bundler_enabled', True))))
    cfg.save()
    if d.get('test'):
        emit_webhook('test_ping', {'message': 'tbr PRO webhook test'})
    return jsonify({'success': True})


@net_ops_bp.route('/api/undo/list')
def api_undo_list():
    if _not_admin():
        return jsonify({'items': []}), 403
    items = list_undo_stack()
    for it in items:
        it['date'] = datetime.datetime.fromtimestamp(it['created_at']).strftime('%H:%M:%S')
    return jsonify({'items': items})


@net_ops_bp.route('/api/undo/execute', methods=['POST'])
def api_undo_execute():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    uid = (request.get_json(silent=True) or {}).get('id')
    if not uid:
        return jsonify({'success': False, 'error': 'Нет ID'}), 400
    ok, msg = execute_undo(uid)
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@net_ops_bp.route('/api/presets/export')
def api_presets_export():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    return Response(
        json.dumps(export_presets_json(), ensure_ascii=False, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment; filename=tbr_presets.json'}
    )


@net_ops_bp.route('/api/presets/import', methods=['POST'])
def api_presets_import():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    d = request.get_json(silent=True) or {}
    ok, msg = import_presets_json(d)
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)