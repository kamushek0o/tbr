# core/fastresume_merger.py
import os
import time
import shutil
import datetime
from utils.config import cfg
from utils.helpers import BT_BACKUP_PATH, format_file_size, write_error_log, write_log
from utils.bencode import decode_bencode, encode_bencode
from core.qb_api import (
    detect_qbittorrent_port, get_live_torrent_info, delete_torrents,
    is_qb_running, close_qbittorrent, launch_qbittorrent, get_qb_executable_path
)
from core.torrent_parser import force_clear_cache
from core.torrent_targets import handle_targets_on_merge
from core.app_state_db import app_state_db

VALID_DELETE_MODES = ('none', 'safe', 'force')
VALID_MERGE_MODES = ('add', 'replace')


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
    if not na or not nb or na == nb:
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
            'method': 'webui', 'old_hash': old_hash, 'new_hash': new_hash,
            'old_name': old_live.get('name', old_hash), 'delete_mode': delete_mode,
            'delete_files': delete_files, 'downgraded': downgraded,
            'src_path': src_path, 'dst_path': dst_path
        }, None

    new_file = _find_fastresume_file(new_hash)
    if new_file and os.path.exists(new_file):
        with open(new_file, 'rb') as f:
            disk_data = decode_bencode(f.read()) or {}
        disk_up = int(_get_bencode_val(disk_data, 'total_uploaded') or 0)
        if disk_up >= expected_up:
            return {
                'method': 'disk_only', 'old_hash': old_hash, 'new_hash': new_hash,
                'old_name': old_hash, 'delete_mode': delete_mode,
                'delete_files': False, 'downgraded': True, 'src_path': '', 'dst_path': ''
            }, None

    return None, "⚠️ WebUI недоступен и диск-проверка не пройдена — удаление заблокировано."


def run_fastresume_merge(old_hash, new_hash, delete_mode='none', merge_mode='add', force_duplicate=False):
    d_mode = delete_mode if delete_mode in VALID_DELETE_MODES else 'none'
    m_mode = merge_mode if merge_mode in VALID_MERGE_MODES else 'add'
    log = []

    if m_mode == 'add' and not force_duplicate:
        prev = app_state_db.get_merger_history(old_hash, new_hash)
        if prev:
            dt_str = datetime.datetime.fromtimestamp(prev[0]['created_at']).strftime('%d.%m.%Y %H:%M')
            return False, log, None, 409, {
                'is_duplicate': True,
                'merged_at': dt_str,
                'warning': f"Эти раздачи уже объединялись {dt_str}. Точно сложить ещё раз?"
            }

    old_file = _find_fastresume_file(old_hash)
    new_file = _find_fastresume_file(new_hash)
    if not old_file or not os.path.exists(old_file):
        return False, [f'❌ Файл {old_hash}.fastresume не найден!'], None, 404, None
    if not new_file or not os.path.exists(new_file):
        return False, [f'❌ Файл {new_hash}.fastresume не найден!'], None, 404, None

    ip, port = detect_qbittorrent_port(cfg.config)
    live_before = get_live_torrent_info(ip, port) if (d_mode != 'none' and port) else {}
    exe_path = get_qb_executable_path()
    was_running = is_qb_running()
    expected_up = 0

    try:
        if was_running:
            log.append("🛑 Завершаем qBittorrent (сброс дискового кэша)...")
            if not close_qbittorrent(max_wait_sec=30.0):
                raise RuntimeError("Не удалось завершить qBittorrent за 30с. Убедитесь, что WebUI доступен.")
            time.sleep(1.0)

        with open(old_file, 'rb') as f:
            old_data = decode_bencode(f.read())
        with open(new_file, 'rb') as f:
            new_data = decode_bencode(f.read())

        if not isinstance(old_data, dict) or not isinstance(new_data, dict):
            raise ValueError("Повреждённый формат .fastresume (ожидался bencode-словарь).")

        old_up = int(_get_bencode_val(old_data, 'total_uploaded') or 0)
        new_up = int(_get_bencode_val(new_data, 'total_uploaded') or 0)
        old_seed = int(_get_bencode_val(old_data, 'seeding_time') or 0)
        new_seed = int(_get_bencode_val(new_data, 'seeding_time') or 0)
        old_act = int(_get_bencode_val(old_data, 'active_time') or 0)
        new_act = int(_get_bencode_val(new_data, 'active_time') or 0)

        final_up = (old_up + new_up) if m_mode == 'add' else old_up
        final_seed = (old_seed + new_seed) if m_mode == 'add' else old_seed
        final_act = (old_act + new_act) if m_mode == 'add' else old_act
        expected_up = final_up

        def set_val(d, key, val):
            kb = key.encode('ascii')
            if kb in d or any(isinstance(k, bytes) for k in d.keys()):
                d[kb] = val
                d.pop(key, None)
            else:
                d[key] = val
                d.pop(kb, None)

        set_val(new_data, 'total_uploaded', final_up)
        set_val(new_data, 'seeding_time', final_seed)
        set_val(new_data, 'active_time', final_act)

        old_add = int(_get_bencode_val(old_data, 'added_time') or 0)
        new_add = int(_get_bencode_val(new_data, 'added_time') or 0)
        valid_adds = [x for x in (old_add, new_add) if x > 0]
        if valid_adds:
            set_val(new_data, 'added_time', min(valid_adds))

        if m_mode == 'add':
            log.append(f"➕ Режим СЛОЖЕНИЯ: {format_file_size(old_up)} + {format_file_size(new_up)} = {format_file_size(final_up)}")
            log.append(f"⏱️ Сидирование: {old_seed // 3600}ч + {new_seed // 3600}ч = {final_seed // 3600}ч")
        else:
            log.append(f"🔄 Режим ЗАМЕНЫ: перенесено {format_file_size(final_up)}")

        encoded_bytes = encode_bencode(new_data)
        validated = decode_bencode(encoded_bytes)
        if not isinstance(validated, dict) or len(validated) != len(new_data):
            raise ValueError("Контрольная проверка целостности bencode не пройдена!")

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
        app_state_db.add_merger_record(old_hash, new_hash, m_mode, old_up, new_up, final_up)
        uid = app_state_db.link_torrent_lineage(old_hash, new_hash)
        if uid:
            log.append(f"🔗 Личная история поколений связана (UID: {uid[:8]}...)")
        if handle_targets_on_merge(old_hash, new_hash, final_uploaded=final_up):
            log.append("🎯 Целевая планка (Goal) синхронизирована с новым объёмом.")

        log.append("🎉 Метаданные атомарно записаны в .fastresume!")
    except Exception as e:
        write_error_log("run_fastresume_merge", e)
        log.append(f"❌ Ошибка: {e}")
        if was_running and not is_qb_running():
            launch_qbittorrent(exe_path)
        return False, log, None, 500, None

    if was_running and not is_qb_running():
        log.append("🚀 Перезапуск qBittorrent...")
        launch_qbittorrent(exe_path)

    confirm_info = None
    if d_mode != 'none':
        log.append("🔎 Проверка подхвата клиентом и путей файлов...")
        confirm_info, warn = _evaluate_delete_plan(old_hash, new_hash, d_mode, expected_up, live_before)
        if warn:
            log.append(warn)
        elif confirm_info:
            if confirm_info['method'] == 'disk_only':
                log.append("ℹ️ WebUI недоступен: удаление файлов заблокировано (только .fastresume/.torrent).")
            elif confirm_info['downgraded']:
                log.append("🛡️ Пути пересекаются — удаление понижено до deleteFiles=false.")
            else:
                log.append("⚡ Готов к безопасному удалению исходника.")

    calc_info = {
        'source_up': old_up, 'target_up': new_up, 'final_up': final_up,
        'calc_fmt': f"{format_file_size(old_up)} + {format_file_size(new_up)} = {format_file_size(final_up)}"
    }
    return True, log, confirm_info, 200, calc_info


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
            write_log('merger', f"Удалён исходник {old_hash} ({act})")
            return True, [f"🗑️ Исходник удалён через WebUI {act}."]
        return False, ["❌ WebUI отклонил команду удаления."]

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
    return True, [f"🗑️ Удалены метаданные исходника: {', '.join(removed) or 'ничего'}."]