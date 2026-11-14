pyinstaller --noconfirm --onedir --windowed ^
    --name "tbr_v2" ^
    --add-data "web/templates/index.html;web/templates" ^
    --hidden-import "plyer.platforms.win.notification" ^
    --hidden-import "werkzeug.serving" ^
    main.py