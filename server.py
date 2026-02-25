"""FastAPI server: static files, file upload, WebSocket chat."""

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import config
from app.core.folder_agent import iter_file_summaries, iter_uploaded_file_summaries
from app.utils.logger import setup_logger
from ai_service import get_models as ai_get_models

logger = setup_logger(__name__)

app = FastAPI(title="AI Assistant", version="1.0.0")

# In-memory store for uploaded file contents: file_id -> { "name": str, "text": str }
_upload_store: dict[str, dict[str, str]] = {}
_UPLOAD_STORE_MAX = getattr(config, "UPLOAD_MAX_ENTRIES", 20)

# Session state per WebSocket: ws_id -> { "messages": list[dict], "conversation_title": str }
_sessions: dict[str, dict[str, Any]] = {}


def _store_upload(file_id: str, name: str, text: str) -> None:
    _upload_store[file_id] = {"name": name, "text": text}
    while len(_upload_store) > _UPLOAD_STORE_MAX:
        # Drop oldest (first key)
        k = next(iter(_upload_store), None)
        if k:
            del _upload_store[k]
        else:
            break


def _get_upload(file_id: str | None) -> tuple[str, str] | None:
    if not file_id or file_id not in _upload_store:
        return None
    entry = _upload_store[file_id]
    return (entry["name"], entry["text"])


def _get_or_create_session(ws_id: str) -> dict[str, Any]:
    if ws_id not in _sessions:
        _sessions[ws_id] = {"messages": [], "conversation_title": "New Chat"}
    return _sessions[ws_id]


# Mount static only if dir exists (so we can serve index.html from static/)
# Folder summary request body
class FolderSummaryRequest(BaseModel):
    folder_path: str
    recursive: bool = True
    model: Optional[str] = None


def _validate_folder_path(folder_path: str) -> Path:
    path = Path(folder_path).resolve()
    if not path.exists():
        raise HTTPException(404, f"Folder not found: {path}")
    if not path.is_dir():
        raise HTTPException(400, f"Not a directory: {path}")
    bases = getattr(config, "ALLOWED_FOLDER_BASES", None) or []
    if bases:
        allowed = [Path(b).resolve() for b in bases]
        if not any(path == a or str(path).startswith(str(a) + os.sep) for a in allowed):
            raise HTTPException(403, "Folder path is not in the allowed list")
    return path


if config.STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")


@app.get("/health")
async def health():
    """Readiness check for launcher."""
    return {"status": "ok"}


@app.get("/api/models")
async def api_models():
    """Return list of available Ollama model names."""
    return {"models": ai_get_models()}


@app.get("/")
async def index():
    """Serve the single-page app."""
    index_path = config.STATIC_DIR / "index.html"
    if not index_path.is_file():
        return PlainTextResponse("index.html not found", status_code=404)
    return FileResponse(index_path)


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    """Accept a file, extract text, store by file_id, return file_id."""
    from app.core.file_parser import extract_text

    name = file.filename or "file"
    suffix = Path(name).suffix.lower()
    allowed = {".pdf", ".docx", ".txt", ".csv"}
    if suffix not in allowed:
        raise HTTPException(400, f"Unsupported format. Use: {', '.join(allowed)}")

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > getattr(config, "UPLOAD_MAX_MB", 50):
        raise HTTPException(400, f"File too large (max {config.UPLOAD_MAX_MB} MB)")

    # Write to temp file so file_parser can open by path (PDF/DOCX need path)
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        text = await asyncio.to_thread(extract_text, tmp_path)
    except Exception as e:
        os.unlink(tmp_path)
        logger.exception("Upload extract_text failed: %s", e)
        raise HTTPException(400, str(e))
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    file_id = str(uuid.uuid4())
    _store_upload(file_id, name, text)
    return {"file_id": file_id, "name": name}



@app.post("/api/folder-summary")
async def api_folder_summary(body: FolderSummaryRequest):
    async def event_stream():
        folder = _validate_folder_path(body.folder_path)
        async for info in iter_file_summaries(folder, recursive=body.recursive, model=body.model):
            payload = {"name": info["name"], "summary": info["summary"], "error": info.get("error")}
            yield "data: " + json.dumps(payload) + "\n\n"
        yield "data: " + json.dumps({"done": True}) + "\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_id = id(websocket)
    session = _get_or_create_session(ws_id)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = data.get("type")
            if msg_type == "chat":
                message = (data.get("message") or "").strip()
                file_id = data.get("file_id")
                model = (data.get("model") or "").strip() or None

                if not message and not file_id:
                    await websocket.send_json({"type": "error", "message": "Empty message"})
                    continue

                # Build user message text (include file content if file_id present)
                user_text = message
                file_info = _get_upload(file_id) if file_id else None
                if file_info:
                    file_name, file_text = file_info
                    user_text = await _build_user_message_with_file(
                        message, file_name, file_text, websocket
                    )
                    if user_text is None:
                        continue  # error already sent

                # Append user message and stream response
                session["messages"].append({"role": "user", "content": user_text})
                if session["conversation_title"] == "New Chat" and user_text:
                    session["conversation_title"] = (user_text[:50] + "...") if len(user_text) > 50 else user_text

                from ai_service import stream_response

                full_reply = []
                try:
                    async for token in stream_response(
                        session["messages"],
                        model=model,
                        ws_id=ws_id,
                    ):
                        full_reply.append(token)
                        await websocket.send_json({"type": "token", "content": token})
                    await websocket.send_json({"type": "done"})
                    session["messages"].append({"role": "assistant", "content": "".join(full_reply)})
                except Exception as e:
                    err_msg = str(e) if str(e) else "Generation failed"
                    logger.exception("Stream error: %s", e)
                    await websocket.send_json({"type": "error", "message": err_msg})
                    session["messages"].append({"role": "assistant", "content": f"Error: {err_msg}"})
            elif msg_type == "load_conversation":
                pass
            elif msg_type == "folder_summary":
                fp = (data.get("folder_path") or "").strip()
                if not fp:
                    await websocket.send_json({"type": "error", "message": "Missing folder_path"})
                    continue
                try:
                    folder = _validate_folder_path(fp)
                except HTTPException as e:
                    await websocket.send_json({"type": "error", "message": e.detail})
                    continue
                rec = data.get("recursive", True)
                mod = (data.get("model") or "").strip() or None
                try:
                    async for info in iter_file_summaries(folder, recursive=rec, model=mod):
                        await websocket.send_json({"type": "folder_file", "name": info["name"], "summary": info["summary"], "error": info.get("error")})
                    await websocket.send_json({"type": "folder_done"})
                except Exception as e:
                    logger.exception("Folder summary error: %s", e)
                    await websocket.send_json({"type": "error", "message": str(e)})
            elif msg_type == "multi_file_summary":
                file_ids = data.get("file_ids") or []
                if not file_ids:
                    await websocket.send_json({"type": "error", "message": "Missing file_ids"})
                    continue
                items = []
                for fid in file_ids:
                    info = _get_upload(fid)
                    if not info:
                        await websocket.send_json({"type": "error", "message": "File not found"})
                        break
                    items.append(info)
                else:
                    mod = (data.get("model") or "").strip() or None
                    try:
                        async for info in iter_uploaded_file_summaries(items, model=mod):
                            await websocket.send_json({"type": "folder_file", "name": info["name"], "summary": info["summary"], "error": info.get("error")})
                        await websocket.send_json({"type": "folder_done"})
                    except Exception as e:
                        logger.exception("Multi-file summary error: %s", e)
                        await websocket.send_json({"type": "error", "message": str(e)})
            else:
                await websocket.send_json({"type": "error", "message": f"Unknown type: {msg_type}"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("WebSocket error: %s", e)
    finally:
        _sessions.pop(ws_id, None)


async def _build_user_message_with_file(
    user_message: str, file_name: str, file_text: str, websocket: WebSocket
) -> str | None:
    """If file is long, summarize in thread then build message. Returns None and sends error on failure."""
    from app.core.text_chunker import word_count, chunk_text
    from ai_service import summarize_long_text

    max_words = getattr(config, "MAX_FILE_WORDS", 6000)
    if word_count(file_text) <= max_words:
        header = f"[File: {file_name}]\n"
        return f"{header}{file_text}\n\nUser question: {user_message}"

    # Long file: summarize chunks then combine
    try:
        model = None  # will use default in summarize_long_text
        combined = await summarize_long_text(file_text, model=model)
    except Exception as e:
        logger.exception("Summarize failed: %s", e)
        await websocket.send_json({"type": "error", "message": f"Document summarization failed: {e}"})
        return None
    header = f"[File: {file_name} — summarized content below]\n"
    return f"{header}{combined}\n\nUser question: {user_message}"
