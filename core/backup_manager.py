# core/backup_manager.py
import os
import io
import shutil
import sqlite3
import zipfile
import tempfile
import configparser
from utils.helpers import APP_DATA_DIR, LOG_FOLDER
from utils.config import CONFIG_FILE

DB_TARGETS = [
    ('profiles.db', os.path.join(APP_DATA_DIR, 'profiles.db')),
    ('automation.db', os.path.join(APP_DATA_DIR, 'automation.db')),
    ('app_state.db', os.path.join(APP_DATA_DIR, 'app_state.db')),
    ('summary_history.db', os.path.join(LOG_FOLDER, 'auto_hourly', 'summary_history.db')),
]
PENDING_DIR = os.path.join(APP_DATA_DIR, '_restore_pending')
SECRET_KEYS = ('Web_Password', 'WebUI_Password', 'TG_Bot_Token', 'Discord_Webhook')


def apply_pending_restore_if_any():
    """Вызывается при старте main.py ДО открытия любых БД."""
    if not os.path.isdir(PENDING_DIR):
        return
    try:
        for arc_name, dest_path in DB_TARGETS:
            src = os.path.join(PENDING_DIR, arc_name)
            if os.path.isfile(src):
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                for ext in ('-wal', '-shm'):
                    if os.path.exists(dest_path + ext):
                        try:
                            os.remove(dest_path + ext)
                        except OSError:
                            pass
                shutil.move(src, dest_path)
        cfg_src = os.path.join(PENDING_DIR, 'config.ini')
        if os.path.isfile(cfg_src):
            shutil.move(cfg_src, CONFIG_FILE)
    finally:
        shutil.rmtree(PENDING_DIR, ignore_errors=True)


def create_backup_zip(exclude_history=False, strip_secrets=False):
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for arc_name, src_path in DB_TARGETS:
                if exclude_history and arc_name == 'summary_history.db':
                    continue
                if not os.path.isfile(src_path):
                    continue
                dst_tmp = os.path.join(tmpdir, arc_name)
                src_conn = sqlite3.connect(src_path, timeout=30.0)
                dst_conn = sqlite3.connect(dst_tmp)
                try:
                    src_conn.backup(dst_conn)
                finally:
                    dst_conn.close()
                    src_conn.close()
                zf.write(dst_tmp, arcname=arc_name)

            if os.path.isfile(CONFIG_FILE):
                if strip_secrets:
                    cp = configparser.ConfigParser()
                    cp.read(CONFIG_FILE, encoding='utf-8')
                    if 'Settings' in cp:
                        for k in SECRET_KEYS:
                            if k in cp['Settings']:
                                cp['Settings'][k] = ''
                    s_buf = io.StringIO()
                    cp.write(s_buf)
                    zf.writestr('config.ini', s_buf.getvalue().encode('utf-8'))
                else:
                    zf.write(CONFIG_FILE, arcname='config.ini')

    return buf.getvalue()


def stage_restore_zip(file_bytes):
    allowed = {name for name, _ in DB_TARGETS} | {'config.ini'}
    os.makedirs(PENDING_DIR, exist_ok=True)
    extracted = []
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes), 'r') as zf:
            for info in zf.infolist():
                base = os.path.basename(info.filename)
                if not base or base not in allowed or info.file_size > 512 * 1024 * 1024:
                    continue
                data = zf.read(info.filename)
                with open(os.path.join(PENDING_DIR, base), 'wb') as out:
                    out.write(data)
                extracted.append(base)
        if not extracted:
            shutil.rmtree(PENDING_DIR, ignore_errors=True)
            return False, "В архиве не найдено ни одного файла tbr PRO (.db / config.ini)"
        return True, f"Подготовлено к восстановлению ({', '.join(extracted)}). Перезапустите tbr PRO для применения."
    except zipfile.BadZipFile:
        return False, "Некорректный ZIP-архив"
    except Exception as e:
        return False, str(e)