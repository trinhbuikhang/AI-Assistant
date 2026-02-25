# Migration: PyQt6 → Web (FastAPI + Browser)

All PyQt6 code has been removed. The app is now web-only.

## Removed (PyQt6)

- **Entry point**: `main_desktop.py` — deleted
- **UI package**: entire `app/ui/` folder — deleted
  - `main_window.py`, `chat_widget.py`, `input_bar.py`, `sidebar.py`, `settings_dialog.py`, `styles.qss`, `__init__.py`
- **Dependency**: PyQt6 removed from `requirements.txt`

## Current stack

| Layer        | Technology |
|-------------|------------|
| Entry       | `main.py` — launcher (uvicorn + webbrowser) |
| Server      | FastAPI — `server.py` |
| Chat / API  | WebSocket `/ws`, `POST /upload`, `GET /api/models` |
| Frontend    | `static/index.html` — single file, vanilla JS + CSS |
| AI          | `ai_service.py` + `app/core/ollama_client.py` |
| File parse  | `app/core/file_parser.py` (includes `collect_supported_files` for folder loading) |

## What stayed

- **AI**: Ollama client, streaming, sync generate, model list
- **History**: `app/core/history_manager.py` (can be wired to WebSocket/sidebar later)
- **File parsing**: `app/core/file_parser.py` — used by `POST /upload` and by `test_folder_summary.py` (which now uses `collect_supported_files` from here)
- **Config**: `app/utils/config_manager.py`, `config.json`
- **Logging**: `app/utils/logger.py`

## How to run

```bash
pip install -r requirements.txt
python main.py
```

Server starts on port 8000 (or 8001/8002 if busy) and opens the browser.

## Optional next steps

- Persist conversations: wire `history_manager` to WebSocket and add `GET /api/conversations` for the sidebar
- Settings UI: add a page/modal that POSTs to `/api/config` to update `config.json`
