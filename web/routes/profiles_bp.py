# web/routes/profiles_bp.py
from flask import Blueprint, request, jsonify, g
from core.profiles_db import profiles_db

profiles_bp = Blueprint('profiles_bp', __name__)


@profiles_bp.route('/api/me')
def api_me():
    prof = g.get('profile')
    if not prof:
        return jsonify({'authenticated': False, 'role': 'viewer', 'ui_settings': profiles_db.get_ui_settings(0)})
    return jsonify({
        'authenticated': True,
        'id': prof['id'],
        'name': prof['name'],
        'role': prof['role'],
        'ui_settings': profiles_db.get_ui_settings(prof['id'])
    })


@profiles_bp.route('/api/profile/ui', methods=['GET', 'POST'])
def api_profile_ui():
    prof = g.get('profile')
    pid = prof['id'] if prof else 0
    if request.method == 'GET':
        return jsonify({'ui_settings': profiles_db.get_ui_settings(pid)})

    data = request.get_json(silent=True) or {}
    saved = profiles_db.save_ui_settings(pid, data)
    return jsonify({'success': True, 'ui_settings': saved})


@profiles_bp.route('/api/profiles')
def api_profiles_list():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    return jsonify({'profiles': profiles_db.list_profiles()})


@profiles_bp.route('/api/profiles/create', methods=['POST'])
def api_profiles_create():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    role = data.get('role', 'viewer')
    pid, raw_token = profiles_db.create_profile(name, role)
    if not pid:
        return jsonify({'success': False, 'error': 'Не удалось создать профиль'}), 500
    return jsonify({'success': True, 'id': pid, 'token': raw_token})


@profiles_bp.route('/api/profiles/reissue', methods=['POST'])
def api_profiles_reissue():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    data = request.get_json(silent=True) or {}
    pid = data.get('id')
    if not pid:
        return jsonify({'success': False, 'error': 'Не указан ID'}), 400
    new_tok = profiles_db.reissue_token(pid)
    if not new_tok:
        return jsonify({'success': False, 'error': 'Профиль не найден'}), 404
    return jsonify({'success': True, 'token': new_tok})


@profiles_bp.route('/api/profiles/delete', methods=['POST'])
def api_profiles_delete():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    data = request.get_json(silent=True) or {}
    pid = data.get('id')
    if not pid:
        return jsonify({'success': False, 'error': 'Не указан ID'}), 400
    ok, msg = profiles_db.delete_profile(pid)
    return jsonify({'success': ok, 'message': msg, 'error': None if ok else msg}), (200 if ok else 400)