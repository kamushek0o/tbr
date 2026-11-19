# core/torrent_diff.py
import os
import re
from difflib import SequenceMatcher
from utils.bencode import decode_bencode
from utils.helpers import BT_BACKUP_PATH, format_file_size
from core.qb_api import get_torrent_files

_SEASON_EP_RE = re.compile(r'(?:s(\d{1,2})(?:e(\d{1,3}))?|season\s*(\d{1,2})|сезон\s*(\d{1,2})|\b(\d{1,2})x(\d{1,3})\b)', re.IGNORECASE)
_JUNK_TAGS_RE = re.compile(
    r'\[[^\]]*\]|\([^\)]*\)|\b(?:repack|rip|bdrip|web-dl|webdl|hdrip|bluray|1080p|720p|2160p|480p|4k|uhd|x264|x265|h264|h265|hevc|rus|eng|multi|portable|fitgirl|dodi|xatab|v?\d+\.\d+(?:\.\d+)*|build\s*\d+|\d+(?:gb|mb|tb|gib|mib|tib|fps|hz|bit|ch))\b',
    re.IGNORECASE
)
_ROMAN_MAP = {
    'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8,
    'IX': 9, 'X': 10, 'XI': 11, 'XII': 12, 'XIII': 13, 'XIV': 14, 'XV': 15
}
_ROMAN_MULTI_RE = re.compile(r'(?:^|[\s._:\-])(XIII|XIV|XV|XII|XI|VIII|VII|VI|IV|IX|III|II)(?=$|[\s._:\-])', re.IGNORECASE)
_ROMAN_SINGLE_RE = re.compile(r'(?:^|[\s._:\-])(I|V|X)(?=$|[\s._:\-])')
_ROMAN_TRAIL_RE = re.compile(r'\s+(i|v|x)$', re.IGNORECASE)
_ARABIC_PART_RE = re.compile(r'(?:^|[\s._:\-])(\d{1,4})(?=$|[\s._:\-])')
_GENERIC_ROOT_NAMES = {'downloads', 'download', 'torrents', 'torrent', 'games', 'movies', 'films', 'series', 'music', 'video', 'загрузки', 'игры', 'фильмы', 'сериалы', 'торренты'}


def _norm_rel(path):
    return str(path or '').replace('\\', '/').strip('/')


def _strip_root(path):
    p = _norm_rel(path)
    return p.split('/', 1)[1] if '/' in p else p


def _read_files_from_torrent_file(t_hash):
    if not os.path.isdir(BT_BACKUP_PATH):
        return []
    target = t_hash.lower() + '.torrent'
    fpath = next((os.path.join(BT_BACKUP_PATH, f) for f in os.listdir(BT_BACKUP_PATH) if f.lower() == target), None)
    if not fpath:
        return []
    try:
        with open(fpath, 'rb') as fp:
            data = decode_bencode(fp.read()) or {}
        info = data.get('info') or data.get(b'info') or {}
        if not isinstance(info, dict):
            return []
        raw_name = info.get('name.utf-8') or info.get('name') or info.get(b'name') or t_hash
        root_name = raw_name.decode('utf-8', errors='replace') if isinstance(raw_name, bytes) else str(raw_name)
        if 'length' in info or b'length' in info:
            return [{'path': _norm_rel(root_name), 'size': int(info.get('length') or info.get(b'length') or 0)}]
        out = []
        for entry in (info.get('files') or info.get(b'files') or []):
            if not isinstance(entry, dict):
                continue
            sz = int(entry.get('length') or entry.get(b'length') or 0)
            parts_raw = entry.get('path.utf-8') or entry.get('path') or entry.get(b'path') or []
            parts = [p.decode('utf-8', errors='replace') if isinstance(p, bytes) else str(p) for p in parts_raw]
            rel = '/'.join([root_name] + parts) if root_name else '/'.join(parts)
            out.append({'path': _norm_rel(rel), 'size': sz})
        return out
    except Exception:
        return []


def _get_files_map(ip, port, t_hash):
    raw = get_torrent_files(ip, port, t_hash) if port else []
    if raw:
        return [{'path': _norm_rel(f.get('name', '')), 'size': int(f.get('size', 0) or 0)} for f in raw if f.get('name')]
    return _read_files_from_torrent_file(t_hash)


def compute_torrent_diff(ip, port, old_hash, new_hash):
    old_list = _get_files_map(ip, port, old_hash)
    new_list = _get_files_map(ip, port, new_hash)
    if not old_list and not new_list:
        return {'success': False, 'error': 'Не удалось получить списки файлов (проверьте WebUI или .torrent в BT_backup).'}

    old_exact = {f['path']: f['size'] for f in old_list}
    new_exact = {f['path']: f['size'] for f in new_list}
    use_stripped = False
    if old_exact and new_exact and not (set(old_exact.keys()) & set(new_exact.keys())):
        old_sub = {_strip_root(f['path']): f['size'] for f in old_list}
        new_sub = {_strip_root(f['path']): f['size'] for f in new_list}
        if set(old_sub.keys()) & set(new_sub.keys()):
            use_stripped = True
            old_map, new_map = old_sub, new_sub
        else:
            old_map, new_map = old_exact, new_exact
    else:
        old_map, new_map = old_exact, new_exact

    all_keys = sorted(set(old_map.keys()) | set(new_map.keys()))
    rows, exact_cnt, changed_cnt, removed_cnt, added_cnt, exact_bytes = [], 0, 0, 0, 0, 0
    old_total, new_total = sum(old_map.values()), sum(new_map.values())

    for k in all_keys:
        in_old, in_new = k in old_map, k in new_map
        if in_old and in_new:
            osize, nsize = old_map[k], new_map[k]
            if osize == nsize:
                status, exact_cnt, exact_bytes = 'exact', exact_cnt + 1, exact_bytes + osize
            else:
                status, changed_cnt = 'changed', changed_cnt + 1
        elif in_old:
            osize, nsize, status, removed_cnt = old_map[k], None, 'removed', removed_cnt + 1
        else:
            osize, nsize, status, added_cnt = None, new_map[k], 'added', added_cnt + 1
        if len(rows) < 2000:
            rows.append({
                'path': k, 'status': status, 'old_size': osize, 'new_size': nsize,
                'old_size_fmt': format_file_size(osize) if osize is not None else '—',
                'new_size_fmt': format_file_size(nsize) if nsize is not None else '—',
            })

    match_pct = round(min(100.0, (exact_bytes / max(1, old_total, new_total)) * 100.0), 1)
    return {
        'success': True, 'stripped_root': use_stripped, 'match_percent': match_pct,
        'old_total_fmt': format_file_size(old_total), 'new_total_fmt': format_file_size(new_total),
        'stats': {'exact': exact_cnt, 'changed': changed_cnt, 'removed': removed_cnt, 'added': added_cnt, 'total_rows': len(all_keys), 'truncated': len(all_keys) > 2000},
        'files': rows
    }


def _extract_season_sig(name):
    sigs = []
    for m in _SEASON_EP_RE.finditer(name or ''):
        s = m.group(1) or m.group(3) or m.group(4) or m.group(5) or ''
        e = m.group(2) or m.group(6) or ''
        sigs.append((s.lstrip('0') or '0', e.lstrip('0') if e else ''))
    return sigs


def _extract_sequel_numbers(name):
    base = re.sub(r'\.[a-z0-9]{2,4}$', '', str(name or ''))
    base = _JUNK_TAGS_RE.sub(' ', base)
    nums = []
    for m in _ROMAN_MULTI_RE.finditer(base):
        val = _ROMAN_MAP.get(m.group(1).upper())
        if val:
            nums.append(val)
    for m in _ROMAN_SINGLE_RE.finditer(base):
        val = _ROMAN_MAP.get(m.group(1))
        if val:
            nums.append(val)
    if not nums:
        mt = _ROMAN_TRAIL_RE.search(base.strip())
        if mt:
            val = _ROMAN_MAP.get(mt.group(1).upper())
            if val:
                nums.append(val)
    for m in _ARABIC_PART_RE.finditer(base):
        nums.append(int(m.group(1)))
    return tuple(nums)


def _clean_title(name):
    s = re.sub(r'\.[a-z0-9]{2,4}$', '', str(name or '').lower())
    s = _JUNK_TAGS_RE.sub(' ', s)
    s = re.sub(r'[._\-]+', ' ', s)
    return ' '.join(s.split())


def _extract_content_leaf(item):
    sp = str(item.get('save_path') or '').strip()
    cp = str(item.get('content_path') or '').strip()
    if not cp:
        return ''
    cp_norm = os.path.normcase(os.path.normpath(cp))
    sp_norm = os.path.normcase(os.path.normpath(sp)) if sp else ''
    if sp_norm and cp_norm == sp_norm:
        return ''
    leaf = os.path.basename(cp_norm).strip()
    if not leaf or leaf in _GENERIC_ROOT_NAMES:
        return ''
    return leaf


def find_smart_merge_candidates(items, max_results=20):
    if not items or len(items) < 2:
        return []

    prepared = []
    for it in items:
        nm = it.get('name', '')
        prepared.append({
            'item': it,
            'clean': _clean_title(nm),
            'seasons': _extract_season_sig(nm),
            'sequels': _extract_sequel_numbers(nm),
            'cp_leaf': _extract_content_leaf(it)
        })

    candidates = []
    n = len(prepared)
    for i in range(n):
        a = prepared[i]
        for j in range(i + 1, n):
            b = prepared[j]
            if (a['seasons'] and b['seasons'] and a['seasons'] != b['seasons']) or (bool(a['seasons']) != bool(b['seasons'])):
                continue
            if a['sequels'] != b['sequels']:
                continue

            same_content_dir = bool(a['cp_leaf'] and b['cp_leaf'] and a['cp_leaf'] == b['cp_leaf'])
            sim = SequenceMatcher(None, a['clean'], b['clean']).ratio() if (a['clean'] and b['clean']) else 0.0

            if not ((same_content_dir and sim >= 0.55) or sim >= 0.80):
                continue

            ia, ib = a['item'], b['item']
            score_a = (int(ia.get('uploaded', 0) or 0), int(ia.get('active_seconds', 0) or 0))
            score_b = (int(ib.get('uploaded', 0) or 0), int(ib.get('active_seconds', 0) or 0))
            old_it, new_it = (ia, ib) if score_a >= score_b else (ib, ia)

            reason = f"Одинаковая папка контента: {a['cp_leaf']}" if same_content_dir else f"Совпадение имени {int(sim * 100)}%"
            candidates.append({
                'old_hash': old_it['hash'], 'new_hash': new_it['hash'],
                'old_name': old_it['name'], 'new_name': new_it['name'],
                'old_up_fmt': old_it.get('uploaded_fmt', '0 B'), 'new_up_fmt': new_it.get('uploaded_fmt', '0 B'),
                'similarity': int(round(sim * 100)), 'same_dir': same_content_dir,
                'reason': reason, 'rank': (1 if same_content_dir else 0) + sim
            })

    candidates.sort(key=lambda x: x['rank'], reverse=True)
    return candidates[:max_results]