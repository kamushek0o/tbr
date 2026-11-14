# Компилятор.py
import os
import sys
import subprocess
import shutil

def build_exe():
    print("🚀 Начинается сборка проекта в исполняемый .exe файл...")

    try:
        import PyInstaller
    except ImportError:
        print("❌ PyInstaller не установлен. Выполните: pip install pyinstaller")
        return

    base_dir = os.path.dirname(os.path.abspath(__file__))
    main_script = os.path.join(base_dir, "main.py")
    output_name = "TorrentSwissKnife"

    # Параметры сборки
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",             # Для стабильности и быстрой загрузки
        "--windowed",           # Без чёрного окна консоли
        "--name", output_name,
        "--clean",
        # Добавляем скрытые импорты
        "--hidden-import", "plyer.platforms.win.notification",
        "--hidden-import", "netifaces",
        # Точка входа
        main_script
    ]

    print(f"Выполняется команда:\n{' '.join(cmd)}\n")
    result = subprocess.run(cmd)

    if result.returncode == 0:
        print(f"\n🎉 Сборка завершена успешно! Папка с программой: dist/{output_name}")
    else:
        print("\n❌ Во время сборки произошла ошибка.")

if __name__ == "__main__":
    build_exe()