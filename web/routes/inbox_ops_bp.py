# web/routes/inbox_ops_bp.py
import json
import time
import datetime
from flask import Blueprint, request, jsonify, g
from utils.config import cfg
from core.preflight_inbox import preflight_analyze, add_torrent_to_qb, get_update_radar, prepare_qb_update_safe
from core.autopilot_extras import toggle_sniper, list_snipers, get_conductor_config
from core.saved_views import list_saved_views, add_saved_view, delete_saved_view
from core.app_state_db import app_state_db
from web.security import HASH_RE

inbox_ops_bp = Blueprint('inbox_ops_bp', __name__)


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
    ok, active = toggle_sniper(h, idle_hours=float(d.get('idle_hours') or 4.0))
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
    return jsonify({'success': bool(vid and delete_saved_view(vid))})


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
    cfg.set('Conductor_Enabled', str(bool(d.get('enabled', False))))
    if isinstance(d.get('blocks'), list):
        cfg.set('Conductor_Blocks_JSON', json.dumps(d['blocks'], ensure_ascii=False))
    if 'smart_queue' in d:
        cfg.set('Smart_Queue_Enabled', str(bool(d['smart_queue'])))
    if 'smart_reannounce' in d:
        cfg.set('Smart_Reannounce_Enabled', str(bool(d['smart_reannounce'])))
    cfg.save()
    return jsonify({'success': True})


@inbox_ops_bp.route('/api/conductor/override', methods=['POST'])
def api_conductor_override():
    if _not_admin():
        return jsonify({'success': False}), 403
    now_dt = datetime.datetime.now()
    next_hr = (now_dt.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)).timestamp()
    cfg.set('Conductor_Override_Until', str(int(next_hr)))
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
    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO auto_router_rules (priority, match_field, pattern, target_category, target_path) VALUES (?, ?, ?, ?, ?)",
                (int(d.get('priority', 10)), str(d.get('match_field', 'tracker')), str(d.get('pattern', '')).strip(), str(d.get('category', '')).strip(), str(d.get('path', '')).strip())
            )
            conn.commit()
            return jsonify({'success': True, 'id': cur.lastrowid})


@inbox_ops_bp.route('/api/router/delete', methods=['POST'])
def api_router_delete():
    if _not_admin():
        return jsonify({'success': False}), 403
    rid = (request.get_json(silent=True) or {}).get('id')
    with app_state_db._lock:
        with app_state_db._get_conn() as conn:
            conn.execute("DELETE FROM auto_router_rules WHERE id = ?", (int(rid),))
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