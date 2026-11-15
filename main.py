# main.py
import sys
import os
import argparse
import webbrowser
import threading

from utils.config import cfg
from web.app import web_server


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

    # 1. Запуск встроенного веб-сервера в фоне
    if not args.no_web:
        web_server.start(host=web_host, port=web_port)

    # 2. Headless-режим (без Tkinter)
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
            sys.exit(0)

    # 3. Ленивый импорт GUI только когда реально нужно окно (чтобы Linux/Docker не падал без tkinter)
    import tkinter as tk
    from tkinter import messagebox

    try:
        from gui.main_window import TorrentApp
    except ImportError:
        try:
            from main_window import TorrentApp
        except ImportError as e:
            print(f"❌ Ошибка: не найден файл main_window.py с классом TorrentApp! {e}")
            TorrentApp = None

    if TorrentApp is None:
        messagebox.showerror(
            "Ошибка запуска",
            "Файл интерфейса main_window.py не найден!\nПоложите его в папку gui/main_window.py."
        )
        return

    if os.name == 'nt':
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    root = tk.Tk()
    TorrentApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()