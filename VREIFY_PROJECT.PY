# verify_project.py
import os
import sys

REQUIRED_FILES = [
    "core/version.py", "core/ui_defaults.py", "core/app_state_db.py", "core/updater.py",
    "core/keep_awake.py", "core/reliability.py", "core/disaster_recovery.py",
    "core/torrent_diff.py", "core/orphan_scanner.py", "core/private_vault.py",
    "core/smart_timers.py", "core/dnd_digest.py", "core/smart_tagging.py",
    "core/torrent_targets.py", "core/tracker_inspector.py", "core/health_score.py",
    "core/analytics_insights.py", "core/achievements.py",
    "web/errors.py",
    "web/routes/system_bp.py", "web/routes/tools_bp.py",
    "web/routes/timers_bp.py", "web/routes/insights_bp.py", "web/routes/social_bp.py",
    "web/templates/error.html", "web/templates/partials/tab_tools.html",
    "web/templates/partials/modal_system.html",
    "web/static/system_tools.js", "web/static/merger_tools.js",
    "web/static/timers_ui.js", "web/static/palette_targets.js",
    "web/static/analytics_insights.js", "web/static/social_ui.js",
]

missing = [f for f in REQUIRED_FILES if not os.path.isfile(f)]
if missing:
    print("❌ НЕ ХВАТАЕТ ФАЙЛОВ:")
    for f in missing:
        print("  -", f)
    sys.exit(1)

print(f"✅ Все {len(REQUIRED_FILES)} файлов на месте!")
try:
    import web.app  # noqa: F401
    import main     # noqa: F401
    print("✅ Тестовый импорт web.app и main прошёл успешно! Можно собирать v3.0.1.")
except Exception as e:
    print(f"❌ Ошибка импорта: {e}")
    sys.exit(1)