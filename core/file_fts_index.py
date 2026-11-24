# core/file_fts_index.py
import os
import sqlite3
import threading
import urllib.parse
from contextlib import contextmanager
from utils.bencode import decode_bencode
from utils.helpers import APP_DATA_DIR, BT_BACKUP_PATH, format_file_size, write_error_log
from core.qb_api import get_torrent_files

_FTS_DB = os.path.join(APP_DATA_DIR, "file_index.db")
_LOCK = threading.RLock()
_HAS_FTS5 = True


@contextmanager
def _get_conn():
    conn = sqlite3.connect(_FTS_DB, timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _init_fts():
    global _HAS_FTS5
    with _LOCK:
        try:
            with _get_conn() as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                try:
                    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(hash_id UNINDEXED, torrent_name UNINDEXED, file_path, file_size UNINDEXED)")
                    _HAS_FTS5 = True
                except sqlite3.OperationalError:
                    _HAS_FTS5 = False
                    conn.execute("CREATE TABLE IF NOT EXISTS files_plain (hash_id TEXT, torrent_name TEXT, file_path TEXT, file_size INTEGER)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_fp_path ON files_plain(file_path)")
                conn.execute("CREATE TABLE IF NOT EXISTS indexed_hashes (hash_id TEXT PRIMARY KEY, mtime REAL NOT NULL)")
        except Exception as e:
            write_error_log("init_fts", e)


_init_fts()


def _extract_files_from_torrent(fpath):
    with open(fpath, 'rb') as f:
        data = decode_bencode(f.read()) or {}
    info = data.get('info') or data.get(b'info') or {}
    if not isinstance(info, dict):
        return '', []
    raw_nm = info.get('name.utf-8') or info.get('name') or info.get(b'name') or ''
    t_name = raw_nm.decode('utf-8', errors='replace') if isinstance(raw_nm, bytes) else str(raw_nm)

    if 'length' in info or b'length' in info:
        sz = int(info.get('length') or info.get(b'length') or 0)
        return t_name, [(t_name, sz)]

    files = []
    for entry in (info.get('files') or info.get(b'files') or []):
        if not isinstance(entry, dict):
            continue
        sz = int(entry.get('length') or entry.get(b'length') or 0)
        parts = entry.get('path.utf-8') or entry.get('path') or entry.get(b'path') or []
        rel = "/".join(p.decode('utf-8', errors='replace') if isinstance(p, bytes) else str(p) for p in parts)
        files.append((rel, sz))

    if len(files) > 5000:
        files.sort(key=lambda x: x[1], reverse=True)
        files = files[:500]
    return t_name, files


def reindex_torrent_files(force=False):
    """#45 Индексация файлов локальных .torrent из BT_backup без нагрузки на API qB."""
    if not os.path.isdir(BT_BACKUP_PATH):
        return {'success': False, 'error': 'BT_backup не найден'}

    with _LOCK:
        with _get_conn() as conn:
            known = {} if force else {r['hash_id']: r['mtime'] for r in conn.execute("SELECT hash_id, mtime FROM indexed_hashes").fetchall()}
            if force:
                tbl = "files_fts" if _HAS_FTS5 else "files_plain"
                conn.execute(f"DELETE FROM {tbl}")
                conn.execute("DELETE FROM indexed_hashes")

    indexed_cnt = 0
    for ent in os.scandir(BT_BACKUP_PATH):
        if not ent.is_file() or not ent.name.lower().endswith('.torrent'):
            continue
        hl = ent.name[:-8].lower()
        mtime = ent.stat().st_mtime
        if hl in known and abs(known[hl] - mtime) < 1.0:
            continue
        try:
            t_name, files = _extract_files_from_torrent(ent.path)
            if not files:
                continue
            with _LOCK:
                with _get_conn() as conn:
                    tbl = "files_fts" if _HAS_FTS5 else "files_plain"
                    conn.execute(f"DELETE FROM {tbl} WHERE hash_id = ?", (hl,))
                    conn.executemany(
                        f"INSERT INTO {tbl} (hash_id, torrent_name, file_path, file_size) VALUES (?, ?, ?, ?)",
                        [(hl, t_name, fp, sz) for fp, sz in files]
                    )
                    conn.execute("INSERT OR REPLACE INTO indexed_hashes (hash_id, mtime) VALUES (?, ?)", (hl, mtime))
            indexed_cnt += 1
        except Exception:
            continue

    return {'success': True, 'indexed': indexed_cnt, 'fts5': _HAS_FTS5}


def search_files_fts(query, limit=25, hidden_hashes=None):
    q = str(query or '').strip()
    if len(q) < 2:
        return []
    hidden = {h.lower() for h in (hidden_hashes or set())}
    out = []
    with _LOCK:
        try:
            with _get_conn() as conn:
                if _HAS_FTS5:
                    tokens = [f'"{tok.replace(chr(34), "")}"*' for tok in q.split() if tok.strip()]
                    if not tokens:
                        return []
                    rows = conn.execute("SELECT hash_id, torrent_name, file_path, file_size FROM files_fts WHERE files_fts MATCH ? LIMIT ?", (" ".join(tokens), limit * 3)).fetchall()
                else:
                    rows = conn.execute("SELECT hash_id, torrent_name, file_path, file_size FROM files_plain WHERE file_path LIKE ? LIMIT ?", (f"%{q}%", limit * 3)).fetchall()
                for r in rows:
                    if r['hash_id'] in hidden:
                        continue
                    out.append({
                        'hash': r['hash_id'],
                        'torrent_name': r['torrent_name'],
                        'file_path': r['file_path'],
                        'size_fmt': format_file_size(int(r['file_size'] or 0))
                    })
                    if len(out) >= limit:
                        break
        except Exception:
            pass
    return out


def build_treemap_data(summaries, live, group_by='tags', hidden_hashes=None):
    """#22 Карта тяжеловесов (Treemap) по тегам, трекерам или торрентам."""
    hidden = {h.lower() for h in (hidden_hashes or set())}
    live_lower = {k.lower(): v for k, v in (live or {}).items()}
    buckets = {}

    for s in summaries:
        hl = (s.get('hash_id') or '').lower()
        if not hl or hl in hidden:
            continue
        lv = live_lower.get(hl, {})
        sz = int(lv.get('total_size', s.get('size', 0)) or 0)
        if sz <= 0:
            continue

        if group_by == 'torrents':
            key = str(lv.get('name') or s.get('name') or hl)[:40]
        elif group_by == 'trackers':
            tr = str(lv.get('tracker') or (s['trackers'][0] if s.get('trackers') else ''))
            key = urllib.parse.urlparse(tr).netloc.lower().split(':')[0] if tr else 'DHT / Без трекера'
        else:
            raw_tags = str(lv.get('tags') or '').strip()
            key = raw_tags.split(',')[0].strip() if raw_tags else 'Без тега'

        buckets[key] = buckets.get(key, 0) + sz

    sorted_b = sorted(buckets.items(), key=lambda x: x[1], reverse=True)[:18]
    return [{'label': k, 'bytes': v, 'gb': round(v / (1024 ** 3), 2), 'fmt': format_file_size(v)} for k, v in sorted_b]


def get_torrent_files_paginated(ip, port, t_hash, page=1, per_page=100):
    files = get_torrent_files(ip, port, t_hash) if port else []
    total = len(files)
    p = max(1, int(page))
    pp = max(10, min(200, int(per_page)))
    slice_items = files[(p - 1) * pp: p * pp]
    out = []
    for idx, f in enumerate(slice_items, start=(p - 1) * pp):
        out.append({
            'id': int(f.get('index', idx)),
            'name': str(f.get('name', '')),
            'size_fmt': format_file_size(f.get('size', 0)),
            'progress': round(float(f.get('progress', 0.0) or 0.0) * 100.0, 1),
            'priority': int(f.get('priority', 1) or 0)
        })
    return {'files': out, 'total': total, 'page': p, 'total_pages': max(1, (total + pp - 1) // pp)}