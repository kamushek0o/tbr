# core/torrent_targets.py
import time
from utils.helpers import format_file_size, write_error_log
from core.app_state_db import app_state_db
from core.notifiers import notify_all


def list_targets():
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                rows = conn.execute("SELECT * FROM torrent_targets").fetchall()
                return {r['hash_id'].lower(): dict(r) for r in rows}
        except Exception:
            return {}


def set_target(t_hash, target_ratio=0.0, target_bytes=0, actor='admin'):
    hl = str(t_hash or '').strip().lower()
    tr = max(0.0, float(target_ratio or 0))
    tb = max(0, int(target_bytes or 0))
    if not hl or (tr <= 0 and tb <= 0):
        return False, "Укажите целевой Ratio или объём отдачи"

    now = time.time()
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO torrent_targets
                       (hash_id, target_ratio, target_bytes, achieved_at, updated_at)
                       VALUES (?, ?, ?, NULL, ?)""",
                    (hl, tr, tb, now)
                )
                conn.commit()
        except Exception as e:
            write_error_log("set_target", e)
            return False, str(e)

    app_state_db.add_audit_event('system', 'Цель раздачи задана', f'{hl[:8]} ratio={tr} bytes={tb}', actor=actor)
    return True, "Цель сохранена"


def delete_target(t_hash):
    hl = str(t_hash or '').strip().lower()
    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                conn.execute("DELETE FROM torrent_targets WHERE hash_id = ?", (hl,))
                conn.commit()
                return True
        except Exception:
            return False


def handle_targets_on_merge(old_hash, new_hash, final_uploaded=0):
    """
    При мердже переносит цель на получателя (если у цели её не было).
    При сложении сразу проверяет достижение планки по новому объёму отдачи.
    """
    oh = str(old_hash or '').strip().lower()
    nh = str(new_hash or '').strip().lower()
    if not oh or not nh or oh == nh:
        return False

    with app_state_db._lock:
        try:
            with app_state_db._get_conn() as conn:
                src_row = conn.execute("SELECT * FROM torrent_targets WHERE hash_id = ?", (oh,)).fetchone()
                dst_row = conn.execute("SELECT * FROM torrent_targets WHERE hash_id = ?", (nh,)).fetchone()

                active_target = None
                if src_row and not dst_row:
                    conn.execute(
                        """INSERT OR REPLACE INTO torrent_targets
                           (hash_id, target_ratio, target_bytes, achieved_at, updated_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (nh, src_row['target_ratio'], src_row['target_bytes'], src_row['achieved_at'], time.time())
                    )
                    active_target = src_row
                elif dst_row:
                    active_target = dst_row

                if active_target and final_uploaded > 0:
                    tgt_bytes = int(active_target['target_bytes'] or 0)
                    if tgt_bytes > 0 and final_uploaded >= tgt_bytes and not active_target['achieved_at']:
                        conn.execute("UPDATE torrent_targets SET achieved_at = ? WHERE hash_id = ?", (time.time(), nh))

                if src_row:
                    conn.execute("DELETE FROM torrent_targets WHERE hash_id = ?", (oh,))

                conn.commit()
                return bool(active_target)
        except Exception as e:
            write_error_log("handle_targets_on_merge", e)
            return False


def transfer_target_on_merge(old_hash, new_hash):
    return handle_targets_on_merge(old_hash, new_hash)


def compute_target_progress(target_row, uploaded, ratio):
    if not target_row:
        return None
    tr = float(target_row.get('target_ratio') or 0)
    tb = int(target_row.get('target_bytes') or 0)
    pcts = []
    if tr > 0:
        pcts.append(min(100.0, (float(ratio or 0) / tr) * 100.0))
    if tb > 0:
        pcts.append(min(100.0, (int(uploaded or 0) / tb) * 100.0))
    if not pcts:
        return None
    pct = round(max(pcts), 1)
    return {
        'target_ratio': tr,
        'target_bytes': tb,
        'target_bytes_fmt': format_file_size(tb) if tb > 0 else '',
        'percent': pct,
        'achieved': pct >= 100.0 or bool(target_row.get('achieved_at'))
    }


def evaluate_targets(live):
    targets = list_targets()
    if not targets or not live:
        return 0

    now = time.time()
    live_map = {h.lower(): info for h, info in live.items()}
    newly_achieved = 0

    for hl, row in targets.items():
        if row.get('achieved_at'):
            continue
        info = live_map.get(hl)
        if not info:
            continue
        up = int(info.get('uploaded', 0) or 0)
        ratio = float(info.get('ratio', 0) or 0)
        tr = float(row.get('target_ratio') or 0)
        tb = int(row.get('target_bytes') or 0)
        hit = (tr > 0 and ratio >= tr) or (tb > 0 and up >= tb)
        if not hit:
            continue

        with app_state_db._lock:
            try:
                with app_state_db._get_conn() as conn:
                    conn.execute("UPDATE torrent_targets SET achieved_at = ? WHERE hash_id = ?", (now, hl))
                    conn.commit()
            except Exception:
                continue

        newly_achieved += 1
        nm = str(info.get('name') or hl)
        app_state_db.add_audit_event('automation', 'Цель раздачи достигнута', nm)
        notify_all("🎯 Цель раздачи достигнута!", [f"Раздача: {nm}", f"Отдано: {format_file_size(up)} | Ratio: {ratio:.2f}x"])

    return newly_achieved