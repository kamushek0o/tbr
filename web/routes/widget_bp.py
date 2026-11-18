# web/routes/widget_bp.py
import io
import json
from PIL import Image
from flask import Blueprint, request, jsonify, Response, g
from core.summary_tracker import summary_tracker
from core.profiles_db import profiles_db
from core.widget_service import get_widget_summary, render_widget_chart_png, get_pwa_icon_png

widget_bp = Blueprint('widget_bp', __name__)
_FAVICON_CACHE = None


@widget_bp.route('/favicon.ico')
def favicon_ico():
    global _FAVICON_CACHE
    if _FAVICON_CACHE is None:
        img = Image.open(io.BytesIO(get_pwa_icon_png(64)))
        buf = io.BytesIO()
        img.save(buf, format='ICO', sizes=[(32, 32), (64, 64)])
        _FAVICON_CACHE = buf.getvalue()
    return Response(_FAVICON_CACHE, mimetype='image/x-icon', headers={'Cache-Control': 'public, max-age=86400'})


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
    return Response(json.dumps(manifest, ensure_ascii=False), mimetype='application/manifest+json', headers={'Cache-Control': 'no-store'})


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
    prof = g.get('profile')
    ui_settings = profiles_db.get_ui_settings(prof['id'] if prof else 0)
    top_period = request.args.get('top_period')
    top_scale = request.args.get('top_scale')
    return jsonify(get_widget_summary(summary_tracker.db, ui_settings=ui_settings, top_period=top_period, top_scale=top_scale))


@widget_bp.route('/api/widget/chart.png')
def api_widget_chart_png():
    hours = request.args.get('hours', 24, type=int)
    w = request.args.get('w', 560, type=int)
    h = request.args.get('h', 200, type=int)
    chart_type = request.args.get('type', 'speed')
    prof = g.get('profile')
    ui_settings = profiles_db.get_ui_settings(prof['id'] if prof else 0)
    png_bytes = render_widget_chart_png(summary_tracker.db, ui_settings, hours=hours, width=w, height=h, chart_type=chart_type)
    return Response(png_bytes, mimetype='image/png', headers={'Cache-Control': 'no-store'})