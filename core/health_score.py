# core/health_score.py
from core.torrent_targets import compute_target_progress


def compute_health_metrics(live_item):
    if not live_item:
        return {
            'health_score': -1.0,
            'health_label': 'нет данных',
            'num_complete': -1,
            'num_incomplete': -1,
            'is_last_seed': False,
        }

    num_complete = int(live_item.get('num_complete', -1) if live_item.get('num_complete') is not None else -1)
    num_incomplete = int(live_item.get('num_incomplete', -1) if live_item.get('num_incomplete') is not None else -1)
    progress = float(live_item.get('progress', 0.0) or 0.0)

    if num_complete < 0 or num_incomplete < 0:
        return {
            'health_score': -1.0,
            'health_label': 'нет данных',
            'num_complete': num_complete,
            'num_incomplete': num_incomplete,
            'is_last_seed': False,
        }

    if num_complete == 0 and num_incomplete > 0:
        score = round(num_incomplete * 100.0 + 50.0, 1)
    else:
        score = round((num_incomplete * 100.0) / (num_complete + 1), 1)

    is_last_seed = (progress >= 0.9999 and num_complete == 0)
    return {
        'health_score': score,
        'health_label': f"{score:.1f}",
        'num_complete': num_complete,
        'num_incomplete': num_incomplete,
        'is_last_seed': is_last_seed,
    }


def enrich_live_metrics(item, live_item, target_row=None):
    hm = compute_health_metrics(live_item)
    item.update(hm)
    item['upspeed'] = int((live_item or {}).get('upspeed', 0) or 0)
    item['dlspeed'] = int((live_item or {}).get('dlspeed', 0) or 0)
    item['progress'] = float((live_item or {}).get('progress', 0.0) or 0.0)
    item['target'] = compute_target_progress(
        target_row,
        int(item.get('uploaded', 0) or 0),
        float(item.get('ratio', 0.0) or 0.0)
    )
    return item