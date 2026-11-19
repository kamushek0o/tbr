# core/private_vault.py
import time
from utils.config import cfg
from utils.helpers import format_file_size
from core.app_state_db import app_state_db


def get_vault_settings():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = conn.execute("SELECT tag FROM private_vault_tags ORDER BY tag ASC").fetchall()
                tags = [r['tag'] for r in rows]
        except Exception:
            tags = []
    mode = cfg.get('Vault_Aggregate_Mode', 'exclude').strip().lower()
    if mode not in ('exclude', 'anonymize'):
        mode = 'exclude'
    return {'tags': tags, 'aggregate_mode': mode}


def save_vault_settings(tags_input, aggregate_mode='exclude'):
    if isinstance(tags_input, str):
        raw_list = tags_input.split(',')
    elif isinstance(tags_input, list):
        raw_list = tags_input
    else:
        raw_list = []

    clean_tags = sorted({str(t).strip().lower()[:32] for t in raw_list if str(t).strip()})
    mode = str(aggregate_mode or 'exclude').strip().lower()
    if mode not in ('exclude', 'anonymize'):
        mode = 'exclude'

    now = time.time()
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("DELETE FROM private_vault_tags")
                if clean_tags:
                    conn.executemany(
                        "INSERT INTO private_vault_tags (tag, created_at) VALUES (?, ?)",
                        [(t, now) for t in clean_tags]
                    )
                conn.commit()
        except Exception:
            pass

    cfg.set('Vault_Aggregate_Mode', mode)
    cfg.save()
    return {'tags': clean_tags, 'aggregate_mode': mode}


def get_hidden_hashes(live_info):
    tags = set(get_vault_settings().get('tags') or [])
    if not tags or not live_info:
        return set()
    hidden = set()
    for t_hash, info in live_info.items():
        t_tags = {tg.strip().lower() for tg in str(info.get('tags', '') or '').split(',') if tg.strip()}
        if t_tags & tags:
            hidden.add(str(t_hash).lower())
    return hidden


def filter_torrents_for_role(items, role, hidden_hashes):
    if role == 'admin' or not hidden_hashes:
        return items
    return [
        it for it in items
        if str(it.get('hash') or it.get('hash_id') or '').lower() not in hidden_hashes
    ]


def filter_summary_stats_for_role(stats, role, hidden_hashes):
    if role == 'admin' or not hidden_hashes or not isinstance(stats, dict):
        return stats

    mode = get_vault_settings().get('aggregate_mode', 'exclude')
    all_items = stats.get('items') or []
    visible_items = [
        it for it in all_items
        if str(it.get('hash_id') or it.get('hash') or '').lower() not in hidden_hashes
    ]

    out = dict(stats)
    out['items'] = visible_items

    if mode == 'exclude':
        tot_up = sum(int(i.get('uploaded', 0) or 0) for i in visible_items)
        tot_sz = sum(int(i.get('size', 0) or 0) for i in visible_items)
        hidden_items = [
            it for it in all_items
            if str(it.get('hash_id') or it.get('hash') or '').lower() in hidden_hashes
        ]
        hid_day = sum(int(i.get('delta_24h', 0) or 0) for i in hidden_items)
        vis_day = max(0, int(out.get('global_day_volume', 0) or 0) - hid_day)
        out['total_torrents'] = len(visible_items)
        out['total_size'] = tot_sz
        out['total_size_fmt'] = format_file_size(tot_sz)
        out['total_uploaded'] = tot_up
        out['total_uploaded_fmt'] = format_file_size(tot_up)
        out['global_day_volume'] = vis_day
        out['global_day_volume_fmt'] = f"{format_file_size(vis_day)} / день"

    return out