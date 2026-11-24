# web/routes/tuner_bp.py
import datetime
from flask import Blueprint, request, jsonify, g
from utils.config import cfg
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info
from core.disk_monitor import list_active_disks
from core.tuner_db import (
    get_tuner_profiles, save_tuner_profile, reset_tuner_profile,
    get_switch_rules, save_switch_rules, get_tuner_history
)
from core.tuner_telemetry import list_running_processes
from core.tuner_engine import tuner_engine

tuner_bp = Blueprint('tuner_bp', __name__)


def _not_admin():
    return g.get('role') != 'admin'


@tuner_bp.route('/api/tuner/state')
def api_tuner_state():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    snap = tuner_engine.get_live_snapshot()
    hist = get_tuner_history(limit=30)
    for h in hist:
        h['time'] = datetime.datetime.fromtimestamp(h['ts']).strftime('%H:%M:%S')
    snap['history'] = hist
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    snap['available_disks'] = list_active_disks(live)
    return jsonify(snap)


@tuner_bp.route('/api/tuner/mode', methods=['POST'])
def api_tuner_mode():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    d = request.get_json(silent=True) or {}
    mode = str(d.get('mode', 'off')).strip()
    auto_sw = d.get('auto_switch')
    clear_ov = bool(d.get('clear_override', False))
    ov_pol = d.get('override_policy')
    is_manual = bool(d.get('is_manual', True))
    ok, msg = tuner_engine.set_mode(
        mode, auto_switch=auto_sw, is_manual=is_manual,
        override_policy=ov_pol, clear_override=clear_ov
    )
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@tuner_bp.route('/api/tuner/restore_baseline', methods=['POST'])
def api_tuner_restore_baseline():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    ok, msg = tuner_engine.restore_baseline('Ручной возврат эталона')
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@tuner_bp.route('/api/tuner/profiles', methods=['GET', 'POST'])
def api_tuner_profiles():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    if request.method == 'GET':
        return jsonify({'profiles': get_tuner_profiles()})
    d = request.get_json(silent=True) or {}
    reset_mode = d.get('reset_mode')
    if reset_mode in ('performance', 'comfort'):
        prof = reset_tuner_profile(reset_mode)
        return jsonify({'success': True, 'profile': prof})
    mode = d.get('mode')
    profile_data = d.get('profile')
    if mode not in ('performance', 'comfort') or not isinstance(profile_data, dict):
        return jsonify({'success': False, 'error': 'Некорректные данные профиля'}), 400
    saved = save_tuner_profile(mode, profile_data)
    return jsonify({'success': True, 'profile': saved})


@tuner_bp.route('/api/tuner/rules', methods=['GET', 'POST'])
def api_tuner_rules():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    if request.method == 'GET':
        return jsonify({'rules': get_switch_rules()})
    d = request.get_json(silent=True) or {}
    saved = save_switch_rules(d.get('rules') if isinstance(d.get('rules'), dict) else d)
    return jsonify({'success': True, 'rules': saved})


@tuner_bp.route('/api/tuner/processes')
def api_tuner_processes():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    return jsonify({'processes': list_running_processes()})
