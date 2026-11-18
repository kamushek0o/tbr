# web/routes/automation_bp.py
from flask import Blueprint, request, jsonify

from utils.config import cfg
from core.automation import automation_engine, VALID_TIME_MODES, VALID_SPEED_OPS

automation_bp = Blueprint('automation_bp', __name__)


def _parse_rule_payload(data):
    name = str(data.get('name', '')).strip()[:64] or 'Правило'
    time_mode = str(data.get('time_mode', 'seeding_time')).strip()
    if time_mode not in VALID_TIME_MODES:
        time_mode = 'seeding_time'

    try:
        min_ratio = max(0.0, float(data.get('min_ratio') or 0))
        min_days = max(0.0, float(data.get('min_seed_days') or 0))
        min_up_bytes = max(0, int(data.get('min_uploaded_bytes') or 0))
        speed_op = str(data.get('speed_op', '') or '').strip()
        if speed_op not in VALID_SPEED_OPS:
            speed_op = ''
        speed_bytes = max(0.0, float(data.get('speed_bytes') or 0))
        speed_win = max(1, min(10080, int(data.get('speed_window_min') or 60)))
    except (ValueError, TypeError):
        return None, 'Некорректные числовые параметры правила'

    use_speed = (speed_op in ('>=', '<') and speed_bytes > 0)
    if min_ratio <= 0 and min_days <= 0 and min_up_bytes <= 0 and not use_speed:
        return None, 'Укажите хотя бы одно условие (Ratio, Время, Отдано или Среднюю скорость)'

    return {
        'name': name, 'time_mode': time_mode, 'min_ratio': min_ratio,
        'min_seed_days': min_days, 'min_uploaded_bytes': min_up_bytes,
        'speed_op': speed_op if use_speed else '', 'speed_bytes': speed_bytes if use_speed else 0.0,
        'speed_window_min': speed_win, 'action_pause': bool(data.get('action_pause', False)),
        'action_tag': str(data.get('action_tag', '')).strip()[:32],
        'action_remove_tag': str(data.get('action_remove_tag', '')).strip()[:32],
        'notify': bool(data.get('notify', True))
    }, None


@automation_bp.route('/api/automation', methods=['GET'])
def api_automation_get():
    return jsonify({
        'settings': {
            'enabled': cfg.getboolean('Auto_Enabled', False),
            'interval': cfg.getint('Auto_Interval_Min', 5),
            'has_tg_token': bool(cfg.get('TG_Bot_Token', '').strip()),
            'tg_chat_id': cfg.get('TG_Chat_ID', ''),
            'has_discord': bool(cfg.get('Discord_Webhook', '').strip()),
            'alert_disk_gib': cfg.getint('Alert_Disk_Min_GiB', 0),
            'alert_qb_down': cfg.getboolean('Alert_QB_Down', False)
        },
        'rules': automation_engine.get_rules()
    })


@automation_bp.route('/api/automation/settings', methods=['POST'])
def api_automation_settings():
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get('enabled', False))
    try:
        interval = max(1, min(1440, int(data.get('interval', 5))))
        alert_disk = max(0, min(100000, int(data.get('alert_disk_gib', 0) or 0)))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Некорректные числовые параметры'}), 400

    tg_token = str(data.get('tg_token', '')).strip()
    tg_chat = str(data.get('tg_chat_id', '')).strip()
    discord = str(data.get('discord_webhook', '')).strip()

    if discord and not (discord.startswith('https://discord.com/api/webhooks/') or discord.startswith('https://discordapp.com/api/webhooks/')):
        return jsonify({'success': False, 'error': 'Некорректный URL Discord Webhook!'}), 400

    cfg.set('Auto_Enabled', str(enabled))
    cfg.set('Auto_Interval_Min', str(interval))
    cfg.set('Alert_Disk_Min_GiB', str(alert_disk))
    cfg.set('Alert_QB_Down', str(bool(data.get('alert_qb_down', False))))
    if tg_token:
        cfg.set('TG_Bot_Token', tg_token)
    cfg.set('TG_Chat_ID', tg_chat)
    if discord:
        cfg.set('Discord_Webhook', discord)
    cfg.save()

    return jsonify({'success': True, 'message': 'Настройки автопилота сохранены!'})


@automation_bp.route('/api/automation/test', methods=['POST'])
def api_automation_test():
    ok, results = automation_engine.test_notifications()
    return jsonify({'success': ok, 'message': ' | '.join(results)})


@automation_bp.route('/api/automation/run_now', methods=['POST'])
def api_automation_run_now():
    cnt = automation_engine.run_cycle()
    return jsonify({'success': True, 'triggered': cnt, 'message': f'Проверка завершена. Сработало раздач: {cnt}'})


@automation_bp.route('/api/automation/rules', methods=['POST'])
def api_automation_add_rule():
    data = request.get_json(silent=True) or {}
    parsed, err = _parse_rule_payload(data)
    if err:
        return jsonify({'success': False, 'error': err}), 400
    rid = automation_engine.add_rule(**parsed)
    return jsonify({'success': bool(rid), 'id': rid})


@automation_bp.route('/api/automation/rules/update', methods=['POST'])
def api_automation_update_rule():
    data = request.get_json(silent=True) or {}
    rid = data.get('id')
    if not rid:
        return jsonify({'success': False, 'error': 'Не указан ID правила'}), 400
    try:
        rid_int = int(rid)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Некорректный ID правила'}), 400
    parsed, err = _parse_rule_payload(data)
    if err:
        return jsonify({'success': False, 'error': err}), 400
    ok = automation_engine.update_rule(rid_int, **parsed)
    return jsonify({'success': ok}), (200 if ok else 404)


@automation_bp.route('/api/automation/rules/toggle', methods=['POST'])
def api_automation_toggle_rule():
    rid = (request.get_json(silent=True) or {}).get('id')
    if not rid:
        return jsonify({'success': False}), 400
    return jsonify({'success': automation_engine.toggle_rule(rid)})


@automation_bp.route('/api/automation/rules/delete', methods=['POST'])
def api_automation_delete_rule():
    rid = (request.get_json(silent=True) or {}).get('id')
    if not rid:
        return jsonify({'success': False}), 400
    return jsonify({'success': automation_engine.delete_rule(rid)})