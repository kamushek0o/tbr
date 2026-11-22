# web/routes/inbox_ops_bp.py
import json
import datetime
from flask import Blueprint, request, jsonify, g
from utils.config import cfg
from core.qb_api import detect_qbittorrent_port, set_global_speed_limits
from core.preflight_inbox import preflight_analyze, add_torrent_to_qb, get_update_radar, prepare_qb_update_safe
from core.autopilot_extras import toggle_sniper, list_snipers, get_conductor_config
from core.saved_views import list_saved_views, add_saved_view, delete_saved_view
from core.app_state_db import app_state_db
from web.security import HASH_RE

inbox_ops_bp = Blueprint('inbox_ops_bp', __name__)
_VALID_ROUTER_FIELDS = {'tracker', 'ext', 'min_gib'}


def _not_admin():
    return g.get('role') != 'admin'


@inbox_ops_bp.route('/api/inbox/preflight', methods=['POST'])
def api_inbox_preflight():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    f = request.files.get('file')
    if f:
        return jsonify(preflight_analyze(torrent_bytes=f.read(), save_path=request.form.get('save_path', '')))
    d = request.get_json(silent=True) or {}
    return jsonify(preflight_analyze(magnet_or_url=d.get('url', ''), save_path=d.get('save_path', '')))


@inbox_ops_bp.route('/api/inbox/add', methods=['POST'])
def api_inbox_add():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    f = request.files.get('file')
    if f:
        ok, msg = add_torrent_to_qb(
            torrent_bytes=f.read(), filename=f.filename or 'upload.torrent',
            savepath=request.form.get('save_path', '').strip(),
            tags=request.form.get('tags', '').strip(),
            paused=request.form.get('paused', '0') == '1'
        )
    else:
        d = request.get_json(silent=True) or {}
        ok, msg = add_torrent_to_qb(
            magnet_or_url=d.get('url', ''), savepath=str(d.get('save_path', '')).strip(),
            tags=str(d.get('tags', '')).strip(), paused=bool(d.get('paused', False))
        )
    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)


@inbox_ops_bp.route('/api/snipers', methods=['GET', 'POST'])
def api_snipers():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    if request.method == 'GET':
        return jsonify({'hashes': list_snipers()})
    d = request.get_json(silent=True) or {}
    h = str(d.get('hash', '')).strip()
    if not HASH_RE.fullmatch(h):
        return jsonify({'success': False, 'error': 'Некорректный хэш'}), 400
    try:
        idle_h = max(0.5, float(d.get('idle_hours') or 4.0))
    except (ValueError, TypeError):
        idle_h = 4.0
    ok, active = toggle_sniper(h, idle_hours=idle_h)
    return jsonify({'success': ok, 'active': active})


@inbox_ops_bp.route('/api/views', methods=['GET', 'POST'])
def api_views():
    if request.method == 'GET':
        return jsonify({'views': list_saved_views()})
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    d = request.get_json(silent=True) or {}
    vid = add_saved_view(d.get('name', ''), d.get('filters') or {})
    return jsonify({'success': bool(vid), 'id': vid}), (200 if vid else 400)


@inbox_ops_bp.route('/api/views/delete', methods=['POST'])
def api_views_delete():
    if _not_admin():
        return jsonify({'success': False}), 403
    vid = (request.get_json(silent=True) or {}).get('id')
    try:
        vid_i = int(vid)
    except (ValueError, TypeError):
        return jsonify({'success': False}), 400
    return jsonify({'success': delete_saved_view(vid_i)})


@inbox_ops_bp.route('/api/conductor', methods=['GET', 'POST'])
def api_conductor():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    if request.method == 'GET':
        c = get_conductor_config()
        c['smart_queue'] = cfg.getboolean('Smart_Queue_Enabled', False)
        c['smart_reannounce'] = cfg.getboolean('Smart_Reannounce_Enabled', False)
        return jsonify(c)
    d = request.get_json(silent=True) or {}
    enabled = bool(d.get('enabled', False))
    cfg.set('Conductor_Enabled', str(enabled))
    if isinstance(d.get('blocks'), list):
        cfg.set('Conductor_Blocks_JSON', json.dumps(d['blocks'], ensure_ascii=False))
    if 'smart_queue' in d:
        cfg.set('Smart_Queue_Enabled', str(bool(d.get('smart_queue'))))
    if 'smart_reannounce' in d:
        cfg.set('Smart_Reannounce_Enabled', str(bool(d.get('smart_reannounce'))))
    if not enabled and cfg.getint('Conductor_Last_Applied_Up', 0) > 0:
        ip, port = detect_qbittorrent_port(cfg.config)
        if port:
            set_global_speed_limits(ip, port, 0, 0)
        cfg.set('Conductor_Last_Applied_Up', '0')
    cfg.save()
    return jsonify({'success': True})


@inbox_ops_bp.route('/api/conductor/override', methods=['POST'])
def api_conductor_override():
    if _not_admin():
        return jsonify({'success': False}), 403
    now_dt = datetime.datetime.now()
    next_hr = (now_dt.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)).timestamp()
    cfg.set('Conductor_Override_Until', str(int(next_hr)))
    if cfg.getint('Conductor_Last_Applied_Up', 0) > 0:
        ip, port = detect_qbittorrent_port(cfg.config)
        if port:
            set_global_speed_limits(ip, port, 0, 0)
        cfg.set('Conductor_Last_Applied_Up', '0')
    cfg.save()
    return jsonify({'success': True, 'until': int(next_hr)})


@inbox_ops_bp.route('/api/router/rules', methods=['GET', 'POST'])
def api_router_rules():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    if request.method == 'GET':
        with app_state_db._lock:
            with app_state_db._get_conn() as conn:
                return jsonify({'rules': [dict(r) for r in conn.execute("SELECT * FROM auto_router_rules ORDER BY priority ASC, id ASC").fetchall()]})
    d = request.get_json(silent=True) or {}
    fld = str(d.get('match_field', 'tracker')).strip()
    if fld not in _VALID_ROUTER_FIELDS:
        return jsonify({'success': False, 'error': 'Некорректное поле условия'}), 400
    pat = str(d.get('pattern', '')).strip()
    if not pat:
        return jsonify({'success': False, 'error': 'Укажите непустой паттерн'}), 400
    if fld == 'min_gib':
        try:
            if float(pat) <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Для min_gib укажите число > 0'}), 400
    cat = str(d.get('category', '')).strip()
    path = str(d.get('path', '')).strip()
    if not cat and not path:
        return jsonify({'success': False, 'error': 'Укажите категорию или путь назначения'}), 400
    try:
        prio = int(d.get('priority', 10) or 10)
    except (ValueError, TypeError):
        prio = 10

    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO auto_router_rules (priority, match_field, pattern, target_category, target_path) VALUES (?, ?, ?, ?, ?)",
                (prio, fld, pat, cat, path)
            )
            conn.commit()
            return jsonify({'success': True, 'id': cur.lastrowid})


@inbox_ops_bp.route('/api/router/delete', methods=['POST'])
def api_router_delete():
    if _not_admin():
        return jsonify({'success': False}), 403
    rid = (request.get_json(silent=True) or {}).get('id')
    try:
        rid_i = int(rid)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Некорректный ID'}), 400
    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            conn.execute("DELETE FROM auto_router_rules WHERE id = ?", (rid_i,))
            conn.commit()
    return jsonify({'success': True})


@inbox_ops_bp.route('/api/radar/updates')
def api_radar_updates():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    return jsonify(get_update_radar(force=request.args.get('force', '0') == '1'))


@inbox_ops_bp.route('/api/radar/prepare_qb', methods=['POST'])
def api_radar_prepare_qb():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    return jsonify(prepare_qb_update_safe())