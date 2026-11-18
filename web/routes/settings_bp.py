# web/routes/settings_bp.py
import hmac
import datetime
from flask import Blueprint, request, jsonify, render_template, redirect, session, current_app, Response, g

from utils.config import cfg
from core.qb_api import reset_qb_session
from core.autostart import is_autostart_enabled
from core.summary_tracker import summary_tracker
from core.scheduler import ALLOWED_INTERVALS, normalize_interval
from core.profiles_db import profiles_db
from core.backup_manager import create_backup_zip, stage_restore_zip
from web.security import get_csrf_token, is_allowed_qb_ip, check_rate_limit, record_failed_login

settings_bp = Blueprint('settings_bp', __name__)


@settings_bp.route('/invite/<token>', methods=['GET', 'POST'])
def invite_accept(token):
    inv = profiles_db.get_valid_invite(token)
    if not inv:
        return render_template('invite.html', csrf_token=get_csrf_token(), error='Инвайт-ссылка недействительна, просрочена или уже использована.', invite=None), 410
    if request.method == 'GET':
        return render_template('invite.html', csrf_token=get_csrf_token(), error=None, invite=inv)
    expected, sent = session.get('csrf_token'), request.form.get('csrf_token')
    if not (expected and sent and hmac.compare_digest(str(expected), str(sent))):
        return render_template('invite.html', csrf_token=get_csrf_token(), error='CSRF ошибка, обновите страницу.', invite=inv), 403
    prof, err = profiles_db.consume_invite(token, request.form.get('login', '').strip(), request.form.get('password', '').strip())
    if err or not prof:
        return render_template('invite.html', csrf_token=get_csrf_token(), error=err or 'Ошибка активации', invite=inv), 400
    session['authenticated'] = True
    session['profile_id'] = prof['id']
    return redirect('/')


@settings_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html', csrf_token=get_csrf_token(), error=None)
    ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or '0.0.0.0').split(',')[0].strip()
    if not check_rate_limit(ip):
        return render_template('login.html', csrf_token=get_csrf_token(), error='Слишком много попыток входа. Подождите 5 минут.'), 429

    login_val, pwd = request.form.get('login', '').strip(), request.form.get('password', '').strip()
    real_pwd = cfg.get('Web_Password', '')
    if real_pwd and hmac.compare_digest(pwd, real_pwd) and (not login_val or login_val.lower() == 'admin'):
        session['authenticated'] = True
        adm = profiles_db.get_default_admin()
        if adm:
            session['profile_id'] = adm['id']
        return redirect('/')

    prof = profiles_db.authenticate_login(login_val, pwd) if login_val else profiles_db.authenticate_api_token(pwd)
    if prof:
        session['authenticated'] = True
        session['profile_id'] = prof['id']
        return redirect('/')

    record_failed_login(ip)
    return render_template('login.html', csrf_token=get_csrf_token(), error='Неверный логин или пароль!'), 401


@settings_bp.route('/logout', methods=['POST', 'GET'])
def logout():
    session.pop('authenticated', None)
    session.pop('profile_id', None)
    return redirect('/login')


@settings_bp.route('/')
def index():
    return render_template('index.html', csrf_token=get_csrf_token(), auth_enabled=current_app.config.get('IS_EXPOSED', False), v=current_app.config.get('BUILD_VER', '1'))


@settings_bp.route('/api/backup/export')
def api_backup_export():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    ex_hist = request.args.get('exclude_history', '0') == '1'
    strip_sec = request.args.get('strip_secrets', '0') == '1'
    zip_bytes = create_backup_zip(exclude_history=ex_hist, strip_secrets=strip_sec)
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    return Response(zip_bytes, mimetype='application/zip', headers={'Content-Disposition': f'attachment; filename=tbr_backup_{ts}.zip'})


@settings_bp.route('/api/backup/restore', methods=['POST'])
def api_backup_restore():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    f = request.files.get('file')
    if not f:
        return jsonify({'success': False, 'error': 'Файл не передан'}), 400
    ok, msg = stage_restore_zip(f.read())
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@settings_bp.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'GET':
        return jsonify({
            'web_port': cfg.getint('Web_Port', 5000), 'web_host': cfg.get('Web_Host', '127.0.0.1'),
            'has_password': bool(cfg.get('Web_Password', '').strip()),
            'qb_ip': cfg.get('WebUI_Address', ''), 'qb_port': cfg.get('WebUI_Port', ''),
            'qb_user': cfg.get('WebUI_User', 'admin'), 'has_qb_password': bool(cfg.get('WebUI_Password', '').strip()),
            'w1': cfg.getint('Weight_W1', 70), 'w2': cfg.getint('Weight_W2', 30), 'w3': cfg.getint('Weight_W3', 0),
            'snapshot_interval': normalize_interval(cfg.getint('Snapshot_Interval_Min', 60)),
            'autostart': is_autostart_enabled()
        })

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Некорректные данные'}), 400

    old_p, old_h = cfg.getint('Web_Port', 5000), cfg.get('Web_Host', '127.0.0.1').strip() or '127.0.0.1'
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
            if not (1 <= int(qb_port_raw) <= 65535):
                raise ValueError
        except ValueError:
            return jsonify({'success': False, 'error': 'Порт qBittorrent должен быть от 1 до 65535'}), 400

    try:
        w1, w2, w3 = int(data.get('w1', 70)), int(data.get('w2', 30)), int(data.get('w3', 0))
        if w1 < 0 or w2 < 0 or w3 < 0 or (w1 + w2 + w3) <= 0:
            raise ValueError
        snap_iv = int(data.get('snapshot_interval', 60))
        if snap_iv not in ALLOWED_INTERVALS:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Некорректные веса или интервал замеров'}), 400

    new_host = str(data.get('web_host', '127.0.0.1')).strip() or '127.0.0.1'
    new_pass = str(data.get('web_password', '')).strip()
    if new_host not in ('127.0.0.1', 'localhost') and not (new_pass or cfg.get('Web_Password', '').strip()):
        return jsonify({'success': False, 'error': 'Для внешнего хоста обязательно задайте пароль!'}), 400

    old_snap_iv = normalize_interval(cfg.getint('Snapshot_Interval_Min', 60))
    cfg.set('Web_Port', new_p); cfg.set('Web_Host', new_host)
    if new_pass:
        cfg.set('Web_Password', new_pass)
    cfg.set('WebUI_Address', qb_ip); cfg.set('WebUI_Port', qb_port_raw)
    cfg.set('WebUI_User', str(data.get('qb_user', 'admin')).strip() or 'admin')
    if str(data.get('qb_password', '')):
        cfg.set('WebUI_Password', str(data.get('qb_password', '')))
    cfg.set('Weight_W1', w1); cfg.set('Weight_W2', w2); cfg.set('Weight_W3', w3)
    cfg.set('Snapshot_Interval_Min', snap_iv); cfg.save()

    reset_qb_session()
    if old_snap_iv != snap_iv:
        summary_tracker.notify_interval_changed()

    net_changed = (old_p != new_p) or (old_h != new_host)
    if net_changed:
        ws = current_app.config.get('WEB_SERVER')
        if ws:
            ws.restart(new_host, new_p)

    return jsonify({'success': True, 'port_changed': net_changed, 'new_port': new_p, 'message': 'Настройки сохранены! Веб-сервер перезапущен.' if net_changed else 'Настройки сохранены!'})