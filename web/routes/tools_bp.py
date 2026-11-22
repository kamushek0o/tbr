# web/routes/tools_bp.py
import os
from flask import Blueprint, request, jsonify, g
from core.orphan_scanner import get_download_roots, scan_orphan_entries, delete_orphan_entries
from core.private_vault import get_vault_settings, save_vault_settings
from core.app_state_db import app_state_db

tools_bp = Blueprint('tools_bp', __name__)


def _actor_name():
    prof = g.get('profile')
    return (prof.get('login') or prof.get('name') or 'admin') if prof else 'admin'


def _sanitize_custom_roots(raw_roots):
    if raw_roots is None:
        return None, None
    if not isinstance(raw_roots, list) or not all(isinstance(x, str) for x in raw_roots):
        return None, 'Ожидался список строковых путей'
    clean = []
    for r in raw_roots:
        ap = os.path.abspath(r.strip())
        if not ap or os.path.dirname(ap) == ap:
            return None, f'Запрещено указывать корень диска/ФС: {r}'
        clean.append(ap)
    return clean, None


@tools_bp.route('/api/tools/orphans/roots')
def api_orphans_roots():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    return jsonify({'roots': get_download_roots()})


@tools_bp.route('/api/tools/orphans/scan', methods=['POST'])
def api_orphans_scan():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    data = request.get_json(silent=True) or {}
    custom_roots, err = _sanitize_custom_roots(data.get('roots'))
    if err:
        return jsonify({'success': False, 'error': err}), 400
    res = scan_orphan_entries(custom_roots=custom_roots)
    return jsonify({'success': True, **res})


@tools_bp.route('/api/tools/orphans/delete', methods=['POST'])
def api_orphans_delete():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    data = request.get_json(silent=True) or {}
    paths = data.get('paths')
    confirmed = bool(data.get('confirmed', False))
    use_trash = bool(data.get('use_trash', True))
    if not confirmed or not isinstance(paths, list) or not paths:
        return jsonify({'success': False, 'error': 'Требуется явное подтверждение и непустой список путей'}), 400
    custom_roots, err = _sanitize_custom_roots(data.get('custom_roots'))
    if err:
        return jsonify({'success': False, 'error': err}), 400
    ok, deleted, errors = delete_orphan_entries(paths, actor=_actor_name(), use_trash=use_trash, custom_roots=custom_roots)
    return jsonify({'success': ok, 'deleted': deleted, 'errors': errors, 'use_trash': use_trash}), (200 if deleted or ok else 400)


@tools_bp.route('/api/vault/settings', methods=['GET', 'POST'])
def api_vault_settings():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    if request.method == 'GET':
        return jsonify(get_vault_settings())
    data = request.get_json(silent=True) or {}
    saved = save_vault_settings(data.get('tags', ''), data.get('aggregate_mode', 'exclude'))
    app_state_db.add_audit_event('system', 'Private Vault обновлён', f"tags={','.join(saved['tags'])}", actor=_actor_name())
    return jsonify({'success': True, **saved})