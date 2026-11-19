#!/usr/bin/env python3
"""
tbr PRO / tbr-widget — Project Context Collector
Скрипт собирает все текстовые файлы проекта с учётом .gitignore в единый файл для промпта.
"""

import os
import subprocess
import sys
from pathlib import Path

# Бинарники и служебный мусор, который точно не надо слать в LLM
BINARY_EXTENSIONS = {
    ".exe", ".apk", ".aab", ".zip", ".tar", ".gz", ".7z",
    ".db", ".sqlite", ".sqlite3", ".wal", ".shm",
    ".png", ".jpg", ".jpeg", ".ico", ".webp", ".gif",
    ".keystore", ".jks", ".pyc", ".pyo", ".pyd",
    ".dll", ".so", ".dylib", ".bin", ".dat"
}

OUTPUT_FILE = "project_dump.txt"


def get_git_files() -> list[str]:
    """Получает список файлов проекта, исключая .gitignore."""
    try:
        cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception as e:
        print(f"[!] Ошибка вызова git: {e}")
        print("[*] Убедись, что Git установлен и ты запускаешь скрипт в корне репозитория.")
        return []


def is_text_file(filepath: Path) -> bool:
    """Проверяет расширение и пытается прочитать первый чанк файла."""
    if filepath.suffix.lower() in BINARY_EXTENSIONS:
        return False
    
    # Игнорируем сам файл дампа и сам этот скрипт
    if filepath.name in (OUTPUT_FILE, "dump_project.py"):
        return False

    try:
        with open(filepath, "tr", encoding="utf-8") as f:
            f.read(1024)
            return True
    except (UnicodeDecodeError, OSError):
        return False


def main():
    root_dir = Path.cwd()
    print(f"[*] Сканирую репозиторий в: {root_dir}")

    files = get_git_files()
    if not files:
        print("[-] Список файлов пуст или проект не инициализирован как git-репо.")
        sys.exit(1)

    collected_count = 0
    skipped_count = 0

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        for rel_path in files:
            full_path = root_dir / rel_path
            
            if not full_path.is_file():
                continue

            if not is_text_file(full_path):
                skipped_count += 1
                continue

            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
                out.write("=" * 80 + "\n")
                out.write(f"FILE: {rel_path.replace(os.sep, '/')}\n")
                out.write("=" * 80 + "\n")
                out.write(content)
                if not content.endswith("\n"):
                    out.write("\n")
                out.write("\n")
                collected_count += 1
            except Exception as ex:
                print(f"[!] Пропущен {rel_path}: {ex}")
                skipped_count += 1

    size_mb = os.path.getsize(OUTPUT_FILE) / (1024 * 1024)
    print("\n" + "=" * 40)
    print(f"[+] Готово! Собрано файлов: {collected_count}")
    print(f"[-] Пропущено (бинарники/кэш): {skipped_count}")
    print(f"[>] Результат сохранён в: {OUTPUT_FILE} ({size_mb:.2f} MB)")
    print("=" * 40)


if __name__ == "__main__":
    main()