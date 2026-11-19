# core/achievements.py
import json
import time
import datetime
from utils.config import cfg
from utils.helpers import write_error_log
from core.app_state_db import app_state_db
from core.qb_api import detect_qbittorrent_port, get_live_torrent_info
from core.torrent_parser import get_global_torrent_summaries
from core.summary_tracker import summary_tracker
from core.health_score import compute_health_metrics

ACHIEVEMENTS_CATALOG = [
    {'code': 'first_tb', 'icon': '🥉', 'title': 'Первый терабайт', 'title_en': 'First Terabyte', 'desc': 'Отдать суммарно 1 TiB данных', 'desc_en': 'Upload 1 TiB in total'},
    {'code': 'ten_tb', 'icon': '🥈', 'title': 'Мастер раздач', 'title_en': 'Seed Master', 'desc': 'Отдать суммарно 10 TiB данных', 'desc_en': 'Upload 10 TiB in total'},
    {'code': 'fifty_tb', 'icon': '🥇', 'title': 'Властелин сидбокса', 'title_en': 'Seedbox Overlord', 'desc': 'Отдать суммарно 50 TiB данных', 'desc_en': 'Upload 50 TiB in total'},
    {'code': 'veteran_100d', 'icon': '🎖️', 'title': 'Ветеран раздачи', 'title_en': '100-Day Veteran', 'desc': 'Держать раздачу в активе 100+ дней', 'desc_en': 'Keep a torrent active for 100+ days'},
    {'code': 'keeper_5', 'icon': '🛡️', 'title': 'Хранитель', 'title_en': 'The Keeper', 'desc': 'Быть единственным сидом на 5+ раздачах', 'desc_en': 'Be the only seeder on 5+ torrents'},
    {'code': 'night_shift_500g', 'icon': '🌙', 'title': 'Ночная смена', 'title_en': 'Night Shift', 'desc': 'Отдать 500+ GiB за одну ночь (00:00–08:00)', 'desc_en': 'Upload 500+ GiB in one night (00:00–08:00)'},
    {'code': 'ratio_god', 'icon': '🔥', 'title': 'Бог Ratio', 'title_en': 'Ratio God', 'desc': 'Раздача >= 100 GiB с Ratio >= 10.0x', 'desc_en': 'Torrent >= 100 GiB with Ratio >= 10.0x'},
    {'code': 'collector_100', 'icon': '📦', 'title': 'Коллекционер', 'title_en': 'Hoarder', 'desc': 'Держать в клиенте 100+ раздач одновременно', 'desc_en': 'Seed 100+ torrents simultaneously'},
    {'code': 'marathon_1tb', 'icon': '⚡', 'title': 'Суточный марафон', 'title_en': 'Daily Marathon', 'desc': 'Отдать 1+ TiB за одни сутки', 'desc_en': 'Upload 1+ TiB in a single day'},
    {'code': 'surgeon', 'icon': '🩺', 'title': 'Главный хирург', 'title_en': 'Chief Surgeon', 'desc': 'Провести хотя бы один мердж .fastresume', 'desc_en': 'Complete at least one .fastresume merge'},
]

_LAST_EVAL_TS = 0.0


def _get_unlocked_map():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = conn.execute("SELECT code, unlocked_at, meta_json FROM achievements").fetchall()
                return {r['code']: {'unlocked_at': r['unlocked_at'], 'meta_json': r['meta_json']} for r in rows}
        except Exception:
            return {}


def _unlock(code, meta=None):
    now = time.time()
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO achievements (code, unlocked_at, meta_json) VALUES (?, ?, ?)",
                    (code, now, json.dumps(meta or {}, ensure_ascii=False))
                )
                conn.commit()
        except Exception as e:
            write_error_log(f"unlock achievement {code}", e)


def _check_night_and_day_records():
    rows = summary_tracker.db.get_snapshots_since(time.time() - 60 * 86400)
    night_by_date = {}
    day_by_date = {}
    prev = None
    for r in rows:
        if prev is not None:
            d = max(0, int(r['total_uploaded']) - int(prev['total_uploaded']))
            dt = float(r['timestamp']) - float(prev['timestamp'])
            if dt >= 60 and d > 0 and (d / dt) < (1024 ** 3):
                dt_obj = datetime.datetime.fromtimestamp(r['timestamp'])
                ds = dt_obj.strftime('%Y-%m-%d')
                day_by_date[ds] = day_by_date.get(ds, 0) + d
                if 0 <= dt_obj.hour < 8:
                    night_by_date[ds] = night_by_date.get(ds, 0) + d
        prev = r
    max_night = max(night_by_date.values(), default=0)
    max_day = max(day_by_date.values(), default=0)
    return max_night >= (500 * 1024 ** 3), max_day >= (1024 ** 4)


def evaluate_achievements(force=False):
    global _LAST_EVAL_TS
    now = time.time()
    if not force and (now - _LAST_EVAL_TS) < 3600:
        return
    _LAST_EVAL_TS = now

    unlocked = _get_unlocked_map()
    if len(unlocked) == len(ACHIEVEMENTS_CATALOG):
        return

    summaries = get_global_torrent_summaries()
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    live_lower = {k.lower(): v for k, v in live.items()}

    tot_up = 0
    max_act = 0
    last_seed_cnt = 0
    has_ratio_god = False

    for s in summaries:
        hl = (s.get('hash_id') or '').lower()
        lv = live_lower.get(hl, {})
        up = int(lv.get('uploaded', s.get('uploaded', 0)) or 0)
        sz = int(lv.get('total_size', s.get('size', 1)) or 1)
        act = int(s.get('active_seconds', 0) or 0)
        tot_up += up
        if act > max_act:
            max_act = act
        if sz >= (100 * 1024 ** 3) and (up / sz) >= 10.0:
            has_ratio_god = True
        if lv and compute_health_metrics(lv).get('is_last_seed'):
            last_seed_cnt += 1

    checks = {
        'first_tb': tot_up >= (1024 ** 4),
        'ten_tb': tot_up >= (10 * 1024 ** 4),
        'fifty_tb': tot_up >= (50 * 1024 ** 4),
        'veteran_100d': max_act >= (100 * 86400),
        'keeper_5': last_seed_cnt >= 5,
        'ratio_god': has_ratio_god,
        'collector_100': len(summaries) >= 100,
    }

    if 'night_shift_500g' not in unlocked or 'marathon_1tb' not in unlocked:
        hit_night, hit_day = _check_night_and_day_records()
        checks['night_shift_500g'] = hit_night
        checks['marathon_1tb'] = hit_day

    if 'surgeon' not in unlocked:
        checks['surgeon'] = len(app_state_db.get_audit_events(category='merger', limit=1)) > 0

    for code, ok in checks.items():
        if ok and code not in unlocked:
            _unlock(code)


def get_achievements_view():
    evaluate_achievements(force=False)
    unlocked = _get_unlocked_map()
    out = []
    for item in ACHIEVEMENTS_CATALOG:
        u = unlocked.get(item['code'])
        dt_str = datetime.datetime.fromtimestamp(u['unlocked_at']).strftime('%Y-%m-%d %H:%M') if u else None
        out.append({
            **item,
            'unlocked': bool(u),
            'unlocked_at': dt_str,
        })
    return {
        'unlocked_count': sum(1 for x in out if x['unlocked']),
        'total_count': len(out),
        'items': out,
    }