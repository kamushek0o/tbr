# core/wrapped_service.py
import io
import csv
import json
import time
import datetime
from utils.helpers import format_file_size, sanitize_csv_cell
from core.scheduler import MIN_DELTA_SEC
from core.health_score import compute_health_metrics


def build_wrapped_summary(db, summaries, live, period='month', hidden_hashes=None):
    """#40 tbr Wrapped: итоги месяца/года со строгим исключением Private Vault."""
    hidden = {h.lower() for h in (hidden_hashes or set())}
    live_lower = {k.lower(): v for k, v in (live or {}).items()}
    days = 365 if period == 'year' else 30
    since_ts = time.time() - (days * 86400)

    visible = [s for s in summaries if (s.get('hash_id') or '').lower() not in hidden]
    deltas = db.get_torrents_positive_deltas(since_ts, allowed_hashes=[(s.get('hash_id') or '').lower() for s in visible])
    period_up = sum(deltas.values())

    last_seed_saved = 0
    tag_vols = {}
    for s in visible:
        hl = (s.get('hash_id') or '').lower()
        lv = live_lower.get(hl, {})
        if lv and compute_health_metrics(lv).get('is_last_seed'):
            last_seed_saved += 1
        vol = deltas.get(hl, 0)
        for tg in str(lv.get('tags') or '').split(','):
            t_clean = tg.strip()
            if t_clean and vol > 0:
                tag_vols[t_clean] = tag_vols.get(t_clean, 0) + vol

    rows = db.get_snapshots_since(since_ts)
    day_totals, prev = {}, None
    for r in rows:
        if prev is not None:
            dt = float(r['timestamp']) - float(prev['timestamp'])
            d = max(0, int(r['total_uploaded']) - int(prev['total_uploaded']))
            if dt >= MIN_DELTA_SEC and d > 0:
                dk = str(r.get('datetime') or '')[:10]
                if dk:
                    day_totals[dk] = day_totals.get(dk, 0) + d
        prev = r

    best_day = max(day_totals.items(), key=lambda x: x[1], default=('—', 0))
    top_tags = sorted(tag_vols.items(), key=lambda x: x[1], reverse=True)[:3]

    return {
        'period': period,
        'period_label': 'За год (365 дн.)' if period == 'year' else 'За месяц (30 дн.)',
        'total_uploaded_fmt': format_file_size(period_up),
        'visible_torrents': len(visible),
        'last_seed_saved': last_seed_saved,
        'best_day_date': best_day[0],
        'best_day_fmt': format_file_size(best_day[1]),
        'top_tags': [{'tag': k, 'fmt': format_file_size(v)} for k, v in top_tags]
    }


def export_full_inventory(summaries, live, lineage_map, notes_map, fmt='json', hidden_hashes=None):
    """#53 Полный экспорт инвентаря в JSON / CSV / Markdown с изоляцией Private Vault."""
    hidden = {h.lower() for h in (hidden_hashes or set())}
    live_lower = {k.lower(): v for k, v in (live or {}).items()}
    rows = []

    for s in summaries:
        hl = (s.get('hash_id') or '').lower()
        if not hl or hl in hidden:
            continue
        lv = live_lower.get(hl, {})
        uid = lineage_map.get(hl, hl)
        up = int(lv.get('uploaded', s.get('uploaded', 0)) or 0)
        sz = int(lv.get('total_size', s.get('size', 0)) or 0)
        rows.append({
            'uid': uid,
            'hash': hl,
            'name': str(lv.get('name') or s.get('name') or hl),
            'size_bytes': sz,
            'size_fmt': format_file_size(sz),
            'uploaded_bytes': up,
            'uploaded_fmt': format_file_size(up),
            'ratio': round(up / sz, 2) if sz > 0 else 0.0,
            'tags': str(lv.get('tags') or ''),
            'tracker': str(lv.get('tracker') or (s['trackers'][0] if s.get('trackers') else '')),
            'note': notes_map.get(uid, '')
        })

    if fmt == 'json':
        return json.dumps({'exported_at': datetime.datetime.now().isoformat(), 'count': len(rows), 'items': rows}, ensure_ascii=False, indent=2).encode('utf-8'), 'application/json', 'tbr_inventory.json'

    if fmt == 'md':
        lines = [f"# tbr PRO Inventory ({len(rows)} torrents)", "", "| Name | UID | Size | Uploaded | Ratio | Tags | Note |", "|---|---|---|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['name']} | `{r['uid'][:8]}` | {r['size_fmt']} | {r['uploaded_fmt']} | {r['ratio']}x | {r['tags']} | {r['note']} |")
        return "\n".join(lines).encode('utf-8'), 'text/markdown', 'tbr_inventory.md'

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';')
    w.writerow(['UID', 'Hash', 'Name', 'Size', 'Uploaded', 'Ratio', 'Tags', 'Tracker', 'Note'])
    for r in rows:
        w.writerow([
            sanitize_csv_cell(r['uid']), sanitize_csv_cell(r['hash']), sanitize_csv_cell(r['name']),
            r['size_bytes'], r['uploaded_bytes'], r['ratio'],
            sanitize_csv_cell(r['tags']), sanitize_csv_cell(r['tracker']), sanitize_csv_cell(r['note'])
        ])
    return buf.getvalue().encode('utf-8-sig'), 'text/csv', 'tbr_inventory.csv'