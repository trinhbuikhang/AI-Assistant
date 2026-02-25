"""Server configuration: port, default model, paths."""

from pathlib import Path

# Port with fallback list if 8000 is busy
PORT_DEFAULT = 8000
PORT_FALLBACKS = [8000, 8001, 8002]

# Base path for the app (ai_assistant folder)
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# Max words per file before summarization (matches desktop app)
MAX_FILE_WORDS = 6000

# Upload: in-memory store max entries (oldest dropped); temp files in this dir
UPLOAD_TEMP_DIR = BASE_DIR / "uploads_temp"
UPLOAD_MAX_MB = 50
UPLOAD_MAX_ENTRIES = 20

# Folder summary: allowed base paths for folder_path (security). Empty = allow any absolute path.
ALLOWED_FOLDER_BASES: list[Path] = []
