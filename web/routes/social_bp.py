# web/routes/social_bp.py
import datetime
from flask import Blueprint, request, jsonify, g
from core.app_state_db import app_state_db
from core.achievements import get_achievements_view

social_bp = Blueprint('social_bp', __name__)
_VALID_AUDIT_CATS = {'', 'auth', 'automation', 'merger', 'system'}


@social_bp.route('/api/tools/audit')
def api_tools_audit():
    if g.get('role') != 'admin':
        return jsonify({'error': 'Только для Admin'}), 403
    cat = str(request.args.get('category', '')).strip().lower()
    if cat not in _VALID_AUDIT_CATS:
        cat = ''
    limit = max(10, min(200, request.args.get('limit', 100, type=int)))
    rows = app_state_db.get_audit_events(category=cat, limit=limit)
    for r in rows:
        ts = float(r.get('created_at') or 0)
        r['datetime'] = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S') if ts else '—'
    return jsonify({'items': rows})


@social_bp.route('/api/achievements')
def api_achievements():
    return jsonify(get_achievements_view())