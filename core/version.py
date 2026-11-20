# core/version.py
import re

APP_VERSION = "4.0.0"
GITHUB_OWNER = "kamushek0o"
GITHUB_REPO = "tbr"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

_SEMVER_RE = re.compile(r'(\d+)\.(\d+)\.(\d+)')


def parse_semver(ver_str):
    """Строгое числовое разложение версии в кортеж (major, minor, patch)."""
    m = _SEMVER_RE.search(str(ver_str or "").strip().lstrip("vV"))
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def is_newer_version(remote_ver, local_ver=APP_VERSION):
    """Возвращает True, если remote_ver строго новее local_ver."""
    return parse_semver(remote_ver) > parse_semver(local_ver)