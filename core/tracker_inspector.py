# core/tracker_inspector.py
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.qb_api import get_torrent_trackers

_CACHE_LOCK = threading.Lock()
_TRACKER_ERR_CACHE = {'ts': 0.0, 'map': {}}
_CACHE_TTL = 45.0


def _classify_error(msg):
    low = str(msg or '').lower()
    if any(k in low for k in ('not registered', 'unregistered', 'not found', 'не зарегистрирован', 'не найдена', 'torrent not registered')):
        return 'unregistered', 'Не зарегистрирована'
    if any(k in low for k in ('passkey', 'unauthorized', 'auth', 'forbidden', '401', '403', 'invalid key', 'ключ', 'авториз')):
        return 'auth', 'Ошибка авторизации / passkey'
    if any(k in low for k in ('timed out', 'timeout', 'unreachable', 'connection', 'refused', 'reset', 'таймаут', 'host not found')):
        return 'timeout', 'Превышен таймаут / сеть'
    return 'other', 'Прочая ошибка трекера'


def inspect_tracker_errors(ip, port, live, force=False):
    if not port or not live:
        return {}
    now = time.time()
    with _CACHE_LOCK:
        if not force and (now - _TRACKER_ERR_CACHE['ts']) < _CACHE_TTL:
            return dict(_TRACKER_ERR_CACHE['map'])

    err_map = {}

    def check_hash(t_hash, info):
        state = str(info.get('state', '')).lower()
        if state in ('pausedup', 'pauseddl', 'stoppedup', 'stoppeddl'):
            return None
        trackers = get_torrent_trackers(ip, port, t_hash)
        real = [tr for tr in trackers if not str(tr.get('url', '')).startswith('**[') and tr.get('status', 0) != 0]
        if not real:
            return None

        # Берём первую критическую ошибку (status == 4), не маскируя её успехом доп. трекеров
        for tr in real:
            if tr.get('status') == 4:
                raw_msg = str(tr.get('msg') or '').strip() or 'Трекер не отвечает'
                cat, cat_lbl = _classify_error(raw_msg)
                return {
                    'category': cat,
                    'category_label': cat_lbl,
                    'message': raw_msg
                }
        return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(check_hash, h, inf): h.lower() for h, inf in live.items()}
        for fut in as_completed(futs):
            hl = futs[fut]
            try:
                res = fut.result()
                if res:
                    err_map[hl] = res
            except Exception:
                pass

    with _CACHE_LOCK:
        _TRACKER_ERR_CACHE['ts'] = now
        _TRACKER_ERR_CACHE['map'] = dict(err_map)
    return err_map