"""Read/write user settings from config.json."""

import json
from pathlib import Path

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

DEFAULT_CONFIG = {
    "system_prompt": "You are a helpful, concise, and intelligent AI assistant. Answer clearly and accurately. If you're unsure, say so.",
    "temperature": 0.7,
    "max_tokens": 2048,
    "stream": True,
    "default_model": "mixtral:8x7b",
}


def get_config_path() -> Path:
    """Return path to config.json in the application directory."""
    return Path(__file__).resolve().parent.parent.parent / "config.json"


def load_config() -> dict:
    """Load config from config.json. Creates file with defaults if missing or corrupted."""
    path = get_config_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Merge with defaults so new keys are always present
            out = dict(DEFAULT_CONFIG)
            out.update(data)
            return out
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Config file missing or corrupted, using defaults: %s", e)
    save_config(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    """Write config to config.json. Raises OSError on write failure."""
    path = get_config_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except OSError as e:
        logger.exception("Failed to save config to %s: %s", path, e)
        raise
