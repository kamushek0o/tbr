# core/mediainfo_lite.py
import os
import json
import struct
import shutil
import subprocess
from utils.helpers import format_file_size

_WIN_FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
_VIDEO_EXTS = {'.mkv', '.mp4', '.avi', '.mov', '.m4v', '.ts', '.wmv', '.webm'}


def _find_video_files(content_path, limit=10):
    if not content_path or not os.path.exists(content_path):
        return []
    if os.path.isfile(content_path):
        return [content_path] if os.path.splitext(content_path)[1].lower() in _VIDEO_EXTS else []
    found = []
    for root, _, files in os.walk(content_path):
        for fn in files:
            if os.path.splitext(fn)[1].lower() in _VIDEO_EXTS:
                fp = os.path.join(root, fn)
                try:
                    found.append((os.path.getsize(fp), fp))
                except OSError:
                    pass
    found.sort(reverse=True)
    return [p for _, p in found[:limit]]


def _probe_with_ffprobe(ffprobe_exe, fpath):
    try:
        cmd = [ffprobe_exe, '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', fpath]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=4.0, creationflags=_WIN_FLAGS)
        data = json.loads(r.stdout or '{}')
        fmt = data.get('format') or {}
        streams = data.get('streams') or []
        v_streams = [s for s in streams if s.get('codec_type') == 'video']
        a_streams = [s for s in streams if s.get('codec_type') == 'audio']
        s_streams = [s for s in streams if s.get('codec_type') == 'subtitle']

        v_str = '—'
        if v_streams:
            vs = v_streams[0]
            v_str = f"{str(vs.get('codec_name', '')).upper()} {vs.get('width', '?')}x{vs.get('height', '?')}"
        a_list = [f"{str(a.get('codec_name', '')).upper()} ({(a.get('tags') or {}).get('language', 'und')})" for a in a_streams[:4]]
        sub_list = [(s.get('tags') or {}).get('language', 'und') for s in s_streams[:6]]

        dur = float(fmt.get('duration') or 0)
        br = int(fmt.get('bit_rate') or 0)
        return {
            'engine': 'ffprobe',
            'file': os.path.basename(fpath),
            'size_fmt': format_file_size(os.path.getsize(fpath)),
            'duration_fmt': f"{int(dur // 60)}м {int(dur % 60)}с" if dur > 0 else '—',
            'bitrate_fmt': f"{round(br / 1_000_000, 1)} Mbps" if br > 0 else '—',
            'video': v_str,
            'audio': ", ".join(a_list) or '—',
            'subtitles': ", ".join(sub_list) or 'нет'
        }
    except Exception:
        return None


def _probe_fallback_headers(fpath):
    """Базовый pure-Python парсер заголовков MKV/MP4 без внешних зависимостей."""
    ext = os.path.splitext(fpath)[1].lower()
    container = ext.lstrip('.').upper()
    dur_fmt = '—'
    try:
        with open(fpath, 'rb') as f:
            head = f.read(65536)
        if ext == '.mkv' and head.startswith(b'\x1a\x45\xdf\xa3'):
            container = 'Matroska (EBML)'
        elif ext in ('.mp4', '.m4v', '.mov') and b'ftyp' in head[:32]:
            container = 'ISO Base Media (MP4)'
            idx = head.find(b'mvhd')
            if idx != -1 and idx + 24 < len(head):
                ver = head[idx + 4]
                if ver == 0:
                    timescale, duration = struct.unpack('>II', head[idx + 16:idx + 24])
                    if timescale > 0:
                        sec = duration / timescale
                        dur_fmt = f"{int(sec // 60)}м {int(sec % 60)}с"
    except Exception:
        pass

    return {
        'engine': 'header-fallback',
        'file': os.path.basename(fpath),
        'size_fmt': format_file_size(os.path.getsize(fpath)),
        'duration_fmt': dur_fmt,
        'bitrate_fmt': 'нужен ffprobe',
        'video': f'{container}',
        'audio': 'нужен ffprobe',
        'subtitles': '—'
    }


def inspect_torrent_media(content_path):
    videos = _find_video_files(content_path, limit=8)
    if not videos:
        return {'success': False, 'error': 'Видеофайлы на диске не найдены', 'items': []}

    ffprobe = shutil.which('ffprobe')
    items = []
    for vp in videos:
        res = _probe_with_ffprobe(ffprobe, vp) if ffprobe else None
        if not res:
            res = _probe_fallback_headers(vp)
        items.append(res)
    return {'success': True, 'has_ffprobe': bool(ffprobe), 'items': items}