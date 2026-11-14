# main.py
import sys
import os
import argparse
import webbrowser
import threading
import tkinter as tk
from tkinter import messagebox

from utils.config import cfg
from web.app import web_server

try:
    from gui.main_window import TorrentApp
except ImportError:
    try:
        from main_window import TorrentApp
    except ImportError as e:
        print(f"❌ Ошибка: не найден файл main_window.py с классом TorrentApp! {e}")
        TorrentApp = None


def parse_arguments():
    parser = argparse.ArgumentParser(description="tbr v2.0 (Швейцарский нож qBittorrent)")
    parser.add_argument("--port", type=int, default=None, help="Порт веб-сервера")
    parser.add_argument("--host", type=str, default=None, help="Хост веб-сервера")
    parser.add_argument("--web-only", action="store_true", help="Запустить только веб без окна")
    parser.add_argument("--no-web", action="store_true", help="Запустить только окно без веб-сервера")
    return parser.parse_args()


def get_browser_url(host, port):
    # Windows не может перейти на 0.0.0.0 напрямую в браузере
    b_host = '127.0.0.1' if host in ('0.0.0.0', '*') else host
    return f"http://{b_host}:{port}"


def main():
    args = parse_arguments()

    if args.port:
        cfg.set('Web_Port', args.port)
    if args.host:
        cfg.set('Web_Host', args.host)
    if args.port or args.host:
        cfg.save()

    web_port = cfg.getint('Web_Port', 5000)
    web_host = cfg.get('Web_Host', '127.0.0.1')

    # 1. Запуск встроенного веб-сервера в фоне
    if not args.no_web:
        web_server.start(host=web_host, port=web_port)

    # 2. Если передан флаг --web-only, работаем как headless веб-сервер
    if args.web_only:
        url = get_browser_url(web_host, web_port)
        webbrowser.open(url)
        print(f"✅ Сервер запущен на {url}. Нажмите Ctrl+C для выхода.")
        try:
            while True:
                threading.Event().wait(1)
        except KeyboardInterrupt:
            sys.exit(0)

    # 3. Запуск классического окна Windows (Tkinter)
    if TorrentApp is None:
        messagebox.showerror(
            "Ошибка запуска",
            "Файл интерфейса main_window.py не найден!\nПоложите его в папку gui/main_window.py."
        )
        return

    # Четкие шрифты на мониторах высокой четкости (HiDPI)
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