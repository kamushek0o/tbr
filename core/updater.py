# core/updater.py
import os
import sys
import hmac
import json
import time
import hashlib
import tempfile
import threading
import subprocess
import urllib.request
from core.version import APP_VERSION, GITHUB_API_LATEST, GITHUB_RELEASES_URL, is_newer_version
from core.app_state_db import app_state_db
from utils.helpers import write_log, write_error_log

CACHE_TTL_SEC = 6 * 3600
_LOCK = threading.Lock()
_CACHE = {"ts": 0.0, "data": None}
_SHUTDOWN_HOOK = None


def register_shutdown_hook(fn):
    global _SHUTDOWN_HOOK
    _SHUTDOWN_HOOK = fn


def is_frozen_windows():
    return bool(getattr(sys, "frozen", False) and os.name == "nt")


def _http_get_bytes(url, timeout=15):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"tbr-pro/{APP_VERSION}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def check_for_updates(force=False):
    now = time.time()
    with _LOCK:
        if not force and _CACHE["data"] and (now - _CACHE["ts"]) < CACHE_TTL_SEC:
            return dict(_CACHE["data"])

    result = {
        "success": True,
        "current_version": APP_VERSION,
        "latest_version": APP_VERSION,
        "update_available": False,
        "can_auto_update": is_frozen_windows(),
        "release_name": "",
        "changelog": "",
        "html_url": GITHUB_RELEASES_URL,
        "exe_url": "",
        "sha256": "",
        "checked_at": int(now),
        "error": None,
    }

    try:
        raw = _http_get_bytes(GITHUB_API_LATEST, timeout=10)
        rel = json.loads(raw.decode("utf-8"))
        tag = str(rel.get("tag_name") or "").strip()
        latest_ver = tag.lstrip("vV") or APP_VERSION
        assets = rel.get("assets") or []

        exe_asset = None
        sha_asset = None
        for a in assets:
            nm = str(a.get("name") or "").lower()
            if nm.endswith(".exe") and not exe_asset:
                exe_asset = a
            elif nm.endswith(".sha256") and not sha_asset:
                sha_asset = a

        sha_val = ""
        if exe_asset:
            digest = str(exe_asset.get("digest") or "")
            if digest.lower().startswith("sha256:"):
                sha_val = digest.split(":", 1)[1].strip().lower()
        if not sha_val and sha_asset and sha_asset.get("browser_download_url"):
            try:
                sha_txt = _http_get_bytes(sha_asset["browser_download_url"], timeout=8).decode("utf-8", errors="ignore")
                token = sha_txt.strip().split()[0].lower()
                if len(token) == 64 and all(c in "0123456789abcdef" for c in token):
                    sha_val = token
            except Exception:
                pass

        result.update({
            "latest_version": latest_ver,
            "update_available": is_newer_version(latest_ver, APP_VERSION),
            "release_name": str(rel.get("name") or tag or latest_ver),
            "changelog": str(rel.get("body") or ""),
            "html_url": str(rel.get("html_url") or GITHUB_RELEASES_URL),
            "exe_url": str(exe_asset.get("browser_download_url") or "") if exe_asset else "",
            "sha256": sha_val,
        })
        with _LOCK:
            _CACHE["ts"] = now
            _CACHE["data"] = dict(result)
    except Exception as e:
        write_error_log("Проверка обновлений GitHub", e)
        result["success"] = False
        result["error"] = str(e)

    return result


def _spawn_updater_bat(pid, current_exe, new_exe):
    bat_path = os.path.join(tempfile.gettempdir(), "tbr_updater.bat")
    bak_exe = current_exe + ".bak"
    script = (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        f"set \"PID={int(pid)}\"\r\n"
        f"set \"CUR={current_exe}\"\r\n"
        f"set \"NEW={new_exe}\"\r\n"
        f"set \"BAK={bak_exe}\"\r\n"
        ":waitloop\r\n"
        "tasklist /FI \"PID eq %PID%\" 2>NUL | find /I \"%PID%\" >NUL\r\n"
        "if \"%ERRORLEVEL%\"==\"0\" (\r\n"
        "    timeout /t 1 /nobreak >NUL\r\n"
        "    goto waitloop\r\n"
        ")\r\n"
        "if exist \"%BAK%\" del /F /Q \"%BAK%\" >NUL 2>&1\r\n"
        "if exist \"%CUR%\" move /Y \"%CUR%\" \"%BAK%\" >NUL 2>&1\r\n"
        "move /Y \"%NEW%\" \"%CUR%\" >NUL 2>&1\r\n"
        "start \"\" \"%CUR%\"\r\n"
        "del /F /Q \"%~f0\" >NUL 2>&1\r\n"
    )
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(script)

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(["cmd.exe", "/c", bat_path], creationflags=flags, close_fds=True)


def download_and_apply_update(actor="admin"):
    if not is_frozen_windows():
        return False, "Автообновление доступно только в собранном tbr.exe под Windows."

    info = check_for_updates(force=True)
    if not info.get("success"):
        return False, f"Ошибка проверки релиза: {info.get('error')}"
    if not info.get("update_available"):
        return False, "Установлена актуальная версия."
    if not info.get("exe_url"):
        return False, "В релизе не найден бинарный файл .exe."
    if not info.get("sha256"):
        return False, "В релизе отсутствует SHA-256 контрольная сумма — обновление отменено."

    current_exe = os.path.abspath(sys.executable)
    exe_dir = os.path.dirname(current_exe)
    new_exe = os.path.join(exe_dir, "tbr_new.exe")

    try:
        req = urllib.request.Request(info["exe_url"], headers={"User-Agent": f"tbr-pro/{APP_VERSION}"})
        hasher = hashlib.sha256()
        with urllib.request.urlopen(req, timeout=60) as resp, open(new_exe, "wb") as out:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                out.write(chunk)
                hasher.update(chunk)

        actual_sha = hasher.hexdigest().lower()
        if not hmac.compare_digest(actual_sha, info["sha256"].lower()):
            try:
                os.remove(new_exe)
            except OSError:
                pass
            app_state_db.add_audit_event("system", "Ошибка обновления", f"SHA-256 mismatch for v{info['latest_version']}", actor=actor)
            return False, "Контрольная сумма SHA-256 не совпала! Файл удалён."

        _spawn_updater_bat(os.getpid(), current_exe, new_exe)
        write_log("app", f"Запущено автообновление до v{info['latest_version']}")
        app_state_db.add_audit_event("system", "Автообновление", f"Переход на v{info['latest_version']}", actor=actor)

        def delayed_exit():
            time.sleep(0.6)
            if _SHUTDOWN_HOOK:
                try:
                    _SHUTDOWN_HOOK()
                except Exception:
                    pass
            os._exit(0)

        threading.Thread(target=delayed_exit, daemon=True).start()
        return True, f"Обновление v{info['latest_version']} проверено и скачано. Перезапуск tbr PRO..."
    except Exception as e:
        if os.path.exists(new_exe):
            try:
                os.remove(new_exe)
            except OSError:
                pass
        write_error_log("Ошибка применения обновления", e)
        return False, f"Ошибка скачивания: {e}"