@echo off
chcp 65001 >nul
title Сборка tbr PRO (Self-Healing PyInstaller)

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "ENTRY=%ROOT%\main.py"
set "DATA_TPL=%ROOT%\web\templates;web\templates"
set "DATA_STC=%ROOT%\web\static;web\static"

echo ==================================================
echo            СБОРКА tbr PRO (PyInstaller)
echo ==================================================
echo.
echo [1] Только ONEFILE  (-^> dist\onefile\tbr.exe)
echo [2] Только ONEDIR   (-^> dist\onedir\tbr\tbr.exe)
echo [3] ОБА ВАРИАНТА    (-^> разложит по разным папкам)
echo.
set /p mode="Выберите режим [1, 2 или 3]: "

if "%mode%"=="1" goto prep
if "%mode%"=="2" goto prep
if "%mode%"=="3" goto prep

echo.
echo ❌ Неверный выбор! Введите 1, 2 или 3.
pause
exit /b 1

:prep
echo.
echo [🔧] Проверка среды и снятие блокировок...

taskkill /F /IM tbr.exe >nul 2>&1
timeout /t 1 /nobreak >nul

python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python не найден в системе! Установи Python 3.10+ с галочкой Add to PATH.
    pause
    exit /b 1
)

python -c "import PyInstaller, flask, pystray, PIL, waitress" >nul 2>&1
if errorlevel 1 (
    echo [📦] Доустанавливаю библиотеки из requirements.txt и PyInstaller...
    python -m pip install --upgrade pip
    if exist "%ROOT%\requirements.txt" (
        python -m pip install -r "%ROOT%\requirements.txt" pyinstaller
    ) else (
        python -m pip install flask pystray pillow waitress pyinstaller
    )
    if errorlevel 1 (
        echo ❌ Не удалось установить зависимости!
        pause
        exit /b 1
    )
)

if "%mode%"=="2" goto build_onedir
goto build_onefile

:build_onefile
echo.
echo [1/2] Очистка и сборка ONEFILE в dist\onefile\...
if exist "%ROOT%\dist\onefile" rd /s /q "%ROOT%\dist\onefile" >nul 2>&1
if exist "%ROOT%\dist\onefile" (
    echo ❌ Папка dist\onefile заблокирована! Закрой её в Проводнике Windows и повтори.
    pause
    exit /b 1
)
if exist "%ROOT%\build\onefile" rd /s /q "%ROOT%\build\onefile" >nul 2>&1
mkdir "%ROOT%\build\onefile"

python -m PyInstaller --noconfirm --clean --onefile --windowed --name "tbr" ^
    --hidden-import "waitress" ^
    --distpath "%ROOT%\dist\onefile" ^
    --workpath "%ROOT%\build\onefile" ^
    --specpath "%ROOT%\build\onefile" ^
    --add-data "%DATA_TPL%" ^
    --add-data "%DATA_STC%" "%ENTRY%"
if errorlevel 1 goto build_error

if "%mode%"=="3" goto build_onedir
goto done

:build_onedir
echo.
echo [2/2] Очистка и сборка ONEDIR в dist\onedir\...
if exist "%ROOT%\dist\onedir" rd /s /q "%ROOT%\dist\onedir" >nul 2>&1
if exist "%ROOT%\dist\onedir" (
    echo ❌ Папка dist\onedir заблокирована! Закрой её в Проводнике Windows и повтори.
    pause
    exit /b 1
)
if exist "%ROOT%\build\onedir" rd /s /q "%ROOT%\build\onedir" >nul 2>&1
mkdir "%ROOT%\build\onedir"

python -m PyInstaller --noconfirm --clean --onedir --windowed --name "tbr" ^
    --hidden-import "waitress" ^
    --distpath "%ROOT%\dist\onedir" ^
    --workpath "%ROOT%\build\onedir" ^
    --specpath "%ROOT%\build\onedir" ^
    --add-data "%DATA_TPL%" ^
    --add-data "%DATA_STC%" "%ENTRY%"
if errorlevel 1 goto build_error
goto done

:done
echo.
echo ==================================================
echo ✅ Сборка успешно завершена!
if not "%mode%"=="2" echo    OneFile: dist\onefile\tbr.exe
if not "%mode%"=="1" echo    OneDir:  dist\onedir\tbr\tbr.exe
echo ==================================================
pause
exit /b 0

:build_error
echo.
echo ❌ Произошла ошибка при компиляции!
pause
exit /b 1