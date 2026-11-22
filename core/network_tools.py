# core/network_tools.py
import os
import re
import time
import socket
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.config import cfg
from utils.helpers import write_log
from core.qb_api import (
    detect_qbittorrent_port, _get_qb_json, get_live_torrent_info,
    get_transfer_info, is_qb_running, close_qbittorrent, launch_qbittorrent
)
from core.tracker_inspector import inspect_tracker_errors
from core.analytics_insights import detect_isp_throttling
from core.env_doctor import sanitize_text_for_github
from core.disaster_recovery import execute_panic_killswitch
from core.app_state_db import app_state_db
from core.notifiers import notify_all


def diagnose_bottleneck(db):
    """«Почему всё тормозит?» — диагностика узких горлышек в реальном времени."""
    ip, port = detect_qbittorrent_port(cfg.config)
    if not port:
        return {'success': False, 'issues': ['qBittorrent WebUI недоступен']}

    live = get_live_torrent_info(ip, port)
    tr = get_transfer_info(ip, port)
    prefs = _get_qb_json(ip, port, "app/preferences", timeout=2.0) or {}
    issues = []

    checking = sum(1 for v in live.values() if 'checking' in str(v.get('state', '')).lower())
    if checking > 0:
        issues.append(f"💽 Идёт проверка хеша ({checking} раздач) — диск может быть перегружен")

    if tr.get('use_alt_speed_limits'):
        issues.append("🐢 Включён альтернативный лимит скорости («Черепаха») в qBittorrent")
    elif int(tr.get('up_rate_limit') or 0) > 0:
        issues.append(f"🚦 Задан глобальный лимит отдачи в qB: {int(tr['up_rate_limit']) // 1024} KiB/s")

    if int(prefs.get('max_active_uploads') or 999) <= 3:
        issues.append(f"🎰 Мало активных слотов отдачи в настройках qB (max_active_uploads={prefs.get('max_active_uploads')})")

    err_map = inspect_tracker_errors(ip, port, live, force=False)
    timeout_cnt = sum(1 for e in err_map.values() if e.get('category') == 'timeout')
    if timeout_cnt >= 3:
        issues.append(f"🌐 Массовые таймауты трекеров ({timeout_cnt} раздач)")

    th = detect_isp_throttling(db, ip, port)
    if th.get('throttled'):
        issues.append(f"🚧 Обнаружена полка скорости ~{th['tier_mbps']} Мбит/с (возможен шейпинг провайдера)")

    if not issues:
        issues.append("📉 Узких мест в клиенте и сети не выявлено — вероятно, дефицит спроса со стороны пиров")

    return {'success': True, 'issues': issues, 'active_torrents': len(live)}


def ping_trackers_dns_tcp(max_hosts=25):
    """Пингер трекеров: только DNS + TCP handshake (без HTTP GET к announce URL)."""
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    hosts = {}
    for info in live.values():
        tr = str(info.get('tracker') or '').strip()
        if not tr or tr.startswith('**['):
            continue
        p = urllib.parse.urlparse(tr)
        if not p.hostname or p.scheme not in ('http', 'https', 'udp'):
            continue
        def_port = 443 if p.scheme == 'https' else (80 if p.scheme == 'http' else 6969)
        hosts[p.hostname.lower()] = (p.hostname.lower(), p.port or def_port, p.scheme)

    targets = list(hosts.values())[:max_hosts]

    def probe(host, t_port, scheme):
        t0 = time.monotonic()
        try:
            addrs = socket.getaddrinfo(host, t_port, type=socket.SOCK_STREAM)
            dns_ms = round((time.monotonic() - t0) * 1000.0, 1)
            if scheme == 'udp':
                return {'host': host, 'port': t_port, 'scheme': 'udp', 'dns_ok': True, 'tcp_ok': None, 'latency_ms': dns_ms, 'error': ''}
            t1 = time.monotonic()
            with socket.create_connection((addrs[0][4][0], t_port), timeout=3.0):
                tcp_ms = round((time.monotonic() - t1) * 1000.0, 1)
            return {'host': host, 'port': t_port, 'scheme': scheme, 'dns_ok': True, 'tcp_ok': True, 'latency_ms': tcp_ms, 'error': ''}
        except Exception as e:
            return {'host': host, 'port': t_port, 'scheme': scheme, 'dns_ok': False, 'tcp_ok': False, 'latency_ms': None, 'error': str(e)[:80]}

    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for fut in as_completed([pool.submit(probe, h, p, s) for h, p, s in targets]):
            results.append(fut.result())
    results.sort(key=lambda x: (x['latency_ms'] is None, x['latency_ms'] or 99999))
    return {'success': True, 'items': results}


def check_network_interface_guard():
    """Страж сетевого интерфейса qBittorrent."""
    enabled = cfg.getboolean('Interface_Guard_Enabled', False)
    ip, port = detect_qbittorrent_port(cfg.config)
    prefs = _get_qb_json(ip, port, "app/preferences", timeout=2.0) if port else None
    if not isinstance(prefs, dict):
        return {'enabled': enabled, 'ok': True, 'reason': 'qb_down', 'current': '', 'current_name': ''}

    cur_iface = str(prefs.get('current_network_interface') or '').strip()
    cur_name = str(prefs.get('current_network_interface_name') or cur_iface).strip()
    expected = cfg.get('Expected_Net_Interface', '').strip()
    if not enabled or not expected:
        return {'enabled': enabled, 'ok': True, 'current': cur_iface, 'current_name': cur_name}

    if cur_iface != expected and cur_name != expected:
        msg = f"Сетевой интерфейс qB изменился: '{expected}' → '{cur_name or cur_iface or 'Any'}'!"
        last_alert = cfg.getint('Interface_Last_Alert_Ts', 0)
        if (time.time() - last_alert) >= 300:
            cfg.set('Interface_Last_Alert_Ts', str(int(time.time())))
            cfg.save()
            app_state_db.add_audit_event('system', 'Страж интерфейса: несовпадение', msg)
            notify_all("🛡️ Страж интерфейса qBittorrent", [msg], critical=True)
            if cfg.getboolean('Interface_Guard_Panic', False):
                execute_panic_killswitch(kill_qb=False, actor='interface_guard')
        return {'enabled': True, 'ok': False, 'expected': expected, 'current': cur_iface, 'current_name': cur_name, 'message': msg}
    return {'enabled': True, 'ok': True, 'expected': expected, 'current': cur_iface, 'current_name': cur_name}


def _find_qb_log_path():
    if os.name == 'nt':
        cands = [
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'qBittorrent', 'logs', 'qbittorrent.log'),
            os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'qBittorrent', 'logs', 'qbittorrent.log'),
        ]
    else:
        cands = [
            '/config/qBittorrent/logs/qbittorrent.log',
            os.path.join(os.path.expanduser('~'), '.local', 'share', 'qBittorrent', 'logs', 'qbittorrent.log'),
        ]
    return next((p for p in cands if p and os.path.isfile(p)), '')


def read_sanitized_qb_log(lines_count=80):
    """Безопасное чтение последних N строк qbittorrent.log с маскировкой IP и пасскеев."""
    path = _find_qb_log_path()
    if not path:
        return False, "Файл qbittorrent.log не найден"
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()[-max(10, min(200, int(lines_count))):]
        text = sanitize_text_for_github("".join(lines))
        text = re.sub(r'\b\d{1,3}(?:\.\d{1,3}){3}\b', '<IP>', text)
        return True, text
    except Exception as e:
        return False, str(e)


def reanimate_qb(force_kill=False):
    """Удалённый реаниматор qB: мягкий или быстрый перезапуск."""
    if os.name != 'nt':
        return False, "Локальное управление процессом доступно только на Windows"
    write_log('system', f"Реаниматор qBittorrent (force={force_kill})")
    if is_qb_running():
        wait_sec = 2.0 if force_kill else 20.0
        closed = close_qbittorrent(max_wait_sec=wait_sec)
        if not closed and not force_kill:
            return False, "qBittorrent не завершился мягко за 20с. Используйте принудительный перезапуск."
    time.sleep(1.5)
    ok = launch_qbittorrent()
    app_state_db.add_audit_event('system', 'Реаниматор qB', f'restarted (ok={ok}, force={force_kill})', actor='admin')
    return ok, "qBittorrent перезапущен" if ok else "Не удалось запустить qBittorrent"