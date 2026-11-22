# web/security.py
import os
import re
import hmac
import secrets
import ipaddress
import urllib.parse
from flask import request, jsonify, redirect, session, g
from utils.helpers import LOG_FOLDER
from core.summary_tracker import AUTO_FOLDER, MANUAL_FOLDER
from core.profiles_db import profiles_db
from core.sessions import sessions_mgr

HASH_RE = re.compile(r'^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$')

_VIEWER_BLOCKED_GET_PREFIXES = ('/api/settings', '/api/automation', '/api/logs', '/api/profiles', '/api/network', '/api/doctor', '/api/vault')
_PUBLIC_ASSET_PATHS = ('/favicon.ico', '/manifest.json', '/icon-192.png', '/icon-512.png', '/apple-touch-icon.png')


def check_rate_limit(ip, bucket='login'):
    return sessions_mgr.check_rate_limit(ip, bucket=bucket)


def record_failed_login(ip, bucket='login'):
    sessions_mgr.record_failure(ip, bucket=bucket)


def _is_trusted_proxy_ip(ip_str):
    s = str(ip_str or '').strip()
    if s in ('127.0.0.1', '::1'):
        return True
    try:
        obj = ipaddress.ip_address(s)
        return obj.is_loopback or obj.is_private
    except ValueError:
        return False


def get_client_ip():
    """Защита от спуфинга X-Forwarded-For: доверяем прокси-заголовку только если remote_addr — локальный/доверенный прокси."""
    remote = (request.remote_addr or '127.0.0.1').strip()
    if _is_trusted_proxy_ip(remote):
        fwd = (request.headers.get('X-Forwarded-For') or request.headers.get('X-Real-IP') or '').split(',')[0].strip()
        if fwd:
            return fwd
    return remote


def get_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']


def is_allowed_qb_ip(ip_str):
    s = (ip_str or '').strip().lower()
    if s in ('', 'localhost'):
        return True
    try:
        ip_obj = ipaddress.ip_address(s)
        return ip_obj.is_loopback or ip_obj.is_private or (ip_obj in ipaddress.ip_network('100.64.0.0/10'))
    except ValueError:
        return False


def resolve_log_path(filename):
    if not filename or not isinstance(filename, str):
        return None
    clean = os.path.basename(filename.replace('\\', '/'))
    for directory in (LOG_FOLDER, AUTO_FOLDER, MANUAL_FOLDER):
        try:
            norm_dir = os.path.abspath(directory)
            full_path = os.path.abspath(os.path.join(norm_dir, clean))
            if os.path.commonpath([norm_dir, full_path]) == norm_dir and os.path.isfile(full_path):
                return full_path
        except ValueError:
            continue
    return None


def _resolve_request_profile(is_exposed):
    ip = get_client_ip()
    auth_hdr = request.headers.get('Authorization', '').strip()
    token = auth_hdr[7:].strip() if auth_hdr.lower().startswith('bearer ') else request.headers.get('X-Auth-Token', '').strip()
    if token:
        if not sessions_mgr.check_rate_limit(ip, bucket='api_token'):
            return None, True
        prof = profiles_db.authenticate_api_token(token)
        if prof:
            sessions_mgr.clear_failures(ip, bucket='api_token')
            return prof, True
        sessions_mgr.record_failure(ip, bucket='api_token')
        return None, True

    pid = session.get('profile_id')
    if pid and session.get('authenticated'):
        sid = session.get('sid')
        if sid:
            if not sessions_mgr.validate_and_touch(sid):
                session.clear()
                return None, False
        else:
            session['sid'] = sessions_mgr.create_session(pid, ip, request.headers.get('User-Agent', ''))
        prof = profiles_db.get_by_id(pid)
        if prof:
            return prof, False

    if not is_exposed:
        return profiles_db.get_default_admin(), False

    return None, False


def register_security(app):
    @app.before_request
    def security_middleware():
        if request.path.startswith('/static/') or request.path in _PUBLIC_ASSET_PATHS:
            return None

        if request.path.startswith('/invite/') or request.path == '/api/auth/exchange':
            return None

        is_exposed = app.config.get('IS_EXPOSED', False)
        prof, used_bearer = _resolve_request_profile(is_exposed)
        g.profile = prof
        g.role = prof['role'] if prof else None

        if request.path in ('/login', '/logout'):
            if request.method == 'POST' and request.path == '/login':
                expected_token = session.get('csrf_token')
                sent_token = request.form.get('csrf_token')
                if not (expected_token and sent_token and hmac.compare_digest(str(expected_token), str(sent_token))):
                    return jsonify({'error': 'CSRF ошибка'}), 403
            return None

        if is_exposed and not prof:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Требуется авторизация'}), 401
            return redirect('/login')

        if g.role == 'viewer':
            if request.path == '/api/profile/password' and request.method == 'POST':
                pass
            elif request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
                return jsonify({'error': 'Недостаточно прав (режим Viewer — только чтение)'}), 403
            elif any(request.path.startswith(p) for p in _VIEWER_BLOCKED_GET_PREFIXES):
                return jsonify({'error': 'Доступ закрыт для роли Viewer'}), 403

        if request.method == 'POST' and not used_bearer:
            expected_token = session.get('csrf_token')
            sent_token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
            origin = request.headers.get('Origin') or request.headers.get('Referer')
            allowed_hosts = {request.host}
            for hdr in ('X-Forwarded-Host', 'X-Original-Host'):
                if request.headers.get(hdr):
                    allowed_hosts.add(request.headers.get(hdr).split(',')[0].strip())

            origin_ok = True
            if origin:
                parsed = urllib.parse.urlparse(origin)
                if parsed.netloc and parsed.netloc not in allowed_hosts:
                    origin_ok = False

            token_ok = bool(expected_token and sent_token and hmac.compare_digest(str(expected_token), str(sent_token)))
            if not token_ok or not origin_ok:
                return jsonify({'error': 'CSRF проверка не пройдена. Обновите страницу.'}), 403