# core/reliability.py
import os
import time
from utils.config import cfg
from utils.helpers import write_log
from core.app_state_db import app_state_db
from core.notifiers import notify_all
from core.qb_api import (
    recheck_torrents, add_torrent_tags,
    close_qbittorrent, launch_qbittorrent, get_qb_executable_path
)

_ERROR_STATES = ('error', 'missingfiles')
_CHECKING_STATES = ('checkingup', 'checkingdl', 'checkingresumedata')
_IO_ERROR_TAG = 'io-error'


def run_auto_recheck(ip, port, live):
    if not cfg.getboolean('AutoRecheck_Enabled', False) or not ip or not port or not live:
        return 0

    now = time.time()
    attempts = app_state_db.get_recheck_attempts()
    changed = False
    rechecked = 0

    for raw_hash, info in live.items():
        h = raw_hash.lower()
        state = str(info.get('state', '')).lower()
        tags = {tg.strip().lower() for tg in str(info.get('tags', '') or '').split(',') if tg.strip()}
        name = str(info.get('name') or h)

        if state in _CHECKING_STATES:
            continue

        if state not in _ERROR_STATES:
            if h in attempts and _IO_ERROR_TAG not in tags:
                del attempts[h]
                changed = True
            continue

        if _IO_ERROR_TAG in tags:
            continue

        if h not in attempts:
            if recheck_torrents(ip, port, raw_hash):
                attempts[h] = now
                changed = True
                rechecked += 1
                write_log('automation', f"Auto-Recheck: запущена перепроверка '{name}' ({state})")
                app_state_db.add_audit_event('automation', 'Auto-Recheck', f"Перепроверка '{name}' ({state})")
                notify_all("🔄 Auto-Recheck: ошибка чтения", [f"Раздача: {name}", "Запущена 1 автоматическая перепроверка файлов."])
        else:
            if (now - float(attempts[h] or 0)) >= 15.0:
                if add_torrent_tags(ip, port, raw_hash, _IO_ERROR_TAG):
                    write_log('automation', f"Auto-Recheck: повторная ошибка '{name}', выставлен тег {_IO_ERROR_TAG}")
                    app_state_db.add_audit_event('automation', 'Ошибка I/O подтверждена', f"Тег {_IO_ERROR_TAG} -> '{name}'")
                    notify_all("💥 Ошибка диска не устранена", [f"Раздача: {name}", f"После перепроверки ошибка осталась. Выставлен тег '{_IO_ERROR_TAG}', автопроверки остановлены."], critical=True)

    if changed:
        app_state_db.save_recheck_attempts(attempts)
    return rechecked


def run_watchdog(qb_available):
    if not cfg.getboolean('Watchdog_Enabled', False):
        return

    now = time.time()
    st = app_state_db.get_watchdog_state()
    timeout_min = max(2, min(10, cfg.getint('Watchdog_Timeout_Min', 3)))
    timeout_sec = timeout_min * 60

    if qb_available:
        if st.get('down_since') is not None or st.get('consecutive_restarts', 0) > 0 or st.get('halted'):
            was_restarted = st.get('consecutive_restarts', 0) > 0
            app_state_db.update_watchdog_state(consecutive_restarts=0, down_since=None, halted=0)
            if was_restarted:
                write_log('automation', "Watchdog: qBittorrent снова отвечает, счётчик сброшен")
                app_state_db.add_audit_event('system', 'Watchdog: восстановление', 'qBittorrent успешно ожил')
        return

    if st.get('halted'):
        return

    down_since = st.get('down_since')
    if down_since is None:
        app_state_db.update_watchdog_state(down_since=now)
        return

    if (now - float(down_since)) < timeout_sec:
        return

    last_restart = st.get('last_restart_at')
    if last_restart and (now - float(last_restart)) < 30.0:
        return

    restarts = int(st.get('consecutive_restarts') or 0)
    if restarts >= 2:
        app_state_db.update_watchdog_state(halted=1)
        write_log('automation', "Watchdog: фатальный сбой qBittorrent после 2 попыток перезапуска")
        app_state_db.add_audit_event('system', 'Watchdog: остановка', 'Фатальный сбой qB после 2 рестартов')
        notify_all("🚨 Фатальный сбой qBittorrent", ["qBittorrent не поднялся после 2 перезапусков подряд.", "Автоперезапуск сторожем остановлен до ручного вмешательства."], critical=True)
        return

    custom_exe = cfg.get('Watchdog_Exe_Path', '').strip()
    exe_path = custom_exe if (custom_exe and os.path.exists(custom_exe)) else get_qb_executable_path()

    new_count = restarts + 1
    app_state_db.update_watchdog_state(consecutive_restarts=new_count, last_restart_at=now)
    write_log('automation', f"Watchdog: qBittorrent не отвечает (>{timeout_min} мин), попытка перезапуска {new_count}/2")
    app_state_db.add_audit_event('system', 'Watchdog: перезапуск qB', f"Попытка {new_count}/2")
    notify_all("🐶 Watchdog: qBittorrent не отвечает", [f"Клиент не отвечает дольше {timeout_min} мин.", f"Перезапускаю... (попытка {new_count}/2)"], critical=True)

    if os.name == 'nt':
        close_qbittorrent()
        time.sleep(2.0)
        launch_qbittorrent(exe_path)
    else:
        write_log('automation', "Watchdog: в Docker/Linux локальный перезапуск процесса qB недоступен")