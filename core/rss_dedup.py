# core/rss_dedup.py
from difflib import SequenceMatcher
from utils.config import cfg
from core.qb_api import detect_qbittorrent_port, _get_qb_json, get_live_torrent_info
from core.torrent_parser import get_all_torrents
from core.torrent_diff import _clean_title


def _extract_rss_articles(node, feed_name='', out=None):
    if out is None:
        out = []
    if not isinstance(node, dict):
        return out
    if 'articles' in node and isinstance(node['articles'], list):
        for art in node['articles']:
            if isinstance(art, dict):
                out.append({
                    'feed': feed_name,
                    'title': str(art.get('title') or ''),
                    'url': str(art.get('torrentURL') or art.get('link') or ''),
                    'date': str(art.get('date') or ''),
                    'is_read': bool(art.get('isRead', False))
                })
    else:
        for k, v in node.items():
            if isinstance(v, dict):
                _extract_rss_articles(v, feed_name=k, out=out)
    return out


def check_rss_duplicates():
    """#34 Читает RSS-элементы через API qB (rss/items) и прогоняет через Smart Match."""
    ip, port = detect_qbittorrent_port(cfg.config)
    if not port:
        return {'success': False, 'error': 'qBittorrent недоступен', 'items': []}

    rss_raw = _get_qb_json(ip, port, "rss/items?withData=true", timeout=4.0)
    if rss_raw is None:
        return {'success': False, 'error': 'RSS в qBittorrent выключен или пуст', 'items': []}

    articles = _extract_rss_articles(rss_raw)
    live = get_live_torrent_info(ip, port)
    existing = list(live.values()) if live else list(get_all_torrents(use_cache=True).values())
    existing_clean = [(str(x.get('name') or ''), _clean_title(x.get('name') or '')) for x in existing if x.get('name')]

    results = []
    for art in articles[:120]:
        t_clean = _clean_title(art['title'])
        best_sim, best_match = 0.0, ''
        if t_clean:
            for ex_raw, ex_cl in existing_clean:
                if not ex_cl:
                    continue
                sim = SequenceMatcher(None, t_clean, ex_cl).ratio()
                if sim > best_sim:
                    best_sim, best_match = sim, ex_raw
        results.append({
            **art,
            'is_duplicate': best_sim >= 0.78,
            'similarity': int(round(best_sim * 100)),
            'matched_name': best_match if best_sim >= 0.78 else ''
        })

    results.sort(key=lambda x: (not x['is_duplicate'], -x['similarity']))
    return {
        'success': True,
        'total': len(results),
        'duplicates': sum(1 for r in results if r['is_duplicate']),
        'items': results
    }