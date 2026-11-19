# core/ui_defaults.py
import json
from copy import deepcopy

DEFAULT_UI_SETTINGS = {
    "version": 2,
    "theme": "dark",
    "custom_colors": {"bg_main": "#121214", "bg_panel": "#1a1a20", "text": "#ffffff", "accent": "#2ecc71"},
    "font": "Segoe UI",
    "allow_google_fonts": False,
    "mobile_mode": True,
    "charts": {
        "daily": {"color": "#2ecc71", "color2": "#10b981", "gradient": True, "opacity": 0.75},
        "top5": {"color": "#ff9f1c", "color2": "#ff4d6d", "gradient": True, "opacity": 0.8},
        "hourly": {"color": "#00f5d4", "color2": "#9b5de5", "gradient": True, "opacity": 0.35},
        "hourly_hours": 24,
        "hourly_y_min": None,
        "top_n": 5,
        "top_period": "1d",
        "top_scale": "lin"
    },
    "peer_client_colors": {
        "qBittorrent": "#2ecc71",
        "Transmission": "#e74c3c",
        "uTorrent": "#27ae60",
        "Deluge": "#3498db",
        "BiglyBT": "#9b59b6",
        "Aria2": "#1abc9c",
        "Tixati": "#f39c12",
        "Vuze": "#00bcd4",
        "libtorrent": "#95a5a6",
        "Прочие": "#64748b"
    },
    "summary_columns": {
        "visible": ["name", "size", "uploaded", "ratio", "health_score", "speed_all_time", "speed_1h", "speed_24h", "vol_hour", "vol_day", "ratio_h_all", "created"],
        "order": ["name", "size", "uploaded", "ratio", "health_score", "speed_all_time", "speed_1h", "speed_24h", "vol_hour", "vol_day", "ratio_h_all", "created"],
        "widths": {}
    }
}


def merge_ui_defaults(raw_json):
    result = deepcopy(DEFAULT_UI_SETTINGS)
    if not raw_json:
        return result
    try:
        data = json.loads(raw_json) if isinstance(raw_json, str) else dict(raw_json)
    except Exception:
        return result

    def deep_merge(dst, src):
        for k, v in src.items():
            if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
                deep_merge(dst[k], v)
            else:
                dst[k] = v

    if isinstance(data, dict):
        deep_merge(result, data)
    result["version"] = DEFAULT_UI_SETTINGS["version"]
    return result