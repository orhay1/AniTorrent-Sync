import copy
import logging
from pathlib import Path

import yaml

# Same values as config.example.yaml. Any key missing from a user's config is
# filled from here, so an incomplete file (e.g. one saved by an older GUI
# version) still loads instead of failing.
DEFAULT_CONFIG: dict = {
    "anilist_username": "",
    "shows": [],
    "quality": "1080p",
    "codec": "HEVC",
    "qbittorrent": {
        "host": "localhost",
        "port": 8080,
        "username": "",
        "password": "",
        "https": False,
    },
    "preferred_group": "",
    "release_groups": [],
    "recent_show": "",
    "recent_shows": [],
    "recent_group": "",
    "recent_count": 5,
    "recent_quality": "",
    "recent_codec": "",
    "recent_episode": "",
}


def default_config() -> dict:
    return copy.deepcopy(DEFAULT_CONFIG)


def fill_defaults(data: dict) -> tuple[dict, list[str]]:
    """Add any missing keys (including qbittorrent.*) from DEFAULT_CONFIG. Returns (config, added keys)."""
    added: list[str] = []
    for key, value in DEFAULT_CONFIG.items():
        if key not in data or (key == "shows" and data[key] is None):
            data[key] = copy.deepcopy(value)
            added.append(key)
    qb = data.get("qbittorrent")
    if not isinstance(qb, dict):
        data["qbittorrent"] = copy.deepcopy(DEFAULT_CONFIG["qbittorrent"])
        if "qbittorrent" not in added:
            added.append("qbittorrent")
    else:
        for key, value in DEFAULT_CONFIG["qbittorrent"].items():
            if key not in qb:
                qb[key] = value
                added.append(f"qbittorrent.{key}")
    return data, added


def load_config_with_report(path: str) -> tuple[dict, list[str]]:
    """Load a YAML config, filling missing keys with defaults. Returns (config, added keys)."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain YAML key/value pairs")

    return fill_defaults(data)


def load_config(path: str) -> dict:
    """
    Load a YAML config file and return it as a Python dictionary.
    Missing keys are filled with defaults (see DEFAULT_CONFIG).
    """
    data, added = load_config_with_report(path)
    if added:
        logging.warning("Config %s was missing %s; using defaults for them.", path, ", ".join(added))
    return data
