# web/routes/hygiene_bp.py
import urllib.parse
from flask import Blueprint, request, jsonify, Response, g
from utils.config import cfg
from core.qb_api import detect_qbittorrent_port, delete_torrents
from core.hygiene_trackers import scan_quarantine, scan_stalled_incompletes, scan_dead_weight
from core.hygiene_disk import scan_bt_backup_garbage, scan_inner_content_junk, trash_paths_list
from core.torrent_archiver import sync_torrent_archive, list_archived_torrents, get_archived_torrent_bytes, export_archive_zip_by_tag
from core.soft_trash import move_to_trash
from core.app_state_db import app_state_db
from web.security import HASH_RE

hygiene_bp = Blueprint('hygiene_bp', __name__)


def _not_admin():
    return g.get('role') != 'admin'


@hygiene_bp.route('/api/hygiene/quarantine')
def api_hygiene_quarantine():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    hrs = request.args.get('hours', 72, type=int)
    apply_tags = request.args.get('tag', '0') == '1'
    return jsonify(scan_quarantine(hours_threshold=hrs, apply_tags=apply_tags))


@hygiene_bp.route('/api/hygiene/incompletes')
def api_hygiene_incompletes():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    days = request.args.get('days', 14, type=int)
    return jsonify(scan_stalled_incompletes(stalled_days=days))


@hygiene_bp.route('/api/hygiene/dead_weight')
def api_hygiene_dead_weight():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    days = request.args.get('days', 30, type=int)
    seeds = request.args.get('min_seeds', 10, type=int)
    return jsonify(scan_dead_weight(idle_days=days, min_seeds=seeds))


@hygiene_bp.route('/api/hygiene/delete_torrents_soft', methods=['POST'])
def api_hygiene_delete_torrents_soft():
    """Удаляет торренты из qB и переносит их файлы в _tbr_trash (#8)."""
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    data = request.get_json(silent=True) or {}
    items = data.get('items') or []
    if not isinstance(items, list) or not items:
        return jsonify({'success': False, 'error': 'Пустой список'}), 400

    ip, port = detect_qbittorrent_port(cfg.config)
    if not port:
        return jsonify({'success': False, 'error': 'qBittorrent недоступен'}), 400

    removed = 0
    for it in items:
        h = str(it.get('hash', '')).strip()
        cp = str(it.get('content_path', '')).strip()
        nm = str(it.get('name', h))
        if not HASH_RE.fullmatch(h):
            continue
        if delete_torrents(ip, port, h, delete_files=False):
            if cp:
                move_to_trash(cp, name=nm, t_hash=h, actor='admin')
            removed += 1

    if removed:
        app_state_db.add_audit_event('system', 'Гигиена: перенос в _tbr_trash', f'Удалено раздач: {removed}', actor='admin')
    return jsonify({'success': True, 'removed': removed})


@hygiene_bp.route('/api/hygiene/bt_backup')
def api_hygiene_bt_backup():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    return jsonify(scan_bt_backup_garbage())


@hygiene_bp.route('/api/hygiene/inner_junk')
def api_hygiene_inner_junk():
    if _not_admin():
        return jsonify({'error': 'Только для Admin'}), 403
    return jsonify(scan_inner_content_junk())


@hygiene_bp.route('/api/hygiene/trash_paths', methods=['POST'])
def api_hygiene_trash_paths():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    data = request.get_json(silent=True) or {}
    paths = data.get('paths') or []
    reason = str(data.get('reason', 'hygiene'))[:32]
    if not isinstance(paths, list) or not paths:
        return jsonify({'success': False, 'error': 'Пустой список'}), 400
    ok, moved, errors = trash_paths_list(paths, actor='admin', reason=reason)
    return jsonify({'success': ok, 'moved': len(moved), 'errors': errors})


@hygiene_bp.route('/api/archive/sync', methods=['POST'])
def api_archive_sync():
    if _not_admin():
        return jsonify({'success': False, 'error': 'Только для Admin'}), 403
    return jsonify(sync_torrent_archive())


@hygiene_bp.route('/api/archive/list')
def api_archive_list():
    q = request.args.get('q', '')
    tag = request.args.get('tag', '')
    return jsonify({'items': list_archived_torrents(query=q, tag=tag, role=g.get('role') or 'viewer')})


@hygiene_bp.route('/api/archive/download')
def api_archive_download():
    h = request.args.get('hash', '')
    if not HASH_RE.fullmatch(h):
        return "Некорректный хэш", 400
    raw, fname = get_archived_torrent_bytes(h, role=g.get('role') or 'viewer')
    if not raw:
        return "Файл не найден или скрыт", 404
    return Response(raw, mimetype='application/x-bittorrent', headers={'Content-Disposition': f"attachment; filename*=UTF-8''{urllib.parse.quote(fname)}"})


@hygiene_bp.route('/api/archive/export_zip')
def api_archive_export_zip():
    tag = request.args.get('tag', '')
    zbytes, cnt = export_archive_zip_by_tag(tag=tag, role=g.get('role') or 'viewer')
    if cnt == 0:
        return "Нет файлов для выгрузки", 404
    return Response(zbytes, mimetype='application/zip', headers={'Content-Disposition': f"attachment; filename=torrents_archive_{tag or 'all'}.zip"})