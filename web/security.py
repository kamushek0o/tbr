# web/security.py
import os
import re
import hmac
import secrets
import ipaddress
import urllib.parse
from flask import request, jsonify, redirect, session
from utils.helpers import LOG_FOLDER
from core.summary_tracker import AUTO_FOLDER, MANUAL_FOLDER

HASH_RE = re.compile(r'^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$')


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
        cgnat_net = ipaddress.ip_network('100.64.0.0/10')
        return ip_obj.is_loopback or ip_obj.is_private or (ip_obj in cgnat_net)
    except ValueError:
        return False


def resolve_log_path(filename):
    if not filename or not isinstance(filename, str):
        return None
    clean = os.path.basename(filename.replace('\\', '/'))
    allowed_dirs = [LOG_FOLDER, AUTO_FOLDER, MANUAL_FOLDER]

    if '/' in filename or '\\' in filename:
        parts = [p for p in filename.replace('\\', '/').split('/') if p]
        if len(parts) >= 2:
            sub = parts[-2]
            if sub == 'auto_hourly':
                allowed_dirs = [AUTO_FOLDER]
            elif sub == 'manual_exports':
                allowed_dirs = [MANUAL_FOLDER]
            clean = parts[-1]

    for directory in allowed_dirs:
        try:
            norm_dir = os.path.abspath(directory)
            full_path = os.path.abspath(os.path.join(norm_dir, clean))
            if os.path.commonpath([norm_dir, full_path]) == norm_dir and os.path.isfile(full_path):
                return full_path
        except ValueError:
            continue
    return None


def register_security(app):
    @app.before_request
    def security_middleware():
        if request.path.startswith('/static/'):
            return None

        is_exposed = app.config.get('IS_EXPOSED', False)
        if is_exposed and request.path != '/login':
            if not session.get('authenticated'):
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Требуется авторизация'}), 401
                return redirect('/login')

        if request.method == 'POST':
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