# AI Assistant

**Version 1.0.0** — Web-based AI assistant using [Ollama](https://ollama.ai) as the LLM backend. Dark UI, streaming chat, file and folder support.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)

## Features

- **Chat** — Dark theme, streaming responses, Markdown and code highlighting with copy button
- **Attach files** — One or multiple files (PDF, Word, TXT, CSV); drag & drop supported
- **Choose folder** — Pick a folder from your machine; all supported files are uploaded and summarized per file
- **Folder by path** — Enter a server-side folder path to summarize (optional, for local/network paths)
- **Model selection** — Dropdown from Ollama; switch model per conversation
- **Modular CSS** — UI styles split into `static/css/` modules for easy theming

## Requirements

- **Python** 3.10+
- **Ollama** installed and running ([ollama.ai](https://ollama.ai))
- At least one model pulled (e.g. `ollama pull llama3.2`)

## Install

```bash
cd ai_assistant
python -m venv venv_web
# Windows:
.\venv_web\Scripts\Activate.ps1
# macOS/Linux:
source venv_web/bin/activate
pip install -r requirements.txt
```

## Run

Start Ollama if needed (e.g. `ollama serve` or open the Ollama app), then:

```bash
python main.py
```

The server runs at http://127.0.0.1:8000 (or 8001/8002 if 8000 is busy) and opens the browser.

## Project structure

```
ai_assistant/
├── main.py              # Launcher: start server + open browser
├── server.py             # FastAPI: /, /upload, /ws, /api/models, /api/folder-summary
├── ai_service.py         # Ollama streaming and summarization
├── config.py             # Port, paths, limits
├── requirements.txt
├── VERSION               # 1.0.0
├── static/
│   ├── index.html        # Single-page UI
│   └── css/              # Modular styles (variables, sidebar, header, messages, etc.)
└── app/
    ├── core/             # ollama_client, file_parser, folder_agent, history_manager, text_chunker
    └── utils/             # config_manager, logger
```

## API overview

| Endpoint        | Description |
|----------------|-------------|
| `GET /`        | Serve the web UI |
| `GET /health`  | Health check |
| `GET /api/models` | List Ollama models |
| `POST /upload` | Upload a file; returns `file_id` |
| `POST /api/folder-summary` | Stream per-file summaries for a folder path (SSE) |
| `WebSocket /ws` | Chat (streaming), `folder_summary`, `multi_file_summary` |

## Troubleshooting

- **"Ollama is not running"** — Start Ollama (app or `ollama serve`).
- **No models** — Run `ollama pull <model>`.
- **File errors** — Only .pdf, .docx, .txt, .csv are supported; files must not be password-protected.
- **Logs** — See `app.log` in the project directory (create it by running the app).

## License

Use and modify as you like. Ollama and its models have their own terms.
