"""
bot/updater.py — Auto-Update Checker for L.A.R.P
Uses GitHub Releases API to compare the local version against the latest release.
"""

import threading
import logging
import webbrowser
from packaging.version import Version

# --- Constants ---
CURRENT_VERSION = "1.0.0"
GITHUB_REPO = "hivestupid-cmyk/LARP"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"

logger = logging.getLogger(__name__)


def get_latest_release() -> dict | None:
    """
    Fetch the latest release info from the GitHub API.
    Returns a dict with 'tag_name' and 'html_url', or None on failure.
    """
    try:
        import urllib.request
        import json
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={"User-Agent": f"LARP-Bot/{CURRENT_VERSION}"}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            return {
                "tag_name": data.get("tag_name", "").lstrip("v"),
                "html_url": data.get("html_url", GITHUB_RELEASES_URL),
                "body": data.get("body", "No release notes available."),
                "name": data.get("name", "New Release"),
            }
    except Exception as e:
        logger.warning(f"[Updater] Version check failed: {e}")
        return None


def is_newer(remote_version: str) -> bool:
    """Returns True if the remote version is strictly newer than the local version."""
    try:
        return Version(remote_version) > Version(CURRENT_VERSION)
    except Exception:
        return False


def check_for_updates_async(callback):
    """
    Run the update check in a background thread to avoid freezing the UI.
    'callback' is called with the release dict if an update is available, else None.
    """
    def _worker():
        release = get_latest_release()
        if release and is_newer(release["tag_name"]):
            callback(release)
        else:
            callback(None)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


def open_release_page(url: str = GITHUB_RELEASES_URL):
    """Open the GitHub releases page in the user's default browser."""
    webbrowser.open(url)
