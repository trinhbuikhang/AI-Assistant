"""Save and load conversation history as JSON files."""

import json
import os
import re
from pathlib import Path
from typing import Any

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Store history locally per user, not on the network share
HISTORY_DIR = Path(
    os.path.join(
        os.path.expanduser("~"),
        "Documents", "AI_Assistant", "chat_history"
    )
)


def get_history_dir(base_path: Path | None = None) -> Path:
    """Return the chat_history directory (created if needed)."""
    d = Path(HISTORY_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sanitize_filename(title: str) -> str:
    """Make a string safe for use in filenames."""
    s = re.sub(r'[<>:"/\\|?*]', "_", title)
    return s.strip()[:80] or "untitled"


def save_conversation(
    title: str,
    model: str,
    messages: list[dict],
    base_path: Path | None = None,
) -> Path:
    """
    Save conversation to user's Documents/AI_Assistant/chat_history/{timestamp}_{title}.json.
    Returns the path of the saved file. Raises OSError on write failure.
    """
    import time
    dir_path = get_history_dir(base_path)
    safe_title = _sanitize_filename(title)
    ts = int(time.time())
    filename = f"{ts}_{safe_title}.json"
    path = dir_path / filename
    data = {"title": title, "model": model, "messages": messages}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as e:
        logger.exception("Failed to save conversation to %s: %s", path, e)
        raise
    logger.info("Saved conversation to %s", path)
    return path


def load_conversation(path: Path) -> dict[str, Any]:
    """Load a conversation from a JSON file. Raises ValueError with user-friendly message on error."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Invalid conversation file format.")
        return data
    except json.JSONDecodeError as e:
        logger.warning("Corrupted conversation file %s: %s", path, e)
        raise ValueError(f"Could not read conversation file: file may be corrupted.") from e
    except OSError as e:
        logger.warning("Could not open conversation file %s: %s", path, e)
        raise ValueError(f"Could not open file: {e}") from e


def list_conversations(base_path: Path | None = None) -> list[tuple[Path, str, str]]:
    """
    List all saved conversations. Returns list of (path, title, model).
    Sorted by modification time, newest first.
    """
    dir_path = get_history_dir(base_path)
    results = []
    for p in dir_path.glob("*.json"):
        try:
            data = load_conversation(p)
            title = data.get("title", p.stem)
            model = data.get("model", "")
            results.append((p, title, model))
        except (ValueError, json.JSONDecodeError, OSError) as e:
            logger.warning("Skip invalid history file %s: %s", p, e)
    try:
        results.sort(key=lambda x: x[0].stat().st_mtime, reverse=True)
    except OSError:
        pass
    return results
