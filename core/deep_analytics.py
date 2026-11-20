# core/deep_analytics.py
import time
import datetime
import statistics
from utils.config import cfg
from utils.helpers import format_file_size
from core.scheduler import MIN_DELTA_SEC
from core.disk_monitor import get_monitored_disk_info


def get_rhythm_7x24(db):
    """#14 Ритм канала 7x24: медиана часовых скоростей за последние 45 дней."""
    since_ts = time.time() - (45 * 86400)
    rows = db.get_snapshots_since(since_ts)
    hour_buckets = {}  # (date_str, weekday, hour) -> {'bytes': float, 'sec': float}
    prev = None

    for r in rows:
        if prev is not None:
            t1, t2 = float(prev['timestamp']), float(r['timestamp'])
            dt_sec = t2 - t1
            delta = max(0, int(r['total_uploaded']) - int(prev['total_uploaded']))
            if dt_sec >= MIN_DELTA_SEC and delta > 0:
                cur_ts = datetime.datetime.fromtimestamp(t1).replace(minute=0, second=0, microsecond=0).timestamp()
                while cur_ts < t2:
                    b_end = cur_ts + 3600.0
                    overlap = min(t2, b_end) - max(t1, cur_ts)
                    if overlap > 0:
                        dt_obj = datetime.datetime.fromtimestamp(cur_ts)
                        k = (dt_obj.strftime('%Y-%m-%d'), dt_obj.weekday(), dt_obj.hour)
                        b = hour_buckets.setdefault(k, {'bytes': 0.0, 'sec': 0.0})
                        b['bytes'] += delta * (overlap / dt_sec)
                        b['sec'] += overlap
                    cur_ts = b_end
        prev = r

    samples = {(wd, hr): [] for wd in range(7) for hr in range(24)}
    for (_, wd, hr), b in hour_buckets.items():
        if b['sec'] >= 60:
            samples[(wd, hr)].append((b['bytes'] / b['sec']) / (1024 * 1024))  # MiB/s

    matrix = []
    max_med = 0.0
    for wd in range(7):
        row = []
        for hr in range(24):
            vals = samples[(wd, hr)]
            med = round(statistics.median(vals), 2) if vals else 0.0
            if med > max_med:
                max_med = med
            row.append(med)
        matrix.append(row)
    return {'matrix': matrix, 'max_mbs': round(max_med, 2)}


def get_day_hourly_breakdown(db, date_str):
    """#14 Почасовая разбивка выбранного дня при клике в хитмапе."""
    try:
        d = datetime.datetime.strptime(str(date_str).strip(), '%Y-%m-%d')
    except ValueError:
        return {'success': False, 'error': 'Некорректная дата'}

    start_ts = d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    end_ts = d.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp()
    rows = db.get_snapshots_since(start_ts - 3600)
    hours = {h: 0.0 for h in range(24)}
    points_in_day = 0
    prev = None

    for r in rows:
        ts = float(r['timestamp'])
        if ts > end_ts:
            break
        if start_ts <= ts <= end_ts:
            points_in_day += 1
        if prev is not None:
            t1, t2 = float(prev['timestamp']), ts
            dt_sec = t2 - t1
            delta = max(0, int(r['total_uploaded']) - int(prev['total_uploaded']))
            if dt_sec >= MIN_DELTA_SEC and delta > 0:
                cur_ts = max(start_ts, datetime.datetime.fromtimestamp(t1).replace(minute=0, second=0, microsecond=0).timestamp())
                while cur_ts < min(t2, end_ts):
                    b_end = cur_ts + 3600.0
                    overlap = min(t2, b_end, end_ts) - max(t1, cur_ts, start_ts)
                    if overlap > 0:
                        hr = datetime.datetime.fromtimestamp(cur_ts).hour
                        hours[hr] += delta * (overlap / dt_sec)
                    cur_ts = b_end
        prev = r

    has_detail = points_in_day >= 3
    return {
        'success': True,
        'date': date_str,
        'has_detail': has_detail,
        'hours': [{'hour': f"{h:02d}:00", 'bytes': int(hours[h]), 'fmt': format_file_size(hours[h])} for h in range(24)]
    }


def get_storage_runway(live, summaries):
    """#18 Взлётная полоса диска: остаток после очереди + прогноз дней по темпу 30д."""
    disk = get_monitored_disk_info(live)
    free_b = int(disk.get('free_bytes') or 0)
    queue_left = sum(int(v.get('amount_left', 0) or 0) for v in (live or {}).values() if int(v.get('amount_left', 0) or 0) > 0)
    post_queue_free = max(0, free_b - queue_left)

    now = time.time()
    cutoff_30d = now - (30 * 86400)
    added_30d_bytes = 0
    for s in summaries:
        cts = int(s.get('created_ts') or 0)
        if cts >= cutoff_30d:
            added_30d_bytes += int(s.get('size', 0) or 0)

    daily_growth = added_30d_bytes / 30.0
    reserve_gib = max(0, cfg.getint('Disk_Reserve_GiB', 20))
    usable_after_reserve = max(0, post_queue_free - (reserve_gib * 1024 ** 3))
    days_left = int(usable_after_reserve / daily_growth) if daily_growth > (1024 ** 2) else None

    return {
        'disk_path': disk.get('path', '—'),
        'free_fmt': format_file_size(free_b),
        'queue_left_fmt': format_file_size(queue_left),
        'post_queue_fmt': format_file_size(post_queue_free),
        'daily_growth_fmt': f"{format_file_size(daily_growth)}/день",
        'days_left': days_left,
        'reserve_gib': reserve_gib,
        'guard_triggered': post_queue_free < (reserve_gib * 1024 ** 3)
    }


def _calc_period_metrics(db, start_ts, end_ts):
    rows = db.get_snapshots_since(start_ts - 3600)
    total_b, speeds, peak_hour_map = 0, [], {h: 0.0 for h in range(24)}
    active_counts = []
    prev = None
    for r in rows:
        ts = float(r['timestamp'])
        if ts > end_ts:
            break
        if prev is not None and start_ts <= ts <= end_ts:
            dt = ts - float(prev['timestamp'])
            d = max(0, int(r['total_uploaded']) - int(prev['total_uploaded']))
            if dt >= MIN_DELTA_SEC and d >= 0:
                total_b += d
                speeds.append((d / dt) / (1024 * 1024))
                hr = datetime.datetime.fromtimestamp(ts).hour
                peak_hour_map[hr] += d
                active_counts.append(int(r.get('count', 0) or 0))
        prev = r

    avg_mbs = round(sum(speeds) / len(speeds), 2) if speeds else 0.0
    peak_hr = max(peak_hour_map.items(), key=lambda x: x[1])[0] if any(peak_hour_map.values()) else None
    avg_cnt = int(round(sum(active_counts) / len(active_counts))) if active_counts else 0
    return {'bytes': total_b, 'fmt': format_file_size(total_b), 'avg_mbs': avg_mbs, 'peak_hour': f"{peak_hr:02d}:00" if peak_hr is not None else '—', 'avg_count': avg_cnt}


def compare_periods_ab(db, start_a_str, end_a_str, start_b_str, end_b_str, same_n_days=True):
    """#33 Машина времени: сравнение двух диапазонов дат."""
    try:
        da1 = datetime.datetime.strptime(start_a_str, '%Y-%m-%d')
        da2 = datetime.datetime.strptime(end_a_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        db1 = datetime.datetime.strptime(start_b_str, '%Y-%m-%d')
        db2 = datetime.datetime.strptime(end_b_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    except ValueError:
        return {'success': False, 'error': 'Укажите даты в формате YYYY-MM-DD'}

    if same_n_days:
        days_span = min((da2 - da1).days, (db2 - db1).days)
        da2 = (da1 + datetime.timedelta(days=days_span)).replace(hour=23, minute=59, second=59)
        db2 = (db1 + datetime.timedelta(days=days_span)).replace(hour=23, minute=59, second=59)

    m_a = _calc_period_metrics(db, da1.timestamp(), da2.timestamp())
    m_b = _calc_period_metrics(db, db1.timestamp(), db2.timestamp())
    diff_pct = round(((m_b['bytes'] - m_a['bytes']) / m_a['bytes']) * 100.0, 1) if m_a['bytes'] > 0 else None
    return {'success': True, 'period_a': m_a, 'period_b': m_b, 'diff_pct': diff_pct}


def get_monthly_quota_status(db):
    """#42 Счётчик месячной квоты строго по положительным приращениям из summary_history.db."""
    now_dt = datetime.datetime.now()
    month_start = now_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    rows = db.get_snapshots_since(month_start - 3600)
    used_b, prev = 0, None
    for r in rows:
        ts = float(r['timestamp'])
        if prev is not None and ts >= month_start:
            dt = ts - float(prev['timestamp'])
            d = int(r['total_uploaded']) - int(prev['total_uploaded'])
            if dt >= MIN_DELTA_SEC and d > 0:
                used_b += d
        prev = r

    quota_tib = max(0.0, float(cfg.get('Monthly_Quota_TiB', '0') or 0))
    quota_b = int(quota_tib * (1024 ** 4))
    pct = round(min(100.0, (used_b / quota_b) * 100.0), 1) if quota_b > 0 else 0.0
    elapsed_days = max(0.1, (now_dt.timestamp() - month_start) / 86400.0)
    proj_b = int((used_b / elapsed_days) * 30.0)
    return {
        'used_bytes': used_b, 'used_fmt': format_file_size(used_b),
        'quota_tib': quota_tib, 'quota_fmt': format_file_size(quota_b) if quota_b > 0 else 'Не задана',
        'percent': pct, 'projected_fmt': format_file_size(proj_b)
    }