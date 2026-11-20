# core/swarm_analytics.py
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.qb_api import _get_qb_json, get_torrent_peers

_TITLE_STRIP_RE = re.compile(
    r'\[[^\]]*\]|\([^\)]*\)|\b(?:repack|rip|bdrip|web-dl|webdl|hdrip|bluray|1080p|720p|2160p|480p|4k|uhd|x264|x265|h264|h265|hevc|av1|rus|eng|multi|sub|dub|fitgirl|dodi|xatab|v?\d+(?:\.\d+)+)\b',
    re.IGNORECASE
)


def get_tracker_survivability(summaries, live, hidden_hashes=None):
    """#19 Рейтинг живучести трекеров и GB-ROI (мультитрекерные выделяются отдельно)."""
    hidden = {h.lower() for h in (hidden_hashes or set())}
    live_lower = {k.lower(): v for k, v in (live or {}).items()}
    groups = {}

    for s in summaries:
        hl = (s.get('hash_id') or s.get('hash') or '').lower()
        if not hl or hl in hidden:
            continue
        lv = live_lower.get(hl, {})
        tr_list = list(s.get('trackers') or [])
        tr_live = str(lv.get('tracker') or '').strip()
        if tr_live and tr_live not in tr_list:
            tr_list.insert(0, tr_live)

        hosts = {urllib.parse.urlparse(t).netloc.lower().split(':')[0] for t in tr_list if t and urllib.parse.urlparse(t).netloc}
        if len(hosts) > 1:
            key = '🔀 Мультитрекерные'
        elif len(hosts) == 1:
            key = next(iter(hosts))
        else:
            key = 'Без трекера / DHT'

        up = int(lv.get('uploaded', s.get('uploaded', 0)) or 0)
        sz = int(lv.get('total_size', s.get('size', 0)) or 0)
        st = str(lv.get('state', '')).lower()
        is_ok = st not in ('error', 'missingfiles')

        g = groups.setdefault(key, {'tracker': key, 'count': 0, 'ok_count': 0, 'size': 0, 'uploaded': 0})
        g['count'] += 1
        if is_ok:
            g['ok_count'] += 1
        g['size'] += sz
        g['uploaded'] += up

    out = []
    for g in groups.values():
        sz_gb = max(0.01, g['size'] / (1024 ** 3))
        up_gb = g['uploaded'] / (1024 ** 3)
        out.append({
            'tracker': g['tracker'],
            'count': g['count'],
            'uptime_pct': round((g['ok_count'] / max(1, g['count'])) * 100.0, 1),
            'gb_roi': round(up_gb / sz_gb, 2),
            'uploaded_gb': round(up_gb, 2)
        })
    out.sort(key=lambda x: x['uploaded_gb'], reverse=True)
    return out[:20]


def get_protocol_efficiency(ip, port, live, hidden_hashes=None):
    """#43 uTP против TCP и IPv4 против IPv6 (только топ-12 активных раздач прямо сейчас)."""
    if not port or not live:
        return {'utp': 0, 'tcp': 0, 'ipv4': 0, 'ipv6': 0, 'utp_speed': 0, 'tcp_speed': 0, 'sampled': 0}
    hidden = {h.lower() for h in (hidden_hashes or set())}
    active = sorted(
        [(h, v) for h, v in live.items() if h.lower() not in hidden and (int(v.get('upspeed', 0) or 0) + int(v.get('dlspeed', 0) or 0)) > 0],
        key=lambda kv: int(kv[1].get('upspeed', 0) or 0) + int(kv[1].get('dlspeed', 0) or 0),
        reverse=True
    )[:12]

    utp_cnt = tcp_cnt = v4_cnt = v6_cnt = utp_spd = tcp_spd = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(get_torrent_peers, ip, port, h) for h, _ in active]
        for fut in as_completed(futs):
            try:
                peers = (fut.result() or {}).get('peers') or {}
                for p in peers.values():
                    if not isinstance(p, dict):
                        continue
                    flags = str(p.get('flags') or '')
                    ip_addr = str(p.get('ip') or '')
                    spd = int(p.get('up_speed', 0) or 0) + int(p.get('dl_speed', 0) or 0)
                    if 'u' in flags:
                        utp_cnt += 1
                        utp_spd += spd
                    else:
                        tcp_cnt += 1
                        tcp_spd += spd
                    if ':' in ip_addr:
                        v6_cnt += 1
                    elif ip_addr:
                        v4_cnt += 1
            except Exception:
                pass

    return {
        'utp': utp_cnt, 'tcp': tcp_cnt,
        'ipv4': v4_cnt, 'ipv6': v6_cnt,
        'utp_avg_kbs': round((utp_spd / max(1, utp_cnt)) / 1024.0, 1),
        'tcp_avg_kbs': round((tcp_spd / max(1, tcp_cnt)) / 1024.0, 1),
        'sampled': len(active)
    }


def get_qb_slot_recommendations(ip, port, live, max_channel_mbps=1000):
    """#50 Авто-тюнер слотов qB (только рекомендации с объяснением «почему»)."""
    if not port:
        return []
    prefs = _get_qb_json(ip, port, "app/preferences", timeout=2.0) or {}
    recs = []
    max_up_slots = int(prefs.get('max_active_uploads') or 0)
    global_connec = int(prefs.get('max_connec') or 0)
    up_slots_per_tor = int(prefs.get('max_uploads_per_torrent') or 0)

    if 0 < max_up_slots < 10 and len(live or {}) > 30:
        recs.append(f"🎰 Увеличьте max_active_uploads (сейчас {max_up_slots}) до 15–20: у вас {len(live)} раздач, мелкие сиды могут простаивать в очереди.")
    if max_channel_mbps <= 150 and global_connec > 500:
        recs.append(f"🔌 Снизьте max_connec (сейчас {global_connec}) до 250–300: для канала {max_channel_mbps} Мбит/с лишние соединения только грузят роутер.")
    if up_slots_per_tor > 10:
        recs.append(f"⚡ Умерьте слоты отдачи на торрент (сейчас {up_slots_per_tor}) до 4–8: дробление канала на десятки пиров снижает эффективность TCP.")
    if not recs:
        recs.append("✅ Текущие лимиты слотов и соединений qBittorrent сбалансированы под ваш канал.")
    return recs


def find_normalized_title_groups(items, hidden_hashes=None):
    """#39 Группировщик версий по нормализованному названию (информационный инструмент)."""
    hidden = {h.lower() for h in (hidden_hashes or set())}
    buckets = {}
    for it in items:
        h = str(it.get('hash') or it.get('hash_id') or '').lower()
        if h in hidden:
            continue
        nm = str(it.get('name') or '')
        norm = re.sub(r'[._\-]+', ' ', _TITLE_STRIP_RE.sub(' ', nm.lower()))
        norm = ' '.join(norm.split())
        if len(norm) < 4:
            continue
        buckets.setdefault(norm, []).append(it)

    groups = []
    for norm, grp in buckets.items():
        if len(grp) < 2:
            continue
        tot_sz = sum(int(x.get('size', 0) or 0) for x in grp)
        groups.append({
            'title': norm,
            'count': len(grp),
            'total_size': tot_sz,
            'items': [{'name': x.get('name', ''), 'size_fmt': x.get('size_fmt', ''), 'uploaded_fmt': x.get('uploaded_fmt', '')} for x in grp]
        })
    groups.sort(key=lambda x: x['total_size'], reverse=True)
    return groups[:30]