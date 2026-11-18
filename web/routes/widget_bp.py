# web/routes/widget_bp.py
import json
from flask import Blueprint, request, jsonify, Response, g
from core.summary_tracker import summary_tracker
from core.profiles_db import profiles_db
from core.widget_service import get_widget_summary, render_widget_chart_png, get_pwa_icon_png

widget_bp = Blueprint('widget_bp', __name__)


@widget_bp.route('/manifest.json')
def pwa_manifest():
    manifest = {
        "name": "tbr PRO — qBittorrent",
        "short_name": "tbr PRO",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#121214",
        "theme_color": "#1a1a20",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}
        ]
    }
    return Response(
        json.dumps(manifest, ensure_ascii=False),
        mimetype='application/manifest+json',
        headers={'Cache-Control': 'no-store'}
    )


@widget_bp.route('/icon-192.png')
def pwa_icon_192():
    return Response(get_pwa_icon_png(192), mimetype='image/png')


@widget_bp.route('/icon-512.png')
def pwa_icon_512():
    return Response(get_pwa_icon_png(512), mimetype='image/png')


@widget_bp.route('/apple-touch-icon.png')
def pwa_apple_icon():
    return Response(get_pwa_icon_png(180), mimetype='image/png')


@widget_bp.route('/api/widget')
def api_widget():
    return jsonify(get_widget_summary(summary_tracker.db))


@widget_bp.route('/api/widget/chart.png')
def api_widget_chart_png():
    hours = request.args.get('hours', 24, type=int)
    w = request.args.get('w', 600, type=int)
    h = request.args.get('h', 220, type=int)
    chart_type = request.args.get('type', 'speed')
    prof = g.get('profile')
    pid = prof['id'] if prof else 0
    ui_settings = profiles_db.get_ui_settings(pid)
    png_bytes = render_widget_chart_png(
        summary_tracker.db, ui_settings,
        hours=hours, width=w, height=h, chart_type=chart_type
    )
    return Response(png_bytes, mimetype='image/png', headers={'Cache-Control': 'no-store'})