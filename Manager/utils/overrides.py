"""
utils/overrides.py — Runtime override loader.

Every agent calls get_overrides() to check if the Gemini Manager
has issued any live directives that should supersede config.py defaults.

Usage in any agent:
    from utils.overrides import get_overrides, override
    OV = get_overrides()

    # Use override() to safely fall back to config default if not set
    video_length = override(OV, "video_length_min", config.VIDEO_LENGTH_MIN)
"""

import json, os
from typing import Any

OVERRIDE_PATH = "data/manager_overrides.json"


def get_overrides() -> dict:
    """Load current manager directives. Returns empty dict if none set."""
    if not os.path.exists(OVERRIDE_PATH):
        return {}
    try:
        with open(OVERRIDE_PATH) as f:
            data = json.load(f)
        # Strip internal meta keys
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except (json.JSONDecodeError, IOError):
        return {}


def override(directives: dict, key: str, default: Any) -> Any:
    """Return directive value if set, otherwise the config default."""
    return directives.get(key, default)


def get_banned_topics(directives: dict) -> list[str]:
    return directives.get("banned_topics", [])


def get_required_keywords(directives: dict) -> list[str]:
    return directives.get("required_keywords", [])
