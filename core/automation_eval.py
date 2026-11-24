# core/automation_eval.py
from utils.helpers import format_file_size
from core.summary_tracker import summary_tracker

VALID_TIME_MODES = ('seeding_time', 'time_active')
VALID_SPEED_OPS = ('', '>=', '<')


def format_duration_ru(seconds):
    sec = max(0, int(seconds or 0))
    if sec >= 86400:
        return f"{sec // 86400} д {(sec % 86400) // 3600} ч"
    if sec >= 3600:
        return f"{sec // 3600} ч"
    return f"{sec // 60} мин"


def evaluate_rule_match(engine, r, t_hash, info, now_ts, ignore_history=False):
    t_mode = r.get('time_mode') if r.get('time_mode') in VALID_TIME_MODES else 'seeding_time'
    min_r = float(r.get('min_ratio', 0) or 0)
    min_d = float(r.get('min_seed_days', 0) or 0)
    min_up = int(r.get('min_uploaded_bytes', 0) or 0)
    s_op = r.get('speed_op', '') or ''
    s_bytes = float(r.get('speed_bytes', 0) or 0)
    w_sec = max(60, int(r.get('speed_window_min', 60) or 60) * 60)
    use_speed = (s_op in ('>=', '<') and s_bytes > 0)
    if min_r <= 0 and min_d <= 0 and min_up <= 0 and not use_speed:
        return None

    ratio = float(info.get('ratio', 0) or 0)
    uploaded = int(info.get('uploaded', 0) or 0)
    time_sec = float(info.get(t_mode, 0) or 0)
    if (min_r > 0 and ratio < min_r) or (min_d > 0 and (time_sec / 86400.0) < min_d) or (min_up > 0 and uploaded < min_up):
        return None

    v_avg = None
    if use_speed:
        first, last, cnt = summary_tracker.db.get_torrent_window_bounds(t_hash, now_ts - w_sec, now_ts)
        if cnt < 2 or not first or not last or (last[0] - first[0]) < (0.5 * w_sec):
            return None
        v_avg = max(0.0, (last[1] - first[1]) / (last[0] - first[0]))
        if (s_op == '>=' and v_avg < s_bytes) or (s_op == '<' and v_avg >= s_bytes):
            return None

    if not ignore_history and engine._is_triggered(r['id'], t_hash):
        return None

    cur_tags = {tg.strip().lower() for tg in str(info.get('tags', '') or '').split(',') if tg.strip()}
    add_tag = str(r.get('action_tag', '') or '').strip()
    rem_tag = str(r.get('action_remove_tag', '') or '').strip()
    want_pause = bool(r.get('action_pause'))
    planned = []
    if want_pause:
        planned.append("⏸️ Пауза")
    if add_tag and add_tag.lower() not in cur_tags:
        planned.append(f"🏷️ +Тег: {add_tag}")
    if rem_tag and rem_tag.lower() in cur_tags:
        planned.append(f"✂️ -Тег: {rem_tag}")

    return {
        'rule_id': r['id'], 'rule_name': r['name'], 'hash': t_hash, 'name': info.get('name', t_hash),
        'ratio': ratio, 'uploaded': uploaded, 'uploaded_fmt': format_file_size(uploaded),
        'time_mode': t_mode, 'time_sec': time_sec, 'dur_fmt': format_duration_ru(time_sec),
        'v_avg': v_avg, 'want_pause': want_pause,
        'add_tag': add_tag if (add_tag and add_tag.lower() not in cur_tags) else '',
        'rem_tag': rem_tag if (rem_tag and rem_tag.lower() in cur_tags) else '',
        'planned': planned, 'already_triggered': engine._is_triggered(r['id'], t_hash)
    }