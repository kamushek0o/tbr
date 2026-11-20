# web/routes/timers_bp.py
from flask import Blueprint, request, jsonify, g
from utils.config import cfg
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info
from core.smart_timers import (
    get_freeze_status, freeze_active_torrents, unfreeze_torrents,
    get_snooze_status, start_snooze, cancel_snooze,
    list_expirations, set_expiration, remove_expiration, _INACTIVE_STATES
)
from core.smart_tagging import (
    list_tagging_rules, add_tagging_rule, toggle_tagging_rule, delete_tagging_rule
)
from core.torrent_targets import list_targets, set_target, delete_target
from core.dnd_digest import get_dnd_settings, get_digest_settings
from core.app_state_db import app_state_db
from web.security import HASH_RE

timers_bp = Blueprint('timers_bp', __name__)


def _actor():
    p = g.get('profile')
    return (p.get('login') or p.get('name') or 'admin') if p else 'admin'


@timers_bp.route('/api/freeze/status')
def api_freeze_status():
    if g.get('role') != 'admin':
        return jsonify({'frozen': False, 'count': 0, 'active_count': 0}), 403
    st = get_freeze_status()
    active_cnt = 0
    if not st.get('frozen'):
        ip, port = detect_qbittorrent_port(cfg.config)
        live = get_live_torrent_info(ip, port) if port else {}
        active_cnt = sum(1 for info in live.values() if str(info.get('state', '')).lower() not in _INACTIVE_STATES)
    st['active_count'] = active_cnt
    return jsonify(st)


@timers_bp.route('/api/freeze/toggle', methods=['POST'])
def api_freeze_toggle():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    st = get_freeze_status()
    if st.get('frozen'):
        ok, msg, cnt = unfreeze_torrents(actor=_actor())
        return jsonify({'success': ok, 'frozen': False, 'count': cnt, 'message': msg})
    ok, msg, cnt = freeze_active_torrents(actor=_actor())
    return jsonify({'success': ok, 'frozen': ok, 'count': cnt, 'message': msg}), (200 if ok else 400)


@timers_bp.route('/api/snooze/status')
def api_snooze_status():
    if g.get('role') != 'admin':
        return jsonify({'active': False}), 403
    return jsonify(get_snooze_status())


@timers_bp.route('/api/snooze/start', methods=['POST'])
def api_snooze_start():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    data = request.get_json(silent=True) or {}
    try:
        mins = int(data.get('minutes') or 30)
        if not (1 <= mins <= 1440):
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Укажите от 1 до 1440 минут'}), 400
    mode = str(data.get('mode', 'pause')).strip()
    ok, msg = start_snooze(mins, mode=mode, actor=_actor())
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@timers_bp.route('/api/snooze/cancel', methods=['POST'])
def api_snooze_cancel():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    ok, msg = cancel_snooze(actor=_actor(), auto_triggered=False)
    return jsonify({'success': ok, 'message': msg})


@timers_bp.route('/api/expirations')
def api_expirations_list():
    if g.get('role') != 'admin':
        return jsonify({'items': []}), 403
    return jsonify({'items': list_expirations()})


@timers_bp.route('/api/expirations/set', methods=['POST'])
def api_expirations_set():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    data = request.get_json(silent=True) or {}
    h = str(data.get('hash', '')).strip()
    if not HASH_RE.fullmatch(h):
        return jsonify({'success': False, 'error': 'Некорректный хэш'}), 400
    try:
        hours = float(data.get('hours') or 0)
        target_bytes = int(data.get('target_uploaded_bytes') or 0)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Некорректные числовые значения'}), 400
    delete_files = bool(data.get('delete_files', False))
    ok, msg = set_expiration(h, hours=hours, target_up_bytes=target_bytes, delete_files=delete_files, actor=_actor())
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@timers_bp.route('/api/expirations/delete', methods=['POST'])
def api_expirations_delete():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    h = str((request.get_json(silent=True) or {}).get('hash', '')).strip()
    if not HASH_RE.fullmatch(h):
        return jsonify({'success': False, 'error': 'Некорректный хэш'}), 400
    return jsonify({'success': remove_expiration(h)})


@timers_bp.route('/api/targets')
def api_targets_list():
    return jsonify({'targets': list_targets()})


@timers_bp.route('/api/targets/set', methods=['POST'])
def api_targets_set():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    data = request.get_json(silent=True) or {}
    h = str(data.get('hash', '')).strip()
    if not HASH_RE.fullmatch(h):
        return jsonify({'success': False, 'error': 'Некорректный хэш'}), 400
    try:
        tr = float(data.get('target_ratio') or 0)
        tb = int(data.get('target_bytes') or 0)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Некорректные числовые значения'}), 400
    ok, msg = set_target(h, target_ratio=tr, target_bytes=tb, actor=_actor())
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@timers_bp.route('/api/targets/delete', methods=['POST'])
def api_targets_delete():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    h = str((request.get_json(silent=True) or {}).get('hash', '')).strip()
    if not HASH_RE.fullmatch(h):
        return jsonify({'success': False, 'error': 'Некорректный хэш'}), 400
    return jsonify({'success': delete_target(h)})


@timers_bp.route('/api/tagging/rules')
def api_tagging_list():
    if g.get('role') != 'admin':
        return jsonify({'rules': []}), 403
    return jsonify({'rules': list_tagging_rules()})


@timers_bp.route('/api/tagging/rules/add', methods=['POST'])
def api_tagging_add():
    if g.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    data = request.get_json(silent=True) or {}
    rid = add_tagging_rule(
        data.get('name', ''), data.get('match_field', 'tracker'),
        data.get('pattern', ''), data.get('target_tag', '')
    )
    if not rid:
        return jsonify({'success': False, 'error': 'Укажите паттерн и целевой тег'}), 400
    return jsonify({'success': True, 'id': rid})


@timers_bp.route('/api/tagging/rules/toggle', methods=['POST'])
def api_tagging_toggle():
    if g.get('role') != 'admin':
        return jsonify({'success': False}), 403
    rid = (request.get_json(silent=True) or {}).get('id')
    return jsonify({'success': bool(rid and toggle_tagging_rule(rid))})


@timers_bp.route('/api/tagging/rules/delete', methods=['POST'])
def api_tagging_delete():
    if g.get('role') != 'admin':
        return jsonify({'success': False}), 403
    rid = (request.get_json(silent=True) or {}).get('id')
    return jsonify({'success': bool(rid and delete_tagging_rule(rid))})


@timers_bp.route('/api/notifications/schedule', methods=['GET', 'POST'])
def api_notifications_schedule():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    if request.method == 'GET':
        return jsonify({'dnd': get_dnd_settings(), 'digest': get_digest_settings()})

    data = request.get_json(silent=True) or {}
    dnd, dig = data.get('dnd') or {}, data.get('digest') or {}

    cfg.set('DND_Enabled', str(bool(dnd.get('enabled', False))))
    cfg.set('DND_Start', str(dnd.get('start', '23:00'))[:5] or '23:00')
    cfg.set('DND_End', str(dnd.get('end', '08:00'))[:5] or '08:00')
    days = dnd.get('days') if isinstance(dnd.get('days'), list) else [0, 1, 2, 3, 4, 5, 6]
    cfg.set('DND_Days', ','.join(str(int(d)) for d in days if str(d).isdigit() and 0 <= int(d) <= 6))

    d_mode = str(dig.get('mode', 'off'))
    if d_mode not in ('off', 'daily', 'weekly'):
        d_mode = 'off'
    cfg.set('Digest_Mode', d_mode)
    cfg.set('Digest_Hour', str(max(0, min(23, int(dig.get('hour', 21) or 21)))))
    cfg.set('Digest_Weekday', str(max(0, min(6, int(dig.get('weekday', 6) or 6)))))
    cfg.save()

    app_state_db.add_audit_event('automation', 'Расписание DND/Дайджеста', f'dnd={dnd.get("enabled")}, digest={d_mode}', actor=_actor())
    return jsonify({'success': True, 'message': 'Расписание DND и дайджеста сохранено!'})