# web/routes/batch_bp.py
from flask import Blueprint, request, jsonify, g
from core.tracker_replacer import preview_tracker_replace, apply_tracker_replace
from core.batch_relocate import preview_batch_relocate, start_batch_relocate, get_relocate_status
from core.path_remapper import preview_fastresume_remap, apply_fastresume_remap

batch_bp = Blueprint('batch_bp', __name__)


def _not_admin():
    return g.get('role') != 'admin'


@batch_bp.route('/api/batch/trackers/preview', methods=['POST'])
def api_batch_trackers_preview():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    d = request.get_json(silent=True) or {}
    return jsonify(preview_tracker_replace(d.get('find', ''), d.get('replace', '')))


@batch_bp.route('/api/batch/trackers/apply', methods=['POST'])
def api_batch_trackers_apply():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    d = request.get_json(silent=True) or {}
    return jsonify(apply_tracker_replace(d.get('find', ''), d.get('replace', ''), actor='admin'))


@batch_bp.route('/api/batch/relocate/preview', methods=['POST'])
def api_batch_relocate_preview():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    d = request.get_json(silent=True) or {}
    return jsonify(preview_batch_relocate(d.get('old_prefix', ''), d.get('new_prefix', '')))


@batch_bp.route('/api/batch/relocate/start', methods=['POST'])
def api_batch_relocate_start():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    d = request.get_json(silent=True) or {}
    return jsonify(start_batch_relocate(d.get('old_prefix', ''), d.get('new_prefix', ''), actor='admin'))


@batch_bp.route('/api/batch/relocate/status')
def api_batch_relocate_status():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    return jsonify(get_relocate_status())


@batch_bp.route('/api/batch/remap/preview', methods=['POST'])
def api_batch_remap_preview():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    d = request.get_json(silent=True) or {}
    return jsonify(preview_fastresume_remap(d.get('old_prefix', ''), d.get('new_prefix', '')))


@batch_bp.route('/api/batch/remap/apply', methods=['POST'])
def api_batch_remap_apply():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    d = request.get_json(silent=True) or {}
    return jsonify(apply_fastresume_remap(d.get('old_prefix', ''), d.get('new_prefix', ''), actor='admin'))