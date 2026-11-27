# web/routes/tuner_bp.py
import datetime
from flask import Blueprint, request, jsonify, g
from utils.config import cfg
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info
from core.disk_monitor import list_active_disks
from core.tuner_presets import POPULAR_APPS_CATALOG, APP_FRIENDLY_NAMES
from core.tuner_db import (
    update_tuner_state, list_tuner_profiles, get_tuner_profiles_map,
    save_tuner_profile, delete_tuner_profile, reset_builtin_presets,
    list_switch_rules, save_switch_rule, delete_switch_rule, move_switch_rule,
    get_tuner_history
)
from core.tuner_telemetry import list_running_processes_smart
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
    snap['profiles'] = list_tuner_profiles()
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    snap['available_disks'] = list_active_disks(live)
    return jsonify(snap)


@tuner_bp.route('/api/tuner/mode', methods=['POST'])
def api_tuner_mode():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    d = request.get_json(silent=True) or {}
    ok, msg = tuner_engine.set_mode(
        str(d.get('mode', 'off')).strip(),
        auto_switch=d.get('auto_switch'),
        is_manual=bool(d.get('is_manual', True)),
        override_policy=d.get('override_policy'),
        clear_override=bool(d.get('clear_override', False))
    )
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@tuner_bp.route('/api/tuner/settings', methods=['POST'])
def api_tuner_settings():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    d = request.get_json(silent=True) or {}
    upd = {}
    if 'poll_interval_sec' in d:
        upd['poll_interval_sec'] = max(2, min(30, int(d.get('poll_interval_sec') or 3)))
    if 'default_profile_id' in d and str(d['default_profile_id']) in get_tuner_profiles_map():
        upd['default_profile_id'] = str(d['default_profile_id'])
    if d.get('override_policy') in ('2h', 'until_window', 'until_rule'):
        upd['manual_override_policy'] = d['override_policy']
    update_tuner_state(**upd)
    return jsonify({'success': True})


@tuner_bp.route('/api/tuner/restore_baseline', methods=['POST'])
def api_tuner_restore_baseline():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    ok, msg = tuner_engine.restore_baseline('Ручной возврат исходных настроек qB')
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@tuner_bp.route('/api/tuner/profiles', methods=['GET', 'POST'])
def api_tuner_profiles():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    if request.method == 'GET':
        return jsonify({'profiles': list_tuner_profiles()})
    d = request.get_json(silent=True) or {}
    if d.get('reset_builtins'):
        return jsonify({'success': True, 'profiles': reset_builtin_presets()})
    if d.get('delete_id'):
        ok, msg = delete_tuner_profile(str(d['delete_id']))
        return jsonify({'success': ok, 'message': msg, 'profiles': list_tuner_profiles()}), (200 if ok else 400)
    if d.get('clone_from'):
        src = get_tuner_profiles_map().get(str(d['clone_from']))
        if not src:
            return jsonify({'success': False, 'error': 'Исходный профиль не найден'}), 404
        saved = save_tuner_profile('', d.get('name') or f"{src['name']} (копия)", d.get('icon') or src['icon'], src['config'], is_new=True)
        return jsonify({'success': True, 'profile': saved, 'profiles': list_tuner_profiles()})

    saved = save_tuner_profile(
        d.get('id', ''), d.get('name', 'Профиль'), d.get('icon', '⚙️'),
        d.get('config') or {}, is_new=bool(d.get('is_new', False))
    )
    return jsonify({'success': bool(saved), 'profile': saved, 'profiles': list_tuner_profiles()})


@tuner_bp.route('/api/tuner/rules', methods=['GET', 'POST'])
def api_tuner_rules():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    if request.method == 'GET':
        return jsonify({'rules': list_switch_rules()})
    d = request.get_json(silent=True) or {}
    if d.get('delete_id'):
        delete_switch_rule(d['delete_id'])
        return jsonify({'success': True, 'rules': list_switch_rules()})
    if d.get('move_id') and d.get('direction') in ('up', 'down'):
        move_switch_rule(d['move_id'], d['direction'])
        return jsonify({'success': True, 'rules': list_switch_rules()})
    rid = save_switch_rule(
        d.get('id'), d.get('name', 'Правило'),
        d.get('enabled', True), d.get('target_profile_id', 'comfort'),
        d.get('config') or {}
    )
    return jsonify({'success': True, 'id': rid, 'rules': list_switch_rules()})


@tuner_bp.route('/api/tuner/processes')
def api_tuner_processes():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    inc_sys = request.args.get('system', '0') == '1'
    return jsonify({'processes': list_running_processes_smart(include_system=inc_sys)})


@tuner_bp.route('/api/tuner/catalog')
def api_tuner_catalog():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    return jsonify({'catalog': POPULAR_APPS_CATALOG, 'friendly_map': APP_FRIENDLY_NAMES})
