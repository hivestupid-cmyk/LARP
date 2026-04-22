"""
bot/config.py — Simple JSON config loader with portable path resolution.

Usage:
    from bot.config import config
    fps = config.get("bot", "target_fps", 60)

Path resolution:
    Values for "model_path" and "macro_file" in config.json can be either:
    - Relative paths (e.g. "assets/models/best.pt")  → resolved from project root
    - Absolute paths (e.g. "C:/models/best.pt")       → used as-is
"""

import json
import os
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)

# Root of the project = two levels up from this file (bot/config.py → bot/ → project root)
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config.json")

# Keys whose values should be resolved as file/directory paths
_PATH_KEYS = {"model_path", "macro_file", "models_dir", "templates_dir", "debug_dir"}


def _resolve_path(value: str) -> str:
    """
    If `value` is a relative path, resolve it against the project root.
    If it's already absolute (or a URL), return it unchanged.
    """
    if not isinstance(value, str) or not value:
        return value
    # Absolute path check: starts with drive letter (Windows) or '/' (Unix)
    if os.path.isabs(value) or (len(value) >= 2 and value[1] == ':'):
        return value
    return os.path.join(_PROJECT_ROOT, value)


class _Config:
    def __init__(self, path: str):
        self._path = path
        self._data: dict = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                self._data = json.load(f)

            # FOV Aim Assist Defaults
            if "aim_assist" not in self._data:
                self._data["aim_assist"] = {
                    "fov_radius": 150,
                    "show_fov_circle": True,
                    "p_gain": 0.4,
                    "max_delta": 15
                }
            logger.info(f"Config loaded from {path}")
        except FileNotFoundError:
            logger.warning(f"config.json not found at {path}. Using defaults.")
        except json.JSONDecodeError as e:
            logger.error(f"Config parse error: {e}. Using defaults.")

    def reload(self):
        """Reloads the config data from disk (Hot-Reload)."""
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                new_data = json.load(f)
                self._data.clear()
                self._data.update(new_data)
            logger.info(f"Config hot-reloaded from {self._path}")
        except FileNotFoundError:
            logger.warning(f"config.json not found at {self._path}. Kept previous data in memory.")
        except json.JSONDecodeError as e:
            logger.error(f"Config parse error during reload: {e}. Kept previous data in memory.")

    def get(self, section: str, key: Any = None, default=None):
        """
        Retrieves a value from config.
        Supports:
            get(section) -> entire section dict
            get(section, default) -> entire section dict if key is not a string
            get(section, key, default) -> specific value if key is a string

        Path keys (model_path, macro_file, etc.) are automatically resolved
        to absolute paths relative to the project root.
        """
        # If the second argument is NOT a string, treat it as the default for the section
        if key is not None and not isinstance(key, str):
            return self._data.get(section, key)

        if key is None:
            return self._data.get(section, default)

        # usage: get(section, key, default)
        value = self._data.get(section, {}).get(key, default)

        # Auto-resolve path values
        if key in _PATH_KEYS and isinstance(value, str) and value:
            value = _resolve_path(value)

        return value

    def save(self):
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=4)
            logger.info(f"Config saved to {self._path}")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    @property
    def project_root(self) -> str:
        """Returns the absolute path to the project root directory."""
        return _PROJECT_ROOT


config = _Config(_CONFIG_PATH)
