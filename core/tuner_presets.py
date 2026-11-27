# core/tuner_presets.py
from copy import deepcopy

BASE_PROFILE_TEMPLATE = {
    'max_uploads_min': 10, 'max_uploads_max': 60, 'max_uploads_start': 25,
    'per_torrent_up_min': 3, 'per_torrent_up_max': 20, 'per_torrent_up_auto': True,
    'max_connec_min': 40, 'max_connec_max': 250, 'max_connec_auto': True,
    'per_torrent_connec_min': 10, 'per_torrent_connec_max': 60,
    'active_uploads_mode': 'keep', 'active_uploads_min': 6, 'active_uploads_max': 20,
    'channel_target_min': 80, 'channel_target_max': 100,
    'up_limit_pct': 0, 'dl_limit_pct': 0,
    'squeeze_enabled': False, 'squeeze_up_pct': 60, 'squeeze_dl_pct': 60,
    'cooldown_sec': 150, 'step_up_size': 4,
    'yield_to_turtle': True,
    'guards': {
        'disk': {'enabled': False, 'target_disk': '', 'warn': 80, 'crit': 95, 'recover': 60},
        'cpu':  {'enabled': False, 'warn': 80, 'recover': 60},
        'ram':  {'enabled': True,  'min_free': 10, 'recover_free': 18},
        'net':  {'enabled': False, 'warn_pct': 30, 'recover_pct': 15},
    }
}

BUILTIN_PRESETS = [
    {
        'id': 'turbo_night',
        'name': 'Турбо / Ночь',
        'icon': '🚀',
        'config': {
            'max_uploads_min': 20, 'max_uploads_max': 150, 'max_uploads_start': 60,
            'per_torrent_up_min': 5, 'per_torrent_up_max': 45, 'per_torrent_up_auto': True,
            'max_connec_min': 80, 'max_connec_max': 600, 'max_connec_auto': True,
            'per_torrent_connec_min': 20, 'per_torrent_connec_max': 150,
            'active_uploads_mode': 'keep', 'active_uploads_min': 15, 'active_uploads_max': 50,
            'channel_target_min': 90, 'channel_target_max': 100,
            'up_limit_pct': 0, 'dl_limit_pct': 0, 'squeeze_enabled': False,
            'cooldown_sec': 120, 'step_up_size': 6, 'yield_to_turtle': True,
            'guards': {
                'disk': {'enabled': False, 'target_disk': '', 'warn': 90, 'crit': 98, 'recover': 75},
                'cpu':  {'enabled': False, 'warn': 90, 'recover': 70},
                'ram':  {'enabled': True,  'min_free': 8,  'recover_free': 15},
                'net':  {'enabled': False, 'warn_pct': 50, 'recover_pct': 30},
            }
        }
    },
    {
        'id': 'performance',
        'name': 'Производительность',
        'icon': '⚡',
        'config': {
            'max_uploads_min': 30, 'max_uploads_max': 80, 'max_uploads_start': 40,
            'per_torrent_up_min': 4, 'per_torrent_up_max': 25, 'per_torrent_up_auto': True,
            'max_connec_min': 120, 'max_connec_max': 320, 'max_connec_auto': True,
            'per_torrent_connec_min': 15, 'per_torrent_connec_max': 80,
            'active_uploads_mode': 'keep', 'active_uploads_min': 10, 'active_uploads_max': 30,
            'channel_target_min': 85, 'channel_target_max': 100,
            'up_limit_pct': 0, 'dl_limit_pct': 0, 'squeeze_enabled': False,
            'cooldown_sec': 150, 'step_up_size': 5, 'yield_to_turtle': True,
            'guards': {
                'disk': {'enabled': True,  'target_disk': '', 'warn': 80, 'crit': 92, 'recover': 60},
                'cpu':  {'enabled': True,  'warn': 85, 'recover': 65},
                'ram':  {'enabled': True,  'min_free': 10, 'recover_free': 18},
                'net':  {'enabled': False, 'warn_pct': 45, 'recover_pct': 25},
            }
        }
    },
    {
        'id': 'balance',
        'name': 'Баланс / Дневной',
        'icon': '⚖️',
        'config': {
            'max_uploads_min': 15, 'max_uploads_max': 45, 'max_uploads_start': 25,
            'per_torrent_up_min': 3, 'per_torrent_up_max': 15, 'per_torrent_up_auto': True,
            'max_connec_min': 60, 'max_connec_max': 200, 'max_connec_auto': True,
            'per_torrent_connec_min': 12, 'per_torrent_connec_max': 50,
            'active_uploads_mode': 'range', 'active_uploads_min': 6, 'active_uploads_max': 16,
            'channel_target_min': 75, 'channel_target_max': 90,
            'up_limit_pct': 90, 'dl_limit_pct': 90, 'squeeze_enabled': True, 'squeeze_up_pct': 55, 'squeeze_dl_pct': 55,
            'cooldown_sec': 180, 'step_up_size': 3, 'yield_to_turtle': True,
            'guards': {
                'disk': {'enabled': True, 'target_disk': '', 'warn': 70, 'crit': 88, 'recover': 50},
                'cpu':  {'enabled': True, 'warn': 70, 'recover': 45},
                'ram':  {'enabled': True, 'min_free': 15, 'recover_free': 25},
                'net':  {'enabled': True, 'warn_pct': 30, 'recover_pct': 15},
            }
        }
    },
    {
        'id': 'gaming',
        'name': 'Игровой (CS2)',
        'icon': '🎮',
        'config': {
            'max_uploads_min': 4, 'max_uploads_max': 12, 'max_uploads_start': 8,
            'per_torrent_up_min': 2, 'per_torrent_up_max': 5, 'per_torrent_up_auto': True,
            'max_connec_min': 16, 'max_connec_max': 48, 'max_connec_auto': True,
            'per_torrent_connec_min': 8, 'per_torrent_connec_max': 20,
            'active_uploads_mode': 'range', 'active_uploads_min': 3, 'active_uploads_max': 6,
            'channel_target_min': 60, 'channel_target_max': 80,
            'up_limit_pct': 80, 'dl_limit_pct': 80, 'squeeze_enabled': True, 'squeeze_up_pct': 35, 'squeeze_dl_pct': 35,
            'cooldown_sec': 180, 'step_up_size': 2, 'yield_to_turtle': True,
            'guards': {
                'disk': {'enabled': True, 'target_disk': '', 'warn': 55, 'crit': 80, 'recover': 35},
                'cpu':  {'enabled': True, 'warn': 50, 'recover': 35},
                'ram':  {'enabled': True, 'min_free': 20, 'recover_free': 28},
                'net':  {'enabled': True, 'warn_pct': 15, 'recover_pct': 8},
            }
        }
    },
    {
        'id': 'quiet_min',
        'name': 'Тихий минимум',
        'icon': '🤫',
        'config': {
            'max_uploads_min': 3, 'max_uploads_max': 6, 'max_uploads_start': 4,
            'per_torrent_up_min': 1, 'per_torrent_up_max': 3, 'per_torrent_up_auto': False,
            'max_connec_min': 12, 'max_connec_max': 24, 'max_connec_auto': True,
            'per_torrent_connec_min': 6, 'per_torrent_connec_max': 12,
            'active_uploads_mode': 'fixed', 'active_uploads_min': 2, 'active_uploads_max': 3,
            'channel_target_min': 20, 'channel_target_max': 30,
            'up_limit_pct': 25, 'dl_limit_pct': 25, 'squeeze_enabled': True, 'squeeze_up_pct': 15, 'squeeze_dl_pct': 15,
            'cooldown_sec': 240, 'step_up_size': 1, 'yield_to_turtle': True,
            'guards': {
                'disk': {'enabled': True, 'target_disk': '', 'warn': 40, 'crit': 65, 'recover': 25},
                'cpu':  {'enabled': True, 'warn': 35, 'recover': 20},
                'ram':  {'enabled': True, 'min_free': 25, 'recover_free': 35},
                'net':  {'enabled': True, 'warn_pct': 10, 'recover_pct': 5},
            }
        }
    }
]

POPULAR_APPS_CATALOG = [
    {
        'category': 'Игры',
        'icon': '🎮',
        'apps': [
            {'exe': 'cs2.exe', 'name': 'Counter-Strike 2', 'icon': '🔫'},
            {'exe': 'dota2.exe', 'name': 'Dota 2', 'icon': '⚔️'},
            {'exe': 'GTA5.exe', 'name': 'GTA V', 'icon': '🚗'},
            {'exe': 'VALORANT-Win64-Shipping.exe', 'name': 'Valorant', 'icon': '🎯'},
            {'exe': 'TslGame.exe', 'name': 'PUBG: Battlegrounds', 'icon': '🪖'},
            {'exe': 'r5apex.exe', 'name': 'Apex Legends', 'icon': '🦊'},
            {'exe': 'RustClient.exe', 'name': 'Rust', 'icon': '🪨'},
            {'exe': 'WorldOfTanks.exe', 'name': 'World of Tanks', 'icon': '🛡️'},
            {'exe': 'javaw.exe', 'name': 'Minecraft (Java)', 'icon': '⛏️'},
            {'exe': 'EscapeFromTarkov.exe', 'name': 'Escape from Tarkov', 'icon': '🎒'},
            {'exe': 'FortniteClient-Win64-Shipping.exe', 'name': 'Fortnite', 'icon': '🏗️'},
            {'exe': 'Cyberpunk2077.exe', 'name': 'Cyberpunk 2077', 'icon': '🦾'},
        ]
    },
    {
        'category': 'Стрим и звонки',
        'icon': '🎙️',
        'apps': [
            {'exe': 'obs64.exe', 'name': 'OBS Studio', 'icon': '🎥'},
            {'exe': 'Discord.exe', 'name': 'Discord', 'icon': '🎧'},
            {'exe': 'Zoom.exe', 'name': 'Zoom', 'icon': '📹'},
            {'exe': 'Telegram.exe', 'name': 'Telegram Desktop', 'icon': '✈️'},
            {'exe': 'ms-teams.exe', 'name': 'Microsoft Teams', 'icon': '💼'},
        ]
    },
    {
        'category': 'Тяжёлый софт и лаунчеры',
        'icon': '🛠️',
        'apps': [
            {'exe': 'Adobe Premiere Pro.exe', 'name': 'Premiere Pro', 'icon': '🎬'},
            {'exe': 'Resolve.exe', 'name': 'DaVinci Resolve', 'icon': '🎞️'},
            {'exe': 'Photoshop.exe', 'name': 'Adobe Photoshop', 'icon': '🎨'},
            {'exe': 'blender.exe', 'name': 'Blender 3D', 'icon': '🧊'},
            {'exe': 'steam.exe', 'name': 'Steam', 'icon': '🚂'},
            {'exe': 'EpicGamesLauncher.exe', 'name': 'Epic Games', 'icon': '🏪'},
        ]
    }
]

APP_FRIENDLY_NAMES = {}
for grp in POPULAR_APPS_CATALOG:
    for app in grp['apps']:
        APP_FRIENDLY_NAMES[app['exe'].lower()] = {'name': app['name'], 'icon': app['icon'], 'exe': app['exe']}


def merge_profile_config(base, patch):
    res = deepcopy(base)
    if not isinstance(patch, dict):
        return res
    for k, v in patch.items():
        if k in res and isinstance(res[k], dict) and isinstance(v, dict):
            res[k] = merge_profile_config(res[k], v)
        else:
            res[k] = v
    return res
