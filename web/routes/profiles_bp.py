# web/routes/profiles_bp.py
import datetime
from flask import Blueprint, request, jsonify, g, session
from core.profiles_db import profiles_db
from core.qb_api import get_local_ips
from core.sessions import sessions_mgr
from core.app_state_db import app_state_db
from web.security import get_client_ip

profiles_bp = Blueprint('profiles_bp', __name__)


@profiles_bp.route('/api/me')
def api_me():
    prof = g.get('profile')
    if not prof:
        return jsonify({'authenticated': False, 'role': 'viewer', 'ui_settings': profiles_db.get_ui_settings(0)})
    return jsonify({
        'authenticated': True, 'id': prof['id'], 'name': prof['name'],
        'login': prof.get('login', ''), 'role': prof['role'],
        'ui_settings': profiles_db.get_ui_settings(prof['id'])
    })


@profiles_bp.route('/api/auth/exchange', methods=['POST'])
def api_auth_exchange():
    ip = get_client_ip()
    if not sessions_mgr.check_rate_limit(ip, bucket='login'):
        return jsonify({'success': False, 'error': 'Слишком много попыток. Подождите 10 минут.'}), 429

    data = request.get_json(silent=True) or {}
    login = str(data.get('login', '')).strip()
    password = str(data.get('password', '')).strip()
    prof = profiles_db.authenticate_login(login, password)
    if not prof:
        sessions_mgr.record_failure(ip, bucket='login')
        return jsonify({'success': False, 'error': 'Неверный логин или пароль'}), 401

    sessions_mgr.clear_failures(ip, bucket='login')
    return jsonify({'success': True, 'api_token': prof.get('api_token', ''), 'role': prof['role'], 'name': prof['name']})


@profiles_bp.route('/api/sessions')
def api_sessions_list():
    prof = g.get('profile')
    if not prof:
        return jsonify({'sessions': []}), 401
    cur_sid = session.get('sid', '')
    pid_filter = None if g.get('role') == 'admin' else prof['id']
    rows = sessions_mgr.list_active_sessions(current_sid=cur_sid, profile_id=pid_filter)
    for r in rows:
        r['last_seen_fmt'] = datetime.datetime.fromtimestamp(r['last_seen']).strftime('%d.%m %H:%M')
        r['created_fmt'] = datetime.datetime.fromtimestamp(r['created_at']).strftime('%d.%m %H:%M')
    return jsonify({'sessions': rows})


@profiles_bp.route('/api/sessions/revoke_others', methods=['POST'])
def api_sessions_revoke_others():
    prof = g.get('profile')
    if not prof:
        return jsonify({'success': False, 'error': 'Не авторизован'}), 401
    cur_sid = session.get('sid', '')
    pid_filter = None if g.get('role') == 'admin' else prof['id']
    revoked_cnt = sessions_mgr.revoke_other_sessions(cur_sid, profile_id=pid_filter)
    app_state_db.add_audit_event('auth', 'Завершены прочие сессии', f'count={revoked_cnt}', actor=prof.get('login') or 'user')
    return jsonify({'success': True, 'revoked': revoked_cnt, 'message': f'Завершено сессий: {revoked_cnt}'})


@profiles_bp.route('/api/sessions/revoke', methods=['POST'])
def api_sessions_revoke_one():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    sid = str((request.get_json(silent=True) or {}).get('sid', '')).strip()
    if not sid:
        return jsonify({'success': False, 'error': 'Не указан SID'}), 400
    return jsonify({'success': sessions_mgr.revoke_session(sid)})


@profiles_bp.route('/api/profile/ui', methods=['GET', 'POST'])
def api_profile_ui():
    prof = g.get('profile')
    pid = prof['id'] if prof else 0
    if request.method == 'GET':
        return jsonify({'ui_settings': profiles_db.get_ui_settings(pid)})
    data = request.get_json(silent=True) or {}
    return jsonify({'success': True, 'ui_settings': profiles_db.save_ui_settings(pid, data)})


@profiles_bp.route('/api/profile/password', methods=['POST'])
def api_self_password():
    prof = g.get('profile')
    if not prof:
        return jsonify({'success': False, 'error': 'Не авторизован'}), 401
    new_pwd = str((request.get_json(silent=True) or {}).get('password', '')).strip()
    _, err = profiles_db.change_password(prof['id'], new_password=new_pwd)
    if err:
        return jsonify({'success': False, 'error': err}), 400
    return jsonify({'success': True})


@profiles_bp.route('/api/network/hosts')
def api_network_hosts():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    return jsonify({'ips': get_local_ips()})


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
    pid, raw_pwd, api_tok, err = profiles_db.create_profile(
        data.get('name', ''), data.get('role', 'viewer'),
        login=data.get('login', ''), password=data.get('password', '')
    )
    if not pid:
        return jsonify({'success': False, 'error': err or 'Не удалось создать профиль'}), 400
    return jsonify({'success': True, 'id': pid, 'password': raw_pwd, 'api_token': api_tok})


@profiles_bp.route('/api/profiles/change_password', methods=['POST'])
def api_profiles_change_password():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    data = request.get_json(silent=True) or {}
    pid = data.get('id')
    if not pid:
        return jsonify({'success': False, 'error': 'Не указан ID'}), 400
    new_pwd, err = profiles_db.change_password(pid, new_password=data.get('password', ''), new_login=data.get('login'))
    if err:
        return jsonify({'success': False, 'error': err}), 400
    return jsonify({'success': True, 'password': new_pwd})


@profiles_bp.route('/api/profiles/invite', methods=['POST'])
def api_profiles_invite():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    pid = (request.get_json(silent=True) or {}).get('id')
    if not pid:
        return jsonify({'success': False, 'error': 'Не указан ID'}), 400
    inv = profiles_db.create_invite(pid)
    if not inv:
        return jsonify({'success': False, 'error': 'Не удалось создать инвайт'}), 400
    return jsonify({'success': True, 'invite_token': inv})


@profiles_bp.route('/api/profiles/reissue_api', methods=['POST'])
def api_profiles_reissue_api():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    pid = (request.get_json(silent=True) or {}).get('id')
    if not pid:
        return jsonify({'success': False, 'error': 'Не указан ID'}), 400
    tok = profiles_db.reissue_api_token(pid)
    if not tok:
        return jsonify({'success': False, 'error': 'Профиль не найден'}), 404
    return jsonify({'success': True, 'api_token': tok})


@profiles_bp.route('/api/profiles/delete', methods=['POST'])
def api_profiles_delete():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    pid = (request.get_json(silent=True) or {}).get('id')
    if not pid:
        return jsonify({'success': False, 'error': 'Не указан ID'}), 400
    ok, msg = profiles_db.delete_profile(pid)
    return jsonify({'success': ok, 'message': msg, 'error': None if ok else msg}), (200 if ok else 400)