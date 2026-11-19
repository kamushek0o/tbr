# web/routes/system_bp.py
import urllib.parse
from flask import Blueprint, request, jsonify, Response, g

from utils.config import cfg
from core.version import APP_VERSION, GITHUB_RELEASES_URL
from core.updater import check_for_updates, download_and_apply_update, is_frozen_windows
from core.disaster_recovery import (
    execute_panic_killswitch, create_disaster_manifest,
    list_manifests, get_manifest_path
)

system_bp = Blueprint('system_bp', __name__)


def _actor_name():
    prof = g.get('profile')
    return (prof.get('login') or prof.get('name') or 'admin') if prof else 'admin'


@system_bp.route('/api/version')
@system_bp.route('/api/status')
def api_version():
    return jsonify({
        'name': 'tbr PRO',
        'version': APP_VERSION,
        'releases_url': GITHUB_RELEASES_URL,
        'can_auto_update': is_frozen_windows(),
        'autopilot_frozen_until': cfg.getint('Autopilot_Frozen_Until', 0),
        'role': g.get('role') or 'viewer'
    })


@system_bp.route('/api/update/check')
def api_update_check():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    force = request.args.get('force', '0') == '1'
    return jsonify(check_for_updates(force=force))


@system_bp.route('/api/update/apply', methods=['POST'])
def api_update_apply():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    ok, msg = download_and_apply_update(actor=_actor_name())
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@system_bp.route('/api/panic', methods=['POST'])
def api_panic_killswitch():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    data = request.get_json(silent=True) or {}
    kill_qb = bool(data.get('kill_qb', False))
    res = execute_panic_killswitch(kill_qb=kill_qb, actor=_actor_name())
    return jsonify(res)


@system_bp.route('/api/manifest/list')
def api_manifest_list():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    return jsonify({
        'manifests': list_manifests(),
        'weekly': cfg.getboolean('Manifest_Weekly', False)
    })


@system_bp.route('/api/manifest/weekly', methods=['POST'])
def api_manifest_weekly():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    data = request.get_json(silent=True) or {}
    weekly = bool(data.get('weekly', False))
    cfg.set('Manifest_Weekly', str(weekly))
    cfg.save()
    return jsonify({'success': True, 'weekly': weekly})


@system_bp.route('/api/manifest/create', methods=['POST'])
def api_manifest_create():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    res = create_disaster_manifest(actor=_actor_name())
    return jsonify({'success': True, **res})


@system_bp.route('/api/manifest/download')
def api_manifest_download():
    if g.get('role') != 'admin':
        return "Только для Admin", 403
    fname = request.args.get('file', '')
    fpath = get_manifest_path(fname)
    if not fpath:
        return "Файл не найден", 404
    with open(fpath, 'rb') as f:
        data = f.read()
    clean_name = urllib.parse.quote(fname)
    return Response(
        data,
        mimetype='application/json',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{clean_name}"}
    )