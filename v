# VREIFY_PROJECT.PY
import os
import sys

REQUIRED_FILES = [
    "core/version.py", "core/ui_defaults.py", "core/app_state_db.py", "core/updater.py",
    "core/keep_awake.py", "core/reliability.py", "core/disaster_recovery.py",
    "core/torrent_diff.py", "core/orphan_scanner.py", "core/private_vault.py",
    "core/smart_timers.py", "core/dnd_digest.py", "core/smart_tagging.py",
    "core/torrent_targets.py", "core/tracker_inspector.py", "core/health_score.py",
    "core/analytics_insights.py", "core/records_service.py", "core/achievements.py",
    "core/disk_monitor.py", "core/sessions.py", "core/soft_trash.py",
    "core/config_vault.py", "core/env_doctor.py", "core/profiles_auth.py",
    "core/qb_actions.py", "core/automation_eval.py", "core/history_queries.py",
    "core/hygiene_trackers.py", "core/hygiene_disk.py", "core/torrent_archiver.py",
    "core/tracker_replacer.py", "core/batch_relocate.py", "core/path_remapper.py",
    "core/network_tools.py", "core/webhooks_bundler.py", "core/undo_presets.py",
    "core/preflight_inbox.py", "core/autopilot_extras.py", "core/saved_views.py",
    "core/deep_analytics.py", "core/swarm_analytics.py", "core/wrapped_service.py",
    "core/lineage_notes_events.py", "core/file_fts_index.py",
    "core/hdd_smart_queue.py", "core/rss_dedup.py", "core/mediainfo_lite.py",
    "web/errors.py",
    "web/routes/system_bp.py", "web/routes/tools_bp.py", "web/routes/timers_bp.py",
    "web/routes/insights_bp.py", "web/routes/social_bp.py", "web/routes/safety_bp.py",
    "web/routes/hygiene_bp.py", "web/routes/batch_bp.py", "web/routes/net_ops_bp.py",
    "web/routes/inbox_ops_bp.py", "web/routes/deep_analytics_bp.py",
    "web/routes/ux_bp.py", "web/routes/hardcore_bp.py", "web/routes/merger_bp.py",
    "web/templates/error.html", "web/templates/kiosk.html",
    "web/templates/partials/tab_tools.html", "web/templates/partials/tab_hygiene_cards.html",
    "web/templates/partials/tab_net_ops.html", "web/templates/partials/tab_auto_extras.html",
    "web/templates/partials/tab_analytics_deep.html", "web/templates/partials/modal_system.html",
    "web/static/system_tools.js", "web/static/merger_tools.js", "web/static/timers_ui.js",
    "web/static/palette_targets.js", "web/static/analytics_insights.js", "web/static/social_ui.js",
    "web/static/smart_calc.js", "web/static/safety_ui.js", "web/static/hygiene_ui.js",
    "web/static/phase3_ui.js", "web/static/phase4_ui.js", "web/static/hardcore_ui.js",
    "web/static/torrents_merger.js", "web/static/analytics_charts_render.js",
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
    print("✅ Тестовый импорт web.app и main прошёл успешно! Можно собирать .exe через build.bat.")
except Exception as e:
    print(f"❌ Ошибка импорта: {e}")
    sys.exit(1)