import json, os
from typing import Any

OVERRIDE_PATH = "data/manager_overrides.json"


def get_overrides() -> dict:
    if not os.path.exists(OVERRIDE_PATH):
        return {}
    try:
        with open(OVERRIDE_PATH) as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except (json.JSONDecodeError, IOError):
        return {}


def override(directives: dict, key: str, default: Any) -> Any:
    return directives.get(key, default)


def get_banned_topics(directives: dict) -> list[str]:
    return directives.get("banned_topics", [])


def get_required_keywords(directives: dict) -> list[str]:
    return directives.get("required_keywords", [])
