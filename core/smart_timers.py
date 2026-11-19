# core/smart_timers.py
import time
from utils.config import cfg
from utils.helpers import format_file_size, write_log
from core.app_state_db import app_state_db
from core.notifiers import notify_all
from core.qb_api import (
    detect_qbittorrent_port, get_live_torrent_info, send_qb_command,
    delete_torrents, get_transfer_info, set_global_speed_limits
)

_INACTIVE_STATES = {'pausedup', 'pauseddl', 'stoppedup', 'stoppeddl', 'error', 'missingfiles'}


def get_freeze_status():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = conn.execute("SELECT hash_id, frozen_at FROM smart_freeze").fetchall()
                return {'frozen': len(rows) > 0, 'count': len(rows), 'hashes': [r['hash_id'] for r in rows]}
        except Exception:
            return {'frozen': False, 'count': 0, 'hashes': []}


def freeze_active_torrents(actor='admin'):
    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    if not live:
        return False, "qBittorrent недоступен", 0

    active_hashes = [
        h for h, info in live.items()
        if str(info.get('state', '')).lower() not in _INACTIVE_STATES
    ]
    if not active_hashes:
        return False, "Нет активных раздач для заморозки", 0

    if not send_qb_command(ip, port, 'stop', '|'.join(active_hashes)):
        return False, "Не удалось поставить раздачи на паузу", 0

    now = time.time()
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO smart_freeze (hash_id, frozen_at) VALUES (?, ?)",
                    [(h.lower(), now) for h in active_hashes]
                )
                conn.commit()
        except Exception:
            pass

    app_state_db.add_audit_event('automation', 'Умная заморозка', f'Заморожено раздач: {len(active_hashes)}', actor=actor)
    return True, f"Заморожено активных раздач: {len(active_hashes)}", len(active_hashes)


def unfreeze_torrents(actor='admin'):
    st = get_freeze_status()
    saved_hashes = st.get('hashes') or []
    if not saved_hashes:
        return False, "Список заморозки пуст", 0

    ip, port = detect_qbittorrent_port(cfg.config)
    live = get_live_torrent_info(ip, port) if port else {}
    live_map = {h.lower(): h for h in live.keys()}

    to_start = [live_map[h.lower()] for h in saved_hashes if h.lower() in live_map]
    if to_start and port:
        send_qb_command(ip, port, 'start', '|'.join(to_start))

    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("DELETE FROM smart_freeze")
                conn.commit()
        except Exception:
            pass

    app_state_db.add_audit_event('automation', 'Разморозка', f'Возобновлено раздач: {len(to_start)}', actor=actor)
    return True, f"Возобновлено раздач: {len(to_start)} (удалённые пропущены)", len(to_start)


def get_snooze_status():
    now = time.time()
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                row = conn.execute(
                    "SELECT id, resume_at, mode, created_at FROM snooze_timers WHERE active = 1 ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row and row['resume_at'] > now:
                    return {
                        'active': True,
                        'id': row['id'],
                        'resume_at': int(row['resume_at']),
                        'remaining_sec': int(row['resume_at'] - now),
                        'mode': row['mode']
                    }
        except Exception:
            pass
    return {'active': False, 'resume_at': 0, 'remaining_sec': 0, 'mode': 'pause'}


def start_snooze(minutes, mode='pause', actor='admin'):
    mins = max(1, min(1440, int(minutes or 30)))
    m = 'limit' if mode == 'limit' else 'pause'
    ip, port = detect_qbittorrent_port(cfg.config)
    if not port:
        return False, "qBittorrent недоступен"

    if m == 'pause':
        ok, msg, _ = freeze_active_torrents(actor=actor)
        if not ok and "Нет активных" not in msg:
            return False, msg
    else:
        tr = get_transfer_info(ip, port)
        cfg.set('Snooze_Saved_DL', str(int(tr.get('dl_rate_limit', 0) or 0)))
        cfg.set('Snooze_Saved_UP', str(int(tr.get('up_rate_limit', 0) or 0)))
        cfg.save()
        set_global_speed_limits(ip, port, 1, 1)

    now = time.time()
    resume_at = now + (mins * 60)
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("UPDATE snooze_timers SET active = 0 WHERE active = 1")
                conn.execute(
                    "INSERT INTO snooze_timers (resume_at, mode, active, created_at) VALUES (?, ?, 1, ?)",
                    (resume_at, m, now)
                )
                conn.commit()
        except Exception:
            pass

    app_state_db.add_audit_event('automation', 'Таймер сна (Snooze)', f'{mins} мин, режим={m}', actor=actor)
    return True, f"Таймер сна включён на {mins} мин"


def cancel_snooze(actor='admin', auto_triggered=False):
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                row = conn.execute("SELECT id, mode FROM snooze_timers WHERE active = 1 ORDER BY id DESC LIMIT 1").fetchone()
                conn.execute("UPDATE snooze_timers SET active = 0 WHERE active = 1")
                conn.commit()
        except Exception:
            row = None

    if not row:
        return False, "Активный таймер не найден"

    mode = row['mode']
    if mode == 'pause':
        unfreeze_torrents(actor=actor)
    else:
        ip, port = detect_qbittorrent_port(cfg.config)
        if port:
            dl = cfg.getint('Snooze_Saved_DL', 0)
            up = cfg.getint('Snooze_Saved_UP', 0)
            set_global_speed_limits(ip, port, dl, up)

    title = "⏰ Таймер сна завершён" if auto_triggered else "⏰ Таймер сна отменён"
    app_state_db.add_audit_event('automation', title, f'mode={mode}', actor=actor)
    if auto_triggered:
        notify_all(title, ["Ограничения сняты, раздачи возвращены в работу."])
    return True, title


def tick_snooze():
    now = time.time()
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                row = conn.execute(
                    "SELECT id FROM snooze_timers WHERE active = 1 AND resume_at <= ? LIMIT 1", (now,)
                ).fetchone()
        except Exception:
            row = None
    if row:
        cancel_snooze(actor='scheduler', auto_triggered=True)


def list_expirations():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = conn.execute("SELECT * FROM expiration_timers ORDER BY created_at DESC").fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []


def set_expiration(t_hash, hours=0.0, target_up_bytes=0, delete_files=False, actor='admin'):
    hl = str(t_hash or '').strip().lower()
    hrs = max(0.0, float(hours or 0))
    tgt = max(0, int(target_up_bytes or 0))
    if not hl or (hrs <= 0 and tgt <= 0):
        return False, "Укажите срок (часы/дни) или порог отдачи"

    now = time.time()
    expires_at = (now + hrs * 3600.0) if hrs > 0 else None
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO expiration_timers
                       (hash_id, expires_at, target_uploaded, delete_files, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (hl, expires_at, tgt if tgt > 0 else None, 1 if delete_files else 0, now)
                )
                conn.commit()
        except Exception as e:
            return False, str(e)

    app_state_db.add_audit_event('automation', 'Таймер удаления задан', f'{hl[:8]} (delete_files={bool(delete_files)})', actor=actor)
    return True, "Таймер самоуничтожения установлен"


def remove_expiration(t_hash):
    hl = str(t_hash or '').strip().lower()
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("DELETE FROM expiration_timers WHERE hash_id = ?", (hl,))
                conn.commit()
                return True
        except Exception:
            return False


def tick_expirations(ip, port, live):
    if not port or not live:
        return 0
    rows = list_expirations()
    if not rows:
        return 0

    now = time.time()
    live_map = {h.lower(): (h, info) for h, info in live.items()}
    triggered = 0

    for r in rows:
        hl = r['hash_id'].lower()
        if hl not in live_map:
            remove_expiration(hl)
            continue
        raw_hash, info = live_map[hl]
        up = int(info.get('uploaded', 0) or 0)
        exp_ts = r.get('expires_at')
        tgt_up = r.get('target_uploaded')
        hit_time = bool(exp_ts and now >= float(exp_ts))
        hit_up = bool(tgt_up and int(tgt_up) > 0 and up >= int(tgt_up))

        if hit_time or hit_up:
            del_files = bool(r.get('delete_files'))
            if delete_torrents(ip, port, raw_hash, delete_files=del_files):
                remove_expiration(hl)
                triggered += 1
                nm = str(info.get('name') or hl)
                act = "с файлами на диске" if del_files else "только из клиента"
                write_log('automation', f"Expiration Timer: удалён '{nm}' ({act})")
                app_state_db.add_audit_event('automation', 'Срок жизни истёк', f"'{nm}' удалён ({act})")
                notify_all("⏳ Срок жизни раздачи истёк", [f"Раздача: {nm}", f"Отдано: {format_file_size(up)}", f"Удалена {act}."])
    return triggered