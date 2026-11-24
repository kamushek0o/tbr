# core/analytics_insights.py
import time
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.helpers import format_file_size
from core.qb_api import get_torrent_peers
from core.records_service import (  # noqa: F401
    get_heatmap_365, get_records_and_comparisons, detect_isp_throttling
)

_CLIENTS_LOCK = threading.Lock()
_CLIENTS_CACHE = {'ts': 0.0, 'data': None}
_CLIENTS_TTL = 900.0

_INSIGHTS_LOCK = threading.Lock()
_INSIGHTS_CACHE = {}
_INSIGHTS_TTL = 300.0


def invalidate_insights_cache():
    with _INSIGHTS_LOCK:
        _INSIGHTS_CACHE.clear()


def get_cached_insights(cache_key):
    now = time.time()
    with _INSIGHTS_LOCK:
        entry = _INSIGHTS_CACHE.get(cache_key)
        if entry and (now - entry['ts']) < _INSIGHTS_TTL:
            return dict(entry['data'])
    return None


def set_cached_insights(cache_key, data):
    with _INSIGHTS_LOCK:
        _INSIGHTS_CACHE[cache_key] = {'ts': time.time(), 'data': dict(data)}


def fetch_torrent_peers_safe(ip, port, t_hash):
    if not port or not t_hash:
        return []
    raw = get_torrent_peers(ip, port, t_hash)
    peers = raw.get('peers') or {}
    if not isinstance(peers, dict):
        return []
    out = []
    for p in peers.values():
        if not isinstance(p, dict):
            continue
        up = int(p.get('up_speed', 0) or 0)
        dl = int(p.get('dl_speed', 0) or 0)
        prog = round(float(p.get('progress', 0.0) or 0.0) * 100.0, 1)
        out.append({
            'client': str(p.get('client') or 'Unknown').strip() or 'Unknown',
            'progress': prog, 'up_speed': up, 'up_speed_fmt': f"{format_file_size(up)}/s",
            'dl_speed': dl, 'dl_speed_fmt': f"{format_file_size(dl)}/s",
            'flags': str(p.get('flags') or ''), 'country_code': str(p.get('country_code') or '').upper()[:4]
        })
    out.sort(key=lambda x: x['up_speed'], reverse=True)
    return out


def _classify_peer_client(raw_client):
    low = str(raw_client or '').lower()
    for key, label in (
        ('qbittorrent', 'qBittorrent'), ('transmission', 'Transmission'), ('utorrent', 'uTorrent'),
        ('µtorrent', 'uTorrent'), ('deluge', 'Deluge'), ('biglybt', 'BiglyBT'),
        ('aria2', 'Aria2'), ('tixati', 'Tixati'), ('vuze', 'Vuze'), ('azureus', 'Vuze'),
        ('bittorrent', 'BitTorrent'), ('libtorrent', 'libtorrent')
    ):
        if key in low:
            return label
    return 'Прочие'


def get_peer_clients_breakdown(ip, port, live, force=False):
    now = time.time()
    with _CLIENTS_LOCK:
        if not force and _CLIENTS_CACHE['data'] is not None and (now - _CLIENTS_CACHE['ts']) < _CLIENTS_TTL:
            return dict(_CLIENTS_CACHE['data'])
    if not port or not live:
        return {'labels': [], 'values': [], 'total_peers': 0, 'cached_at': int(now)}

    active_hashes = [
        h for h, inf in sorted(
            live.items(),
            key=lambda kv: int(kv[1].get('num_leechs', 0) or 0) + int(kv[1].get('num_seeds', 0) or 0),
            reverse=True
        )
        if int(inf.get('num_leechs', 0) or 0) + int(inf.get('num_seeds', 0) or 0) > 0
    ][:40]

    counts, total_peers = {}, 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for fut in as_completed([pool.submit(fetch_torrent_peers_safe, ip, port, h) for h in active_hashes]):
            try:
                for p in fut.result():
                    fam = _classify_peer_client(p['client'])
                    counts[fam] = counts.get(fam, 0) + 1
                    total_peers += 1
            except Exception:
                pass

    sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    res = {'labels': [k for k, _ in sorted_items], 'values': [v for _, v in sorted_items], 'total_peers': total_peers, 'cached_at': int(now)}
    with _CLIENTS_LOCK:
        _CLIENTS_CACHE['ts'] = now
        _CLIENTS_CACHE['data'] = dict(res)
    return res


def get_tracker_analytics(db, summaries, live=None, period='7d', allowed_hashes=None):
    per = period if period in ('7d', '30d', 'all') else '7d'
    live_lower = {k.lower(): v for k, v in (live or {}).items()}
    allowed = {h.lower() for h in allowed_hashes} if allowed_hashes is not None else None
    domain_by_hash, all_up_by_hash = {}, {}

    for s in summaries:
        hl = (s.get('hash_id') or s.get('hash') or '').lower()
        if not hl or (allowed is not None and hl not in allowed):
            continue
        lv = live_lower.get(hl, {})
        tr_url = str(lv.get('tracker') or '').strip() or (str(s['trackers'][0] or '').strip() if s.get('trackers') else '')
        host = urllib.parse.urlparse(tr_url).netloc.lower().split(':')[0] if tr_url else ''
        domain_by_hash[hl] = host or 'Без трекера / DHT'
        all_up_by_hash[hl] = int(lv.get('uploaded', s.get('uploaded', 0)) or 0)

    vol_map = all_up_by_hash if per == 'all' else db.get_torrents_positive_deltas(time.time() - (30 if per == '30d' else 7) * 86400, allowed_hashes=domain_by_hash.keys())
    by_domain = {}
    for hl, dom in domain_by_hash.items():
        val = int(vol_map.get(hl, 0) or 0)
        if val > 0:
            by_domain[dom] = by_domain.get(dom, 0) + val

    sorted_dom = sorted(by_domain.items(), key=lambda x: x[1], reverse=True)
    top = sorted_dom[:9] + ([('Другие', sum(v for _, v in sorted_dom[9:]))] if len(sorted_dom) > 9 else [])
    return {'period': per, 'labels': [k for k, _ in top], 'values': [round(v / (1024 ** 3), 2) for _, v in top]}