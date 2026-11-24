# web/app.py
import os
import sys
import time
import threading
from flask import Flask

try:
    import waitress
    from waitress import create_server
    HAS_WAITRESS = True
except ImportError:
    waitress = None
    create_server = None
    HAS_WAITRESS = False

from utils.config import cfg
from utils.helpers import APP_DATA_DIR, write_error_log
from core.torrent_parser import get_live_merged_summaries
from core.summary_tracker import summary_tracker
from core.automation import automation_engine
from core.batch_relocate import resume_pending_relocate_if_any
from web.security import register_security
from web.errors import register_error_handlers
from web.routes.torrents_bp import torrents_bp
from web.routes.merger_bp import merger_bp
from web.routes.analytics_bp import analytics_bp
from web.routes.automation_bp import automation_bp
from web.routes.settings_bp import settings_bp
from web.routes.profiles_bp import profiles_bp
from web.routes.widget_bp import widget_bp
from web.routes.system_bp import system_bp
from web.routes.tools_bp import tools_bp
from web.routes.timers_bp import timers_bp
from web.routes.insights_bp import insights_bp
from web.routes.social_bp import social_bp
from web.routes.safety_bp import safety_bp
from web.routes.hygiene_bp import hygiene_bp
from web.routes.batch_bp import batch_bp
from web.routes.net_ops_bp import net_ops_bp
from web.routes.inbox_ops_bp import inbox_ops_bp
from web.routes.deep_analytics_bp import deep_analytics_bp
from web.routes.ux_bp import ux_bp
from web.routes.hardcore_bp import hardcore_bp


def get_resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_path, relative_path)


def _get_or_create_secret_key():
    key_file = os.path.join(APP_DATA_DIR, '.flask_secret')
    try:
        if os.path.isfile(key_file):
            with open(key_file, 'rb') as f:
                data = f.read()
            if len(data) >= 24:
                return data
        new_key = os.urandom(32)
        with open(key_file, 'wb') as f:
            f.write(new_key)
        return new_key
    except Exception:
        return os.urandom(24)


app = Flask(
    __name__,
    template_folder=get_resource_path(os.path.join('web', 'templates')),
    static_folder=get_resource_path(os.path.join('web', 'static'))
)
app.secret_key = _get_or_create_secret_key()
app.config['BUILD_VER'] = str(int(time.time()))
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

register_error_handlers(app)
register_security(app)
for bp in (
    torrents_bp, merger_bp, analytics_bp, automation_bp, settings_bp,
    profiles_bp, widget_bp, system_bp, tools_bp, timers_bp, insights_bp,
    social_bp, safety_bp, hygiene_bp, batch_bp, net_ops_bp, inbox_ops_bp,
    deep_analytics_bp, ux_bp, hardcore_bp
):
    app.register_blueprint(bp)


class WebServerController:
    def __init__(self):
        self.server_instance = None
        self._lock = threading.Lock()
        self.current_host = '127.0.0.1'
        self.current_port = 5000

    def start(self, host=None, port=None):
        with self._lock:
            self._start_locked(host, port)

    def _start_locked(self, host=None, port=None):
        h = (host or cfg.get('Web_Host', '127.0.0.1')).strip() or '127.0.0.1'
        p = port or cfg.getint('Web_Port', 5000)

        is_exposed = h not in ('127.0.0.1', 'localhost')
        if is_exposed and not cfg.get('Web_Password', '').strip():
            print("⚠️ Внимание: выбран внешний хост, но пароль не задан! Безопасный откат на 127.0.0.1.")
            h = '127.0.0.1'
            is_exposed = False

        app.config['IS_EXPOSED'] = is_exposed
        self.current_host = h
        self.current_port = p

        summary_tracker.start_auto_export(get_live_merged_summaries)
        automation_engine.start()
        resume_pending_relocate_if_any()

        try:
            if HAS_WAITRESS and create_server:
                self.server_instance = create_server(app, host=h, port=p, threads=8)
                engine_name = "Waitress"
            else:
                from werkzeug.serving import make_server
                self.server_instance = make_server(h, p, app, threaded=True)
                engine_name = "Werkzeug (fallback)"

            print(f"🚀 Сервер {engine_name} запущен на http://{h}:{p} (Авторизация: {'ВКЛ' if is_exposed else 'ВЫКЛ'})")

            def serve():
                try:
                    if self.server_instance:
                        if hasattr(self.server_instance, 'run'):
                            self.server_instance.run()
                        else:
                            self.server_instance.serve_forever()
                except Exception as e:
                    write_error_log("WebServer serve error", e)

            threading.Thread(target=serve, daemon=True).start()
        except Exception as e:
            write_error_log("WebServerController Start Error", e)
            print(f"❌ Ошибка запуска веб-сервера на {h}:{p}: {e}")

    def stop(self):
        with self._lock:
            if self.server_instance:
                try:
                    if hasattr(self.server_instance, 'close'):
                        self.server_instance.close()
                    elif hasattr(self.server_instance, 'shutdown'):
                        self.server_instance.shutdown()
                except Exception:
                    pass
                self.server_instance = None

    def restart(self, new_host, new_port):
        def do_restart():
            time.sleep(0.5)
            self.stop()
            with self._lock:
                self._start_locked(new_host, new_port)

        threading.Thread(target=do_restart, daemon=True).start()


web_server = WebServerController()
app.config['WEB_SERVER'] = web_server