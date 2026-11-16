# web/routes/settings_bp.py
import hmac
from flask import Blueprint, request, jsonify, render_template, redirect, session, current_app

from utils.config import cfg
from core.qb_api import reset_qb_session
from core.autostart import is_autostart_enabled
from web.security import get_csrf_token, is_allowed_qb_ip

settings_bp = Blueprint('settings_bp', __name__)


@settings_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html', csrf_token=get_csrf_token(), error=None)
    pwd = request.form.get('password', '')
    real_pwd = cfg.get('Web_Password', '')
    if real_pwd and hmac.compare_digest(pwd, real_pwd):
        session['authenticated'] = True
        return redirect('/')
    return render_template('login.html', csrf_token=get_csrf_token(), error='Неверный пароль!'), 401


@settings_bp.route('/logout', methods=['POST', 'GET'])
def logout():
    session.pop('authenticated', None)
    return redirect('/login')


@settings_bp.route('/')
def index():
    return render_template(
        'index.html',
        csrf_token=get_csrf_token(),
        auth_enabled=current_app.config.get('IS_EXPOSED', False),
        v=current_app.config.get('BUILD_VER', '1')
    )


@settings_bp.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'GET':
        return jsonify({
            'web_port': cfg.getint('Web_Port', 5000),
            'web_host': cfg.get('Web_Host', '127.0.0.1'),
            'has_password': bool(cfg.get('Web_Password', '').strip()),
            'qb_ip': cfg.get('WebUI_Address', ''),
            'qb_port': cfg.get('WebUI_Port', ''),
            'qb_user': cfg.get('WebUI_User', 'admin'),
            'has_qb_password': bool(cfg.get('WebUI_Password', '').strip()),
            'w1': cfg.getint('Weight_W1', 70),
            'w2': cfg.getint('Weight_W2', 30),
            'w3': cfg.getint('Weight_W3', 0),
            'autostart': is_autostart_enabled()
        })

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Некорректные данные'}), 400

    old_p = cfg.getint('Web_Port', 5000)
    old_h = cfg.get('Web_Host', '127.0.0.1').strip() or '127.0.0.1'

    try:
        new_p = int(data.get('web_port', old_p))
        if not (1 <= new_p <= 65535):
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Порт должен быть числом от 1 до 65535'}), 400

    qb_ip = str(data.get('qb_ip', '')).strip()
    if not is_allowed_qb_ip(qb_ip):
        return jsonify({'success': False, 'error': 'Недопустимый IP qBittorrent (разрешены только локальные сети и NetBird)'}), 400

    qb_port_raw = str(data.get('qb_port', '')).strip()
    if qb_port_raw:
        try:
            qbp = int(qb_port_raw)
            if not (1 <= qbp <= 65535):
                raise ValueError
        except ValueError:
            return jsonify({'success': False, 'error': 'Порт qBittorrent должен быть от 1 до 65535'}), 400

    try:
        w1 = int(data.get('w1', cfg.getint('Weight_W1', 70)))
        w2 = int(data.get('w2', cfg.getint('Weight_W2', 30)))
        w3 = int(data.get('w3', cfg.getint('Weight_W3', 0)))
        if w1 < 0 or w2 < 0 or w3 < 0 or (w1 + w2 + w3) <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Веса должны быть >= 0, и хотя бы один вес > 0'}), 400

    new_host = str(data.get('web_host', '127.0.0.1')).strip() or '127.0.0.1'
    new_pass = str(data.get('web_password', '')).strip()
    effective_pass = new_pass if new_pass else cfg.get('Web_Password', '').strip()

    if new_host not in ('127.0.0.1', 'localhost') and not effective_pass:
        return jsonify({'success': False, 'error': 'Для внешнего хоста обязательно задайте пароль!'}), 400

    qb_user = str(data.get('qb_user', 'admin')).strip() or 'admin'
    qb_pass = str(data.get('qb_password', ''))

    cfg.set('Web_Port', new_p)
    cfg.set('Web_Host', new_host)
    if new_pass:
        cfg.set('Web_Password', new_pass)
    cfg.set('WebUI_Address', qb_ip)
    cfg.set('WebUI_Port', qb_port_raw)
    cfg.set('WebUI_User', qb_user)
    if qb_pass:
        cfg.set('WebUI_Password', qb_pass)
    cfg.set('Weight_W1', w1)
    cfg.set('Weight_W2', w2)
    cfg.set('Weight_W3', w3)
    cfg.save()

    reset_qb_session()

    net_changed = (old_p != new_p) or (old_h != new_host)
    if net_changed:
        ws = current_app.config.get('WEB_SERVER')
        if ws:
            ws.restart(new_host, new_p)

    return jsonify({
        'success': True,
        'port_changed': net_changed,
        'new_port': new_p,
        'message': 'Настройки сохранены! Веб-сервер перезапущен на новых параметрах.' if net_changed else 'Настройки сохранены!'
    })