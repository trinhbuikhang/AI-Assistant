"""FastAPI server: static files, file upload, WebSocket chat."""

import asyncio
import json
import os
import threading
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
        _sessions[ws_id] = {"messages": [], "conversation_title": "New Chat", "stop_event": None}
    return _sessions[ws_id]


async def _ws_send_json_safe(websocket: WebSocket, data: dict[str, Any]) -> None:
    """Send JSON over WebSocket; ignore errors if connection is already closed."""
    try:
        await websocket.send_json(data)
    except RuntimeError as e:
        if "websocket.send" in str(e) or "already completed" in str(e):
            logger.debug("WebSocket send skipped (connection closed): %s", e)
        else:
            raise


# Mount static only if dir exists (so we can serve index.html from static/)
# Folder summary request body
class FolderSummaryRequest(BaseModel):
    folder_path: str
    recursive: bool = True
    model: Optional[str] = None


class ConfigUpdate(BaseModel):
    """Settings editable from the UI."""
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    default_model: Optional[str] = None


class ConversationSave(BaseModel):
    """One conversation to save to disk."""
    id: str
    title: str
    messages: list[dict[str, str]]


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
    """Return list of available Ollama model names and whether Ollama is reachable."""
    from app.core.ollama_client import check_ollama_running
    models = ai_get_models()
    ollama_ok = check_ollama_running()
    return {"models": models, "ollama_ok": ollama_ok}


@app.get("/api/config")
async def api_get_config():
    """Return current app config (for Settings UI)."""
    from app.utils.config_manager import load_config
    return load_config()


@app.put("/api/config")
async def api_put_config(body: ConfigUpdate):
    """Update config from Settings UI. Only provided fields are updated."""
    from app.utils.config_manager import load_config, save_config
    cfg = load_config()
    if body.system_prompt is not None:
        cfg["system_prompt"] = body.system_prompt
    if body.temperature is not None:
        cfg["temperature"] = max(0.0, min(2.0, float(body.temperature)))
    if body.max_tokens is not None:
        cfg["max_tokens"] = max(1, min(128000, int(body.max_tokens)))
    if body.default_model is not None:
        cfg["default_model"] = (body.default_model or "").strip() or cfg["default_model"]
    save_config(cfg)
    return cfg


def _chat_history_dir() -> Path:
    """Return and ensure chat history directory exists."""
    path = getattr(config, "CHAT_HISTORY_DIR", None) or config.BASE_DIR / "chat_history"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_conversation_id(conv_id: str) -> str:
    """Sanitize id for use as filename."""
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in (conv_id or "unknown"))[:64]


@app.get("/api/conversations")
async def api_get_conversations():
    """Load all saved conversations from chat_history folder. Keys = filename stem (safe id)."""
    directory = _chat_history_dir()
    result = {}
    for f in directory.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            # Use filename stem as key so client and DELETE use the same id
            cid = f.stem
            result[cid] = {"title": data.get("title") or "Chat", "messages": data.get("messages") or []}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Skip %s: %s", f.name, e)
    return {"conversations": result}


@app.post("/api/conversations")
async def api_save_conversation(body: ConversationSave):
    """Save one conversation to chat_history folder. Id is sanitized for filename."""
    directory = _chat_history_dir()
    safe_id = _safe_conversation_id(body.id)
    path = directory / f"{safe_id}.json"
    data = {"id": safe_id, "title": body.title or "Chat", "messages": body.messages or []}
    try:
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, ensure_ascii=False)
    except OSError as e:
        logger.exception("Save conversation failed: %s", e)
        raise HTTPException(500, "Could not save conversation")
    return {"ok": True, "id": safe_id}


@app.delete("/api/conversations/{conversation_id:path}")
async def api_delete_conversation(conversation_id: str):
    """Delete one conversation from chat_history folder. Finds by filename or by id inside JSON."""
    directory = _chat_history_dir()
    safe_id = _safe_conversation_id(conversation_id)
    path = directory / f"{safe_id}.json"
    if path.is_file():
        try:
            path.unlink()
            return {"ok": True}
        except OSError as e:
            logger.exception("Delete conversation failed: %s", e)
            raise HTTPException(500, "Could not delete conversation")
    # Find by id stored in JSON (for old ids with unicode/spaces)
    for f in directory.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("id") == conversation_id or f.stem == conversation_id:
                f.unlink()
                return {"ok": True}
        except (json.JSONDecodeError, OSError):
            continue
    raise HTTPException(404, "Conversation not found")


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

    raw_name = file.filename or "file"
    # Sanitize: basename only, no path traversal; strip leading dots and path separators
    name = os.path.basename(raw_name).lstrip(". ")
    if not name:
        name = "file"
    suffix = Path(name).suffix.lower()
    allowed = {".pdf", ".docx", ".txt", ".csv"}
    if suffix not in allowed:
        raise HTTPException(400, f"Unsupported format. Use: {', '.join(allowed)}")

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > getattr(config, "UPLOAD_MAX_MB", 50):
        raise HTTPException(400, f"File too large (max {config.UPLOAD_MAX_MB} MB)")

    # Use configured temp dir so temp files are in one place and can be cleaned
    config.UPLOAD_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    import tempfile
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=suffix, dir=str(config.UPLOAD_TEMP_DIR)
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        text = await asyncio.to_thread(extract_text, tmp_path)
    except Exception as e:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        logger.exception("Upload extract_text failed: %s", e)
        raise HTTPException(400, str(e))
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
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
            # Enforce max message size to prevent memory exhaustion
            msg = await websocket.receive()
            # Client disconnected — do not try to parse or send
            if msg.get("type") == "websocket.disconnect":
                break
            raw_bytes = msg.get("bytes")
            if raw_bytes is not None:
                if len(raw_bytes) > getattr(config, "WS_MAX_MESSAGE_BYTES", 512 * 1024):
                    await _ws_send_json_safe(websocket, {"type": "error", "message": "Message too large"})
                    continue
                try:
                    raw = raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    await _ws_send_json_safe(websocket, {"type": "error", "message": "Invalid encoding"})
                    continue
            else:
                raw = msg.get("text") or ""
                if len(raw.encode("utf-8")) > getattr(config, "WS_MAX_MESSAGE_BYTES", 512 * 1024):
                    await _ws_send_json_safe(websocket, {"type": "error", "message": "Message too large"})
                    continue
            if not raw.strip():
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await _ws_send_json_safe(websocket, {"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = data.get("type")
            if msg_type == "chat":
                message = (data.get("message") or "").strip()
                file_id = data.get("file_id")
                file_ids = data.get("file_ids") or []
                if file_id and not file_ids:
                    file_ids = [file_id]
                model = (data.get("model") or "").strip() or None

                if not message and not file_ids:
                    await _ws_send_json_safe(websocket, {"type": "error", "message": "Empty message"})
                    continue

                # Build user message text (include file content when file_id or file_ids present)
                user_text = message
                if file_ids:
                    items = []
                    for fid in file_ids:
                        info = _get_upload(fid)
                        if not info:
                            await _ws_send_json_safe(websocket, {"type": "error", "message": f"File not found: {fid}"})
                            break
                        items.append(info)
                    else:
                        user_text = await _build_user_message_with_files(
                            message, items, websocket
                        )
                        if user_text is None:
                            continue

                if len(user_text) > getattr(config, "MAX_MESSAGE_LENGTH", 50000):
                    await _ws_send_json_safe(websocket, {"type": "error", "message": "Message too long"})
                    continue

                # Optional: client can send conversation history (e.g. when loading a past chat)
                history = data.get("history")
                if isinstance(history, list):
                    session["messages"] = [{"role": m.get("role"), "content": m.get("content") or ""} for m in history if isinstance(m, dict) and m.get("role")]
                else:
                    session["messages"].append({"role": "user", "content": user_text})

                # When client sent file_ids, the last user message must be the built user_text (with file content)
                if file_ids and session["messages"] and session["messages"][-1].get("role") == "user":
                    session["messages"][-1] = {"role": "user", "content": user_text}

                # Cap session history to avoid unbounded memory growth
                max_messages = getattr(config, "MAX_SESSION_MESSAGES", 100)
                if len(session["messages"]) >= max_messages:
                    session["messages"] = session["messages"][-(max_messages - 2) :]

                if session["conversation_title"] == "New Chat" and user_text:
                    session["conversation_title"] = (user_text[:50] + "...") if len(user_text) > 50 else user_text

                asyncio.create_task(
                    _run_chat_stream(websocket, session, ws_id, model)
                )
            elif msg_type == "stop":
                if session.get("stop_event"):
                    session["stop_event"].set()
            elif msg_type == "load_conversation":
                pass
            elif msg_type == "folder_summary":
                fp = (data.get("folder_path") or "").strip()
                if not fp:
                    await _ws_send_json_safe(websocket, {"type": "error", "message": "Missing folder_path"})
                    continue
                try:
                    folder = _validate_folder_path(fp)
                except HTTPException as e:
                    await _ws_send_json_safe(websocket, {"type": "error", "message": e.detail})
                    continue
                rec = data.get("recursive", True)
                mod = (data.get("model") or "").strip() or None
                try:
                    async for info in iter_file_summaries(folder, recursive=rec, model=mod):
                        await _ws_send_json_safe(websocket, {"type": "folder_file", "name": info["name"], "summary": info["summary"], "error": info.get("error")})
                    await _ws_send_json_safe(websocket, {"type": "folder_done"})
                except Exception as e:
                    logger.exception("Folder summary error: %s", e)
                    await _ws_send_json_safe(websocket, {"type": "error", "message": str(e)})
            elif msg_type == "multi_file_summary":
                file_ids = data.get("file_ids") or []
                if not file_ids:
                    await _ws_send_json_safe(websocket, {"type": "error", "message": "Missing file_ids"})
                    continue
                items = []
                for fid in file_ids:
                    info = _get_upload(fid)
                    if not info:
                        await _ws_send_json_safe(websocket, {"type": "error", "message": "File not found"})
                        break
                    items.append(info)
                else:
                    mod = (data.get("model") or "").strip() or None
                    try:
                        async for info in iter_uploaded_file_summaries(items, model=mod):
                            await _ws_send_json_safe(websocket, {"type": "folder_file", "name": info["name"], "summary": info["summary"], "error": info.get("error")})
                        await _ws_send_json_safe(websocket, {"type": "folder_done"})
                    except Exception as e:
                        logger.exception("Multi-file summary error: %s", e)
                        await _ws_send_json_safe(websocket, {"type": "error", "message": str(e)})
            else:
                await _ws_send_json_safe(websocket, {"type": "error", "message": f"Unknown type: {msg_type}"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("WebSocket error: %s", e)
    finally:
        _sessions.pop(ws_id, None)


async def _run_chat_stream(
    websocket: WebSocket,
    session: dict[str, Any],
    ws_id: int,
    model: str | None,
) -> None:
    """Run streaming response in background so we can receive 'stop' on the same connection."""
    from ai_service import stream_response

    stop_event = threading.Event()
    session["stop_event"] = stop_event
    try:
        full_reply = []
        async for token in stream_response(
            session["messages"],
            model=model,
            ws_id=ws_id,
            stop_event=stop_event,
        ):
            full_reply.append(token)
            await _ws_send_json_safe(websocket, {"type": "token", "content": token})
        await _ws_send_json_safe(websocket, {"type": "done"})
        session["messages"].append({"role": "assistant", "content": "".join(full_reply)})
        if len(session["messages"]) > getattr(config, "MAX_SESSION_MESSAGES", 100):
            session["messages"] = session["messages"][-getattr(config, "MAX_SESSION_MESSAGES", 100) :]
    except Exception as e:
        err_msg = str(e) if str(e) else "Generation failed"
        logger.exception("Stream error: %s", e)
        await _ws_send_json_safe(websocket, {"type": "error", "message": err_msg})
        session["messages"].append({"role": "assistant", "content": f"Error: {err_msg}"})
    finally:
        session["stop_event"] = None


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
        await _ws_send_json_safe(websocket, {"type": "error", "message": f"Document summarization failed: {e}"})
        return None
    header = f"[File: {file_name} — summarized content below]\n"
    return f"{header}{combined}\n\nUser question: {user_message}"


async def _build_user_message_with_files(
    user_message: str,
    items: list[tuple[str, str]],
    websocket: WebSocket,
) -> str | None:
    """Build combined user message from multiple (name, text) items. Long files are summarized."""
    if len(items) == 1:
        return await _build_user_message_with_file(
            user_message, items[0][0], items[0][1], websocket
        )
    parts = []
    for file_name, file_text in items:
        one = await _build_user_message_with_file(
            "", file_name, file_text, websocket
        )
        if one is None:
            return None
        if "\n\nUser question:" in one:
            one = one.split("\n\nUser question:")[0].strip()
        parts.append(one)
    combined = "\n\n---\n\n".join(parts)
    if user_message:
        combined += f"\n\nUser question: {user_message}"
    return combined
