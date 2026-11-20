# web/routes/safety_bp.py
from flask import Blueprint, request, jsonify, g
from utils.config import cfg
from core.soft_trash import list_trash_items, restore_trash_item, purge_trash_item, cleanup_expired_trash
from core.config_vault import create_config_backup, list_config_backups, diff_config_backups, restore_config_backup, detect_qb_config_dir
from core.env_doctor import run_environment_doctor, generate_github_issue_report, probe_onboarding_defaults
from core.app_state_db import app_state_db

safety_bp = Blueprint('safety_bp', __name__)


def _require_admin():
    return g.get('role') != 'admin'


@safety_bp.route('/api/trash')
def api_trash_list():
    if _require_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    cleanup_expired_trash()
    return jsonify({'items': list_trash_items(), 'ttl_days': cfg.getint('Trash_TTL_Days', 7)})


@safety_bp.route('/api/trash/restore', methods=['POST'])
def api_trash_restore():
    if _require_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    item_id = str((request.get_json(silent=True) or {}).get('id', '')).strip()
    ok, msg = restore_trash_item(item_id)
    if ok:
        app_state_db.add_audit_event('system', 'Восстановление из корзины', msg, actor='admin')
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@safety_bp.route('/api/trash/purge', methods=['POST'])
def api_trash_purge():
    if _require_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    item_id = str((request.get_json(silent=True) or {}).get('id', '')).strip()
    ok, msg = purge_trash_item(item_id)
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@safety_bp.route('/api/qb_vault')
def api_qb_vault_list():
    if _require_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    return jsonify({'backups': list_config_backups(), 'config_dir': detect_qb_config_dir()})


@safety_bp.route('/api/qb_vault/set_dir', methods=['POST'])
def api_qb_vault_set_dir():
    if _require_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    path = str((request.get_json(silent=True) or {}).get('config_dir', '')).strip()
    cfg.set('QB_Config_Dir', path)
    cfg.save()
    return jsonify({'success': True, 'config_dir': detect_qb_config_dir()})


@safety_bp.route('/api/qb_vault/backup', methods=['POST'])
def api_qb_vault_backup():
    if _require_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    ok, res = create_config_backup(reason='manual')
    if ok:
        app_state_db.add_audit_event('system', 'Бэкап конфига qB', res.get('name', ''), actor='admin')
        return jsonify({'success': True, **res})
    return jsonify({'success': False, 'error': res}), 400


@safety_bp.route('/api/qb_vault/diff', methods=['POST'])
def api_qb_vault_diff():
    if _require_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    d = request.get_json(silent=True) or {}
    ok, out = diff_config_backups(d.get('snap_a', ''), d.get('snap_b', ''), d.get('filename', ''))
    return jsonify({'success': ok, 'diff': out if ok else '', 'error': None if ok else out}), (200 if ok else 400)


@safety_bp.route('/api/qb_vault/restore', methods=['POST'])
def api_qb_vault_restore():
    if _require_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    name = str((request.get_json(silent=True) or {}).get('name', '')).strip()
    ok, msg = restore_config_backup(name)
    if ok:
        app_state_db.add_audit_event('system', 'Восстановление конфига qB', name, actor='admin')
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@safety_bp.route('/api/doctor/check')
def api_doctor_check():
    if _require_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    diag = run_environment_doctor()
    return jsonify({'diag': diag, 'report_md': generate_github_issue_report(diag)})


@safety_bp.route('/api/onboarding/status')
def api_onboarding_status():
    if _require_admin():
        return jsonify({'completed': True})
    return jsonify(probe_onboarding_defaults())


@safety_bp.route('/api/onboarding/complete', methods=['POST'])
def api_onboarding_complete():
    if _require_admin():
        return jsonify({'success': False}), 403
    d = request.get_json(silent=True) or {}
    if not d.get('skipped'):
        if d.get('qb_ip') is not None:
            cfg.set('WebUI_Address', str(d.get('qb_ip')).strip())
        if d.get('qb_port') is not None:
            cfg.set('WebUI_Port', str(d.get('qb_port')).strip())
        if d.get('qb_user'):
            cfg.set('WebUI_User', str(d.get('qb_user')).strip())
        if d.get('qb_password'):
            cfg.set('WebUI_Password', str(d.get('qb_password')))
        if d.get('max_channel_mbps'):
            cfg.set('Max_Channel_Mbps', str(max(10, min(100000, int(d.get('max_channel_mbps'))))))
        if d.get('monitored_disk') is not None:
            cfg.set('Monitored_Disk_Path', str(d.get('monitored_disk')).strip())
    cfg.set('Onboarding_Completed', 'True')
    cfg.save()
    return jsonify({'success': True})