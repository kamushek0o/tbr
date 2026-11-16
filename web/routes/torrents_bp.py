# web/routes/torrents_bp.py
import os
import time
import shutil
from flask import Blueprint, request, jsonify

from utils.config import cfg
from utils.helpers import format_file_size, BT_BACKUP_PATH, write_error_log
from utils.bencode import decode_bencode, encode_bencode
from core.torrent_parser import get_all_torrents, force_clear_cache
from core.qb_api import (
    detect_qbittorrent_port, get_live_torrent_info, send_qb_command,
    is_qb_running, close_qbittorrent, launch_qbittorrent, get_qb_executable_path,
    scan_dead_torrents
)
from core.autostart import set_autostart, is_autostart_enabled
from web.security import HASH_RE

torrents_bp = Blueprint('torrents_bp', __name__)


@torrents_bp.route('/api/qb/status')
def api_qb_status():
    running = is_qb_running()
    ip, port = detect_qbittorrent_port(cfg.config)
    return jsonify({'running': running, 'ip': ip, 'port': port})


@torrents_bp.route('/api/qb/start', methods=['POST'])
def api_qb_start():
    ok = launch_qbittorrent()
    return jsonify({'success': ok, 'message': 'qBittorrent запущен' if ok else 'Не удалось запустить'})


@torrents_bp.route('/api/qb/stop', methods=['POST'])
def api_qb_stop():
    ok = close_qbittorrent()
    return jsonify({'success': ok, 'message': 'qBittorrent остановлен' if ok else 'Не удалось остановить'})


@torrents_bp.route('/api/qb/restart', methods=['POST'])
def api_qb_restart():
    close_qbittorrent()
    time.sleep(1.5)
    ok = launch_qbittorrent()
    return jsonify({'success': ok, 'message': 'qBittorrent перезапущен'})


@torrents_bp.route('/api/autostart/status')
def api_autostart_status():
    return jsonify({'enabled': is_autostart_enabled()})


@torrents_bp.route('/api/autostart/toggle', methods=['POST'])
def api_autostart_toggle():
    curr = is_autostart_enabled()
    ok, msg = set_autostart(not curr)
    return jsonify({'success': ok, 'enabled': not curr if ok else curr, 'message': msg})


@torrents_bp.route('/api/torrents')
def api_torrents():
    ip, port = detect_qbittorrent_port(cfg.config)
    data_dict = get_all_torrents(use_cache=False)
    live_info = get_live_torrent_info(ip, port) if port else {}

    result = []
    for t_id, static in data_dict.items():
        live = live_info.get(t_id, {})
        size = live.get('total_size', static.get('size', 1))
        uploaded = live.get('uploaded', static.get('uploaded', 0))
        ratio = round(uploaded / size, 4) if size > 0 else 0.0
        state = live.get('state', 'seeding' if static.get('active_seconds', 0) > 0 else 'unknown')
        save_path = live.get('save_path', static.get('save_path', ''))

        name = static.get('name', '')
        if not name or name.lower() == t_id.lower() or len(name) in (40, 64):
            if live.get('name'):
                name = live['name']
        if not name:
            name = t_id

        result.append({
            'hash': t_id,
            'name': name,
            'size': size,
            'size_fmt': format_file_size(size),
            'uploaded': uploaded,
            'uploaded_fmt': format_file_size(uploaded),
            'ratio': ratio,
            'state': state,
            'save_path': save_path,
            'active_seconds': static.get('active_seconds', 0)
        })
    result.sort(key=lambda x: str(x['name']).lower())
    return jsonify({'torrents': result, 'qb_connected': bool(port), 'qb_running': is_qb_running()})


@torrents_bp.route('/api/torrents/refresh', methods=['POST'])
def api_torrents_refresh():
    force_clear_cache()
    return jsonify({'status': 'ok'})


@torrents_bp.route('/api/torrents/scan_dead', methods=['POST'])
def api_torrents_scan_dead():
    ip, port = detect_qbittorrent_port(cfg.config)
    if not port:
        return jsonify({'success': False, 'error': 'qBittorrent недоступен'}), 400
    res = scan_dead_torrents(ip, port)
    if res.get('success'):
        for item in res.get('items', []):
            item['size_fmt'] = format_file_size(item.get('size', 0))
    return jsonify(res)


@torrents_bp.route('/api/torrents/action', methods=['POST'])
def api_torrent_action():
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    t_hash = data.get('hash', '')
    if action not in ('stop', 'start', 'setForceStart'):
        return jsonify({'success': False, 'error': 'Неизвестная команда'}), 400

    hashes = [h.strip() for h in str(t_hash).split('|') if h.strip()]
    if not hashes or not all(HASH_RE.fullmatch(h) for h in hashes):
        return jsonify({'success': False, 'error': 'Некорректные хэши'}), 400

    ip, port = detect_qbittorrent_port(cfg.config)
    if not port:
        return jsonify({'success': False, 'error': 'qBittorrent недоступен'}), 400
    return jsonify({'success': send_qb_command(ip, port, action, '|'.join(hashes))})


@torrents_bp.route('/api/torrents/action_all', methods=['POST'])
def api_torrents_action_all():
    data = request.get_json(silent=True) or {}
    action = data.get('action', 'stop')
    if action not in ('stop', 'start'):
        return jsonify({'success': False, 'error': 'Неизвестная команда'}), 400
    ip, port = detect_qbittorrent_port(cfg.config)
    if not port:
        return jsonify({'success': False, 'error': 'qBittorrent не запущен'}), 400
    ok = send_qb_command(ip, port, action, 'all')
    msg = "Все раздачи поставлены на паузу" if action == 'stop' else "Все раздачи возобновлены"
    return jsonify({'success': ok, 'message': msg})


@torrents_bp.route('/api/merger/run', methods=['POST'])
def api_merger_run():
    data = request.get_json(silent=True) or {}
    old_hash = str(data.get('old_hash', '')).strip()
    new_hash = str(data.get('new_hash', '')).strip()
    log = []

    if not HASH_RE.fullmatch(old_hash) or not HASH_RE.fullmatch(new_hash) or old_hash.lower() == new_hash.lower():
        return jsonify({'success': False, 'log': ['❌ Некорректные или одинаковые хэши торрентов!']}), 400

    old_file, new_file = None, None
    if os.path.exists(BT_BACKUP_PATH):
        for f in os.listdir(BT_BACKUP_PATH):
            if f.lower() == (old_hash.lower() + '.fastresume'):
                old_file = os.path.join(BT_BACKUP_PATH, f)
            if f.lower() == (new_hash.lower() + '.fastresume'):
                new_file = os.path.join(BT_BACKUP_PATH, f)

    if not old_file or not os.path.exists(old_file):
        return jsonify({'success': False, 'log': [f'❌ Файл {old_hash}.fastresume не найден!']}), 404
    if not new_file or not os.path.exists(new_file):
        return jsonify({'success': False, 'log': [f'❌ Файл {new_hash}.fastresume не найден!']}), 404

    exe_path = get_qb_executable_path()
    was_running = is_qb_running()

    try:
        if was_running:
            log.append("🛑 Завершаем qBittorrent во избежание порчи данных...")
            if not close_qbittorrent():
                raise RuntimeError("Не удалось завершить qBittorrent (возможно, клиент запущен от имени Администратора).")
            time.sleep(1.0)

        with open(old_file, 'rb') as f:
            old_data = decode_bencode(f.read())
        with open(new_file, 'rb') as f:
            new_data = decode_bencode(f.read())

        if not isinstance(old_data, dict) or not isinstance(new_data, dict):
            raise ValueError("Повреждённый формат .fastresume (ожидался словарь bencode).")

        fields = ['total_uploaded', 'total_downloaded', 'active_time', 'seeding_time', 'added_time', 'completed_time']
        copied = 0
        for fld in fields:
            fld_b = fld.encode('ascii')
            val = old_data.get(fld) if fld in old_data else old_data.get(fld_b)
            if val is not None:
                if fld_b in new_data or any(isinstance(k, bytes) for k in new_data.keys()):
                    new_data[fld_b] = val
                    new_data.pop(fld, None)
                else:
                    new_data[fld] = val
                    new_data.pop(fld_b, None)
                log.append(f"✅ Скопировано: {fld} = {val}")
                copied += 1

        if copied == 0:
            raise ValueError("Не найдено подходящих полей статистики для копирования!")

        encoded_bytes = encode_bencode(new_data)

        # Контрольная перепроверка собранного bencode перед записью на диск
        validated = decode_bencode(encoded_bytes)
        if not isinstance(validated, dict) or len(validated) != len(new_data):
            raise ValueError("Контрольная проверка нового bencode не пройдена!")
        log.append("🔍 Валидация нового bencode пройдена.")

        bak = new_file + '.bak'
        if not os.path.exists(bak):
            shutil.copy2(new_file, bak)
            log.append(f"📦 Бэкап создан: {os.path.basename(bak)}")

        # Атомарная запись через временный файл + fsync + replace
        tmp_file = new_file + '.tmp'
        try:
            with open(tmp_file, 'wb') as f:
                f.write(encoded_bytes)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, new_file)
        finally:
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass

        log.append("🎉 Статистика успешно и атомарно записана в .fastresume!")
        return jsonify({'success': True, 'log': log})
    except Exception as e:
        write_error_log("Ошибка merger API", e)
        log.append(f"❌ Ошибка: {e}")
        return jsonify({'success': False, 'log': log}), 500
    finally:
        if was_running and not is_qb_running():
            log.append("🚀 Перезапуск qBittorrent...")
            launch_qbittorrent(exe_path)