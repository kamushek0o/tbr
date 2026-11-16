# web/routes/automation_bp.py
from flask import Blueprint, request, jsonify

from utils.config import cfg
from core.automation import automation_engine

automation_bp = Blueprint('automation_bp', __name__)


@automation_bp.route('/api/automation', methods=['GET'])
def api_automation_get():
    return jsonify({
        'settings': {
            'enabled': cfg.getboolean('Auto_Enabled', False),
            'interval': cfg.getint('Auto_Interval_Min', 5),
            'has_tg_token': bool(cfg.get('TG_Bot_Token', '').strip()),
            'tg_chat_id': cfg.get('TG_Chat_ID', ''),
            'has_discord': bool(cfg.get('Discord_Webhook', '').strip())
        },
        'rules': automation_engine.get_rules()
    })


@automation_bp.route('/api/automation/settings', methods=['POST'])
def api_automation_settings():
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get('enabled', False))
    try:
        interval = max(1, min(1440, int(data.get('interval', 5))))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Интервал должен быть от 1 до 1440 мин.'}), 400

    tg_token = str(data.get('tg_token', '')).strip()
    tg_chat = str(data.get('tg_chat_id', '')).strip()
    discord = str(data.get('discord_webhook', '')).strip()

    if discord and not (discord.startswith('https://discord.com/api/webhooks/') or discord.startswith('https://discordapp.com/api/webhooks/')):
        return jsonify({'success': False, 'error': 'Некорректный URL Discord Webhook!'}), 400

    cfg.set('Auto_Enabled', str(enabled))
    cfg.set('Auto_Interval_Min', str(interval))
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
    name = str(data.get('name', '')).strip()[:64] or 'Правило'
    try:
        min_ratio = max(0.0, float(data.get('min_ratio') or 0))
        min_days = max(0.0, float(data.get('min_seed_days') or 0))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Некорректные числа Ratio или дней'}), 400

    if min_ratio <= 0 and min_days <= 0:
        return jsonify({'success': False, 'error': 'Укажите хотя бы Ratio > 0 или Дней > 0'}), 400

    action_pause = bool(data.get('action_pause', False))
    action_tag = str(data.get('action_tag', '')).strip()[:32]
    notify = bool(data.get('notify', True))

    rid = automation_engine.add_rule(name, min_ratio, min_days, action_pause, action_tag, notify)
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

    name = str(data.get('name', '')).strip()[:64] or 'Правило'
    try:
        min_ratio = max(0.0, float(data.get('min_ratio') or 0))
        min_days = max(0.0, float(data.get('min_seed_days') or 0))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Некорректные числа Ratio или дней'}), 400

    if min_ratio <= 0 and min_days <= 0:
        return jsonify({'success': False, 'error': 'Укажите хотя бы Ratio > 0 или Дней > 0'}), 400

    action_pause = bool(data.get('action_pause', False))
    action_tag = str(data.get('action_tag', '')).strip()[:32]
    notify = bool(data.get('notify', True))

    ok = automation_engine.update_rule(rid_int, name, min_ratio, min_days, action_pause, action_tag, notify)
    if not ok:
        return jsonify({'success': False, 'error': 'Правило не найдено'}), 404
    return jsonify({'success': True})


@automation_bp.route('/api/automation/rules/toggle', methods=['POST'])
def api_automation_toggle_rule():
    data = request.get_json(silent=True) or {}
    rid = data.get('id')
    if not rid:
        return jsonify({'success': False}), 400
    return jsonify({'success': automation_engine.toggle_rule(rid)})


@automation_bp.route('/api/automation/rules/delete', methods=['POST'])
def api_automation_delete_rule():
    data = request.get_json(silent=True) or {}
    rid = data.get('id')
    if not rid:
        return jsonify({'success': False}), 400
    return jsonify({'success': automation_engine.delete_rule(rid)})