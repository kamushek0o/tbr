# core/fastresume_merger.py
import os
import time
import shutil
from utils.config import cfg
from utils.helpers import BT_BACKUP_PATH, write_error_log, write_log
from utils.bencode import decode_bencode, encode_bencode
from core.qb_api import (
    detect_qbittorrent_port, get_live_torrent_info, delete_torrents,
    is_qb_running, close_qbittorrent, launch_qbittorrent, get_qb_executable_path
)
from core.torrent_parser import force_clear_cache
from core.torrent_targets import transfer_target_on_merge

VALID_DELETE_MODES = ('none', 'safe', 'force')
STAT_FIELDS = ('total_uploaded', 'total_downloaded', 'active_time', 'seeding_time', 'added_time', 'completed_time')


def _find_fastresume_file(t_hash):
    if not os.path.exists(BT_BACKUP_PATH):
        return None
    target = t_hash.lower() + '.fastresume'
    for f in os.listdir(BT_BACKUP_PATH):
        if f.lower() == target:
            return os.path.join(BT_BACKUP_PATH, f)
    return None


def _get_bencode_val(data, key):
    if key in data:
        return data[key]
    return data.get(key.encode('ascii'))


def _norm_path(p):
    if not p or not str(p).strip():
        return ''
    return os.path.normcase(os.path.normpath(os.path.abspath(str(p).strip())))


def paths_overlap(path_a, path_b):
    na = _norm_path(path_a)
    nb = _norm_path(path_b)
    if not na or not nb:
        return True
    if na == nb:
        return True
    try:
        common = os.path.commonpath([na, nb])
        return common == na or common == nb
    except ValueError:
        return False


def _wait_for_target_live(ip, port, new_hash, timeout_sec=12.0):
    deadline = time.monotonic() + timeout_sec
    nh = new_hash.lower()
    while time.monotonic() < deadline:
        live = get_live_torrent_info(ip, port)
        if live:
            for k, v in live.items():
                if k.lower() == nh:
                    return live, v
        time.sleep(1.2)
    return {}, None


def _evaluate_delete_plan(old_hash, new_hash, delete_mode, expected_up, live_before):
    ip, port = detect_qbittorrent_port(cfg.config)
    live_after, new_live = _wait_for_target_live(ip, port, new_hash, timeout_sec=12.0) if port else ({}, None)
    oh = old_hash.lower()

    if new_live is not None:
        new_up = int(new_live.get('uploaded', 0) or 0)
        if expected_up > 0 and new_up < expected_up:
            return None, f"⚠️ WebUI: статистика получателя не подтверждена ({new_up} < {expected_up}). Удаление заблокировано."

        old_live = next((v for k, v in live_after.items() if k.lower() == oh), None) or \
                   next((v for k, v in live_before.items() if k.lower() == oh), {})
        src_path = str(old_live.get('content_path') or old_live.get('save_path') or '')
        dst_path = str(new_live.get('content_path') or new_live.get('save_path') or '')

        if delete_mode == 'safe':
            overlap = paths_overlap(src_path, dst_path)
            delete_files = not overlap
            downgraded = overlap
        else:
            delete_files = True
            downgraded = False

        return {
            'method': 'webui',
            'old_hash': old_hash,
            'new_hash': new_hash,
            'old_name': old_live.get('name', old_hash),
            'delete_mode': delete_mode,
            'delete_files': delete_files,
            'downgraded': downgraded,
            'src_path': src_path,
            'dst_path': dst_path
        }, None

    new_file = _find_fastresume_file(new_hash)
    if new_file and os.path.exists(new_file):
        with open(new_file, 'rb') as f:
            disk_data = decode_bencode(f.read()) or {}
        disk_up = int(_get_bencode_val(disk_data, 'total_uploaded') or 0)
        if disk_up >= expected_up:
            return {
                'method': 'disk_only',
                'old_hash': old_hash,
                'new_hash': new_hash,
                'old_name': old_hash,
                'delete_mode': delete_mode,
                'delete_files': False,
                'downgraded': True,
                'src_path': '',
                'dst_path': ''
            }, None

    return None, "⚠️ WebUI недоступен и диск-проверка не пройдена — удаление заблокировано."


def run_fastresume_merge(old_hash, new_hash, delete_mode='none'):
    mode = delete_mode if delete_mode in VALID_DELETE_MODES else 'none'
    log = []

    old_file = _find_fastresume_file(old_hash)
    new_file = _find_fastresume_file(new_hash)
    if not old_file or not os.path.exists(old_file):
        return False, [f'❌ Файл {old_hash}.fastresume не найден!'], None, 404
    if not new_file or not os.path.exists(new_file):
        return False, [f'❌ Файл {new_hash}.fastresume не найден!'], None, 404

    ip, port = detect_qbittorrent_port(cfg.config)
    live_before = get_live_torrent_info(ip, port) if (mode != 'none' and port) else {}
    exe_path = get_qb_executable_path()
    was_running = is_qb_running()
    expected_up = 0

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

        copied = 0
        for fld in STAT_FIELDS:
            fld_b = fld.encode('ascii')
            val = _get_bencode_val(old_data, fld)
            if val is not None:
                if fld == 'total_uploaded':
                    expected_up = int(val)
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
        validated = decode_bencode(encoded_bytes)
        if not isinstance(validated, dict) or len(validated) != len(new_data):
            raise ValueError("Контрольная проверка нового bencode не пройдена!")
        log.append("🔍 Валидация нового bencode пройдена.")

        bak = new_file + '.bak'
        if not os.path.exists(bak):
            shutil.copy2(new_file, bak)
            log.append(f"📦 Бэкап создан: {os.path.basename(bak)}")

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

        force_clear_cache()
        if transfer_target_on_merge(old_hash, new_hash):
            log.append("🎯 Целевая планка (Goal) автоматически перенесена на новый хэш.")
        log.append("🎉 Статистика успешно и атомарно записана в .fastresume!")
    except Exception as e:
        write_error_log("Ошибка merger API", e)
        log.append(f"❌ Ошибка: {e}")
        if was_running and not is_qb_running():
            log.append("🚀 Перезапуск qBittorrent...")
            launch_qbittorrent(exe_path)
        return False, log, None, 500

    if was_running and not is_qb_running():
        log.append("🚀 Перезапуск qBittorrent...")
        launch_qbittorrent(exe_path)

    confirm_info = None
    if mode != 'none':
        log.append("🔎 Проверка подхвата получателя и пересечения путей...")
        confirm_info, warn = _evaluate_delete_plan(old_hash, new_hash, mode, expected_up, live_before)
        if warn:
            log.append(warn)
        elif confirm_info:
            if confirm_info['method'] == 'disk_only':
                log.append("ℹ️ WebUI недоступен: удаление файлов на диске заблокировано (доступно только удаление метаданных из BT_backup).")
            elif confirm_info['downgraded']:
                log.append("🛡️ Пути совпадают или вложены — режим понижен до удаления только торрента (deleteFiles=false).")
            else:
                log.append("⚡ Проверка пройдена. Ожидание подтверждения удаления исходника...")

    return True, log, confirm_info, 200


def execute_source_deletion(old_hash, new_hash, delete_mode):
    mode = delete_mode if delete_mode in ('safe', 'force') else 'safe'
    old_file = _find_fastresume_file(old_hash)
    new_file = _find_fastresume_file(new_hash)
    if not new_file or not os.path.exists(new_file):
        return False, ["❌ Получатель не найден на диске, удаление отменено."]

    with open(new_file, 'rb') as f:
        new_disk = decode_bencode(f.read()) or {}
    expected_up = int(_get_bencode_val(new_disk, 'total_uploaded') or 0)

    plan, err = _evaluate_delete_plan(old_hash, new_hash, mode, expected_up, {})
    if err or not plan:
        return False, [err or "❌ Не удалось подтвердить состояние получателя."]

    if plan['method'] == 'webui':
        ip, port = detect_qbittorrent_port(cfg.config)
        ok = delete_torrents(ip, port, old_hash, delete_files=plan['delete_files'])
        force_clear_cache()
        if ok:
            act = "с файлами на диске (deleteFiles=true)" if plan['delete_files'] else "без удаления файлов (deleteFiles=false)"
            write_log('merger', f"Удалён исходник {old_hash} ({act}) после мерджа в {new_hash}")
            return True, [f"🗑️ Исходник удалён через WebUI {act}."]
        return False, ["❌ WebUI отклонил удаление исходника."]

    removed = []
    if old_file and os.path.exists(old_file):
        os.remove(old_file)
        removed.append(os.path.basename(old_file))
    for ext in ('.torrent', '.fastresume.bak'):
        cand = os.path.join(BT_BACKUP_PATH, old_hash.lower() + ext)
        if os.path.exists(cand):
            os.remove(cand)
            removed.append(os.path.basename(cand))
    force_clear_cache()
    write_log('merger', f"WebUI недоступен; удалены метаданные исходника {old_hash}: {removed}")
    return True, [f"🗑️ WebUI недоступен. Удалены только метаданные из BT_backup: {', '.join(removed) or 'ничего'}."]