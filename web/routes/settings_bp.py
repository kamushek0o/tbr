# web/routes/settings_bp.py
import os
import hmac
import datetime
from flask import Blueprint, request, jsonify, render_template, redirect, session, current_app, Response, g

from utils.config import cfg
from core.version import APP_VERSION, GITHUB_RELEASES_URL
from core.qb_api import reset_qb_session, get_qb_executable_path, detect_qbittorrent_port, get_live_torrent_info
from core.autostart import is_autostart_enabled
from core.summary_tracker import summary_tracker
from core.scheduler import ALLOWED_INTERVALS, normalize_interval
from core.profiles_db import profiles_db
from core.backup_manager import create_backup_zip, stage_restore_zip
from core.keep_awake import keep_awake
from core.app_state_db import app_state_db
from core.disk_monitor import list_active_disks
from core.analytics_insights import invalidate_insights_cache
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
    app_state_db.add_audit_event('auth', 'Активация инвайта', f"Профиль {prof['login']}", actor=prof['login'])
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
        app_state_db.add_audit_event('auth', 'Успешный вход', f'IP: {ip}', actor='admin')
        return redirect('/')

    prof = profiles_db.authenticate_login(login_val, pwd) if login_val else profiles_db.authenticate_api_token(pwd)
    if prof:
        session['authenticated'] = True
        session['profile_id'] = prof['id']
        app_state_db.add_audit_event('auth', 'Успешный вход', f'IP: {ip}', actor=prof.get('login') or prof['name'])
        return redirect('/')

    record_failed_login(ip)
    app_state_db.add_audit_event('auth', 'Неудачный вход', f"IP: {ip}, login={login_val or '-'}", actor=login_val or 'guest')
    return render_template('login.html', csrf_token=get_csrf_token(), error='Неверный логин или пароль!'), 401


@settings_bp.route('/logout', methods=['POST', 'GET'])
def logout():
    session.pop('authenticated', None)
    session.pop('profile_id', None)
    return redirect('/login')


@settings_bp.route('/')
def index():
    return render_template(
        'index.html',
        csrf_token=get_csrf_token(),
        auth_enabled=current_app.config.get('IS_EXPOSED', False),
        v=current_app.config.get('BUILD_VER', '1'),
        app_version=APP_VERSION,
        releases_url=GITHUB_RELEASES_URL
    )


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
    if ok:
        app_state_db.add_audit_event('system', 'Восстановление бэкапа', msg, actor='admin')
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@settings_bp.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'GET':
        ip, port = detect_qbittorrent_port(cfg.config)
        live = get_live_torrent_info(ip, port) if port else {}
        return jsonify({
            'web_port': cfg.getint('Web_Port', 5000), 'web_host': cfg.get('Web_Host', '127.0.0.1'),
            'has_password': bool(cfg.get('Web_Password', '').strip()),
            'qb_ip': cfg.get('WebUI_Address', ''), 'qb_port': cfg.get('WebUI_Port', ''),
            'qb_user': cfg.get('WebUI_User', 'admin'), 'has_qb_password': bool(cfg.get('WebUI_Password', '').strip()),
            'w1': cfg.getint('Weight_W1', 70), 'w2': cfg.getint('Weight_W2', 30), 'w3': cfg.getint('Weight_W3', 0),
            'snapshot_interval': normalize_interval(cfg.getint('Snapshot_Interval_Min', 60)),
            'autostart': is_autostart_enabled(), 'is_windows': (os.name == 'nt'),
            'keep_awake_enabled': cfg.getboolean('KeepAwake_Enabled', False),
            'keep_awake_min_kb': cfg.getint('KeepAwake_Min_KB', 500),
            'keep_awake_display': cfg.getboolean('KeepAwake_Display', False),
            'auto_recheck_enabled': cfg.getboolean('AutoRecheck_Enabled', False),
            'watchdog_enabled': cfg.getboolean('Watchdog_Enabled', False),
            'watchdog_timeout_min': cfg.getint('Watchdog_Timeout_Min', 3),
            'watchdog_exe_path': cfg.get('Watchdog_Exe_Path', ''),
            'watchdog_exe_detected': get_qb_executable_path() if os.name == 'nt' else '',
            'manifest_weekly': cfg.getboolean('Manifest_Weekly', False),
            'max_channel_mbps': cfg.getint('Max_Channel_Mbps', 1000),
            'monitored_disk': cfg.get('Monitored_Disk_Path', ''),
            'disks': list_active_disks(live)
        })

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Некорректные данные'}), 400

    old_p, old_h = cfg.getint('Web_Port', 5000), cfg.get('Web_Host', '127.0.0.1').strip() or '127.0.0.1'
    try:
        new_p = int(data.get('web_port', old_p))
        if not (1 <= new_p <= 65535):
            raise ValueError
        qb_ip = str(data.get('qb_ip', '')).strip()
        if not is_allowed_qb_ip(qb_ip):
            return jsonify({'success': False, 'error': 'Недопустимый IP qBittorrent'}), 400
        qb_port_raw = str(data.get('qb_port', '')).strip()
        if qb_port_raw and not (1 <= int(qb_port_raw) <= 65535):
            raise ValueError
        w1, w2, w3 = int(data.get('w1', 70)), int(data.get('w2', 30)), int(data.get('w3', 0))
        snap_iv = int(data.get('snapshot_interval', 60))
        if w1 < 0 or w2 < 0 or w3 < 0 or (w1 + w2 + w3) <= 0 or snap_iv not in ALLOWED_INTERVALS:
            raise ValueError
        ka_min_kb = max(0, min(1000000, int(data.get('keep_awake_min_kb', 500))))
        wd_timeout = max(2, min(10, int(data.get('watchdog_timeout_min', 3))))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Некорректные числовые параметры'}), 400

    new_host = str(data.get('web_host', '127.0.0.1')).strip() or '127.0.0.1'
    new_pass = str(data.get('web_password', '')).strip()
    if new_host not in ('127.0.0.1', 'localhost') and not (new_pass or cfg.get('Web_Password', '').strip()):
        return jsonify({'success': False, 'error': 'Для внешнего хоста обязательно задайте пароль!'}), 400

    wd_exe = str(data.get('watchdog_exe_path', '')).strip()
    if wd_exe and ('..' in wd_exe or (os.name == 'nt' and not wd_exe.lower().endswith('.exe'))):
        return jsonify({'success': False, 'error': 'Некорректный путь к исполняемому файлу'}), 400

    old_snap_iv = normalize_interval(cfg.getint('Snapshot_Interval_Min', 60))
    old_mbps = cfg.getint('Max_Channel_Mbps', 1000)

    cfg.set('Web_Port', new_p); cfg.set('Web_Host', new_host)
    if new_pass:
        cfg.set('Web_Password', new_pass)
    cfg.set('WebUI_Address', qb_ip); cfg.set('WebUI_Port', qb_port_raw)
    cfg.set('WebUI_User', str(data.get('qb_user', 'admin')).strip() or 'admin')
    if str(data.get('qb_password', '')):
        cfg.set('WebUI_Password', str(data.get('qb_password', '')))
    cfg.set('Weight_W1', w1); cfg.set('Weight_W2', w2); cfg.set('Weight_W3', w3)
    cfg.set('Snapshot_Interval_Min', snap_iv)
    cfg.set('KeepAwake_Enabled', str(bool(data.get('keep_awake_enabled', False))))
    cfg.set('KeepAwake_Min_KB', str(ka_min_kb))
    cfg.set('KeepAwake_Display', str(bool(data.get('keep_awake_display', False))))
    cfg.set('Watchdog_Enabled', str(bool(data.get('watchdog_enabled', False))))
    cfg.set('Watchdog_Timeout_Min', str(wd_timeout))
    cfg.set('Watchdog_Exe_Path', wd_exe)
    if 'auto_recheck_enabled' in data:
        cfg.set('AutoRecheck_Enabled', str(bool(data.get('auto_recheck_enabled'))))
    if 'manifest_weekly' in data:
        cfg.set('Manifest_Weekly', str(bool(data.get('manifest_weekly'))))
    if 'max_channel_mbps' in data:
        cfg.set('Max_Channel_Mbps', str(max(10, min(100000, int(data.get('max_channel_mbps', 1000))))))
    if 'monitored_disk' in data:
        cfg.set('Monitored_Disk_Path', str(data.get('monitored_disk', '')).strip())
    cfg.save()

    if not cfg.getboolean('KeepAwake_Enabled', False):
        keep_awake.release()
    reset_qb_session()
    if old_snap_iv != snap_iv:
        summary_tracker.notify_interval_changed()
    if cfg.getint('Max_Channel_Mbps', 1000) != old_mbps:
        invalidate_insights_cache()

    app_state_db.add_audit_event('system', 'Изменение настроек', f'host={new_host}:{new_p}', actor='admin')
    net_changed = (old_p != new_p) or (old_h != new_host)
    if net_changed:
        ws = current_app.config.get('WEB_SERVER')
        if ws:
            ws.restart(new_host, new_p)

    return jsonify({'success': True, 'port_changed': net_changed, 'new_port': new_p, 'message': 'Настройки сохранены! Веб-сервер перезапущен.' if net_changed else 'Настройки сохранены!'})