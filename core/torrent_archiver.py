# core/torrent_archiver.py
import os
import io
import gzip
import time
import zipfile
from utils.config import cfg
from utils.helpers import APP_DATA_DIR, BT_BACKUP_PATH, format_file_size, write_error_log
from core.app_state_db import app_state_db
from core.torrent_parser import get_all_torrents
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info
from core.private_vault import get_hidden_hashes

ARCHIVE_DIR = os.path.join(APP_DATA_DIR, "torrent_archive")
os.makedirs(ARCHIVE_DIR, exist_ok=True)


def _ensure_table():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS torrent_archive_index (
                        hash_id TEXT PRIMARY KEY,
                        uid TEXT NOT NULL,
                        name TEXT NOT NULL,
                        tags TEXT NOT NULL DEFAULT '',
                        raw_size INTEGER NOT NULL DEFAULT 0,
                        gz_size INTEGER NOT NULL DEFAULT 0,
                        archived_at REAL NOT NULL
                    )
                """)
        except Exception as e:
            write_error_log("torrent_archive_index init", e)


_ensure_table()


def sync_torrent_archive():
    if not os.path.isdir(BT_BACKUP_PATH):
        return {'success': False, 'error': 'BT_backup не найден'}

    parsed = get_all_torrents(use_cache=True)
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    live_lower = {k.lower(): v for k, v in live.items()}

    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            uid_map = {r['torrent_hash']: r['torrent_uid'] for r in conn.execute("SELECT torrent_hash, torrent_uid FROM torrent_lineage").fetchall()}

    added, now = 0, time.time()
    records = []
    for ent in os.scandir(BT_BACKUP_PATH):
        if not ent.is_file() or not ent.name.lower().endswith('.torrent'):
            continue
        hl = ent.name[:-8].lower()
        gz_path = os.path.join(ARCHIVE_DIR, hl + '.torrent.gz')
        lv = live_lower.get(hl, {})
        st = parsed.get(hl, {})
        name = str(lv.get('name') or st.get('name') or hl)
        tags = str(lv.get('tags') or '')
        uid = uid_map.get(hl, hl)

        if not os.path.isfile(gz_path):
            try:
                with open(ent.path, 'rb') as rf:
                    raw = rf.read()
                tmp = gz_path + '.tmp'
                with gzip.open(tmp, 'wb', compresslevel=6) as gf:
                    gf.write(raw)
                os.replace(tmp, gz_path)
                added += 1
            except Exception:
                continue

        raw_sz = ent.stat().st_size
        gz_sz = os.path.getsize(gz_path) if os.path.isfile(gz_path) else 0
        records.append((hl, uid, name, tags, raw_sz, gz_sz, now))

    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.executemany(
                    """INSERT OR REPLACE INTO torrent_archive_index
                       (hash_id, uid, name, tags, raw_size, gz_size, archived_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    records
                )
        except Exception as e:
            write_error_log("sync_torrent_archive db", e)

    return {'success': True, 'added': added, 'total': len(records)}


def list_archived_torrents(query='', tag='', role='admin'):
    q = str(query or '').strip().lower()
    tg = str(tag or '').strip().lower()
    hidden = set()
    if role != 'admin':
        ip, port = detect_qbittorrent_port(cfg.config)
        live = get_live_torrent_info(ip, port) if port else {}
        hidden = get_hidden_hashes(live)

    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = [dict(r) for r in conn.execute("SELECT * FROM torrent_archive_index ORDER BY archived_at DESC").fetchall()]
        except Exception:
            rows = []

    out = []
    for r in rows:
        if r['hash_id'] in hidden:
            continue
        if q and q not in r['name'].lower() and q not in r['hash_id'].lower() and q not in r['uid'].lower():
            continue
        if tg and tg not in {x.strip().lower() for x in r['tags'].split(',') if x.strip()}:
            continue
        r['gz_fmt'] = format_file_size(r['gz_size'])
        out.append(r)
    return out


def get_archived_torrent_bytes(t_hash, role='admin'):
    hl = str(t_hash or '').strip().lower()
    if role != 'admin':
        ip, port = detect_qbittorrent_port(cfg.config)
        live = get_live_torrent_info(ip, port) if port else {}
        if hl in get_hidden_hashes(live):
            return None, None
    gz_path = os.path.join(ARCHIVE_DIR, hl + '.torrent.gz')
    if not os.path.isfile(gz_path):
        return None, None
    with gzip.open(gz_path, 'rb') as gf:
        return gf.read(), hl + '.torrent'


def export_archive_zip_by_tag(tag='', role='admin'):
    items = list_archived_torrents(tag=tag, role=role)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for it in items:
            raw, fname = get_archived_torrent_bytes(it['hash_id'], role=role)
            if raw and fname:
                zf.writestr(fname, raw)
    return buf.getvalue(), len(items)