# gui/tray.py
import os
import threading
from utils.helpers import write_error_log

try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_LIBS_AVAILABLE = True
except ImportError:
    TRAY_LIBS_AVAILABLE = False


def has_display():
    if os.name == 'nt':
        return True
    return bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))


def _create_tray_image():
    size = 64
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([2, 2, size - 2, size - 2], radius=14, fill=(26, 26, 32, 255), outline=(46, 204, 113, 255), width=3)
    # Молния в стиле логотипа tbr PRO
    bolt = [(35, 10), (17, 35), (31, 35), (27, 54), (47, 29), (33, 29)]
    draw.polygon(bolt, fill=(46, 204, 113, 255))
    return img


class SystemTrayController:
    def __init__(self, root, on_show_window, on_open_web, on_exit_app):
        self.root = root
        self.on_show_window = on_show_window
        self.on_open_web = on_open_web
        self.on_exit_app = on_exit_app
        self.icon = None
        self.is_active = False

    def start(self):
        if not TRAY_LIBS_AVAILABLE or not has_display():
            return False

        try:
            menu = pystray.Menu(
                pystray.MenuItem("Открыть окно", self._dispatch(self.on_show_window), default=True),
                pystray.MenuItem("Открыть веб-панель", self._dispatch(self.on_open_web)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Выход", self._dispatch(self.on_exit_app))
            )
            self.icon = pystray.Icon("tbr_pro", _create_tray_image(), "tbr PRO", menu)
            threading.Thread(target=self.icon.run, daemon=True).start()
            self.is_active = True
            return True
        except Exception as e:
            write_error_log("Ошибка запуска системного трея", e)
            self.is_active = False
            return False

    def _dispatch(self, callback):
        def handler(icon, item):
            try:
                self.root.after(0, callback)
            except Exception:
                pass
        return handler

    def stop(self):
        self.is_active = False
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None