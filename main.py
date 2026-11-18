# main.py
import sys
import os
import atexit
import signal
import argparse
import webbrowser
import threading

from core.backup_manager import apply_pending_restore_if_any
apply_pending_restore_if_any()

from utils.config import cfg
from utils.helpers import write_log
from core.single_instance import SingleInstanceLock
from web.app import web_server
from core.summary_tracker import summary_tracker


def parse_arguments():
    parser = argparse.ArgumentParser(description="tbr v2.0 (Швейцарский нож qBittorrent)")
    parser.add_argument("--port", type=int, default=None, help="Порт веб-сервера")
    parser.add_argument("--host", type=str, default=None, help="Хост веб-сервера")
    parser.add_argument("--web-only", "--headless", dest="web_only", action="store_true",
                        help="Запустить только веб без окна (для серверов и Docker)")
    parser.add_argument("--no-web", action="store_true", help="Запустить только окно без веб-сервера")
    return parser.parse_args()


def get_browser_url(host, port):
    b_host = '127.0.0.1' if host in ('0.0.0.0', '*') else host
    return f"http://{b_host}:{port}"


def main():
    args = parse_arguments()

    instance_lock = SingleInstanceLock()
    if not instance_lock.acquire(wait_sec=1.5):
        msg = "tbr уже запущен (проверь системный трей)"
        if args.web_only:
            write_log("app", msg)
            print(f"⚠️ {msg}")
            sys.exit(0)
        try:
            import tkinter as tk
            from tkinter import messagebox
            tmp_root = tk.Tk()
            tmp_root.withdraw()
            messagebox.showinfo("tbr PRO", msg)
            tmp_root.destroy()
        except Exception:
            print(f"⚠️ {msg}")
        sys.exit(0)

    env_pwd = os.environ.get('TBR_WEB_PASSWORD', '').strip()
    if env_pwd:
        cfg.set('Web_Password', env_pwd)
    if args.port:
        cfg.set('Web_Port', args.port)
    if args.host:
        cfg.set('Web_Host', args.host)
    if args.port or args.host or env_pwd:
        cfg.save()

    web_port = cfg.getint('Web_Port', 5000)
    web_host = cfg.get('Web_Host', '127.0.0.1')

    def on_shutdown():
        summary_tracker.flush_on_exit()
        web_server.stop()
        instance_lock.release()

    atexit.register(on_shutdown)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda s, f: (on_shutdown(), sys.exit(0)))
        except Exception:
            pass

    if not args.no_web:
        web_server.start(host=web_host, port=web_port)

    if args.web_only:
        url = get_browser_url(web_host, web_port)
        if os.name == 'nt':
            try:
                webbrowser.open(url)
            except Exception:
                pass
        print(f"✅ Сервер запущен на {url}. Нажмите Ctrl+C для выхода.")
        try:
            while True:
                threading.Event().wait(1)
        except KeyboardInterrupt:
            on_shutdown()
            sys.exit(0)

    import tkinter as tk
    from tkinter import messagebox
    try:
        from gui.main_window import TorrentApp
    except ImportError:
        TorrentApp = None

    if TorrentApp is None:
        messagebox.showerror("Ошибка запуска", "Файл интерфейса gui/main_window.py не найден!")
        on_shutdown()
        return

    if os.name == 'nt':
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    root = tk.Tk()
    TorrentApp(root, on_quit_callback=on_shutdown)
    root.mainloop()
    on_shutdown()


if __name__ == "__main__":
    main()