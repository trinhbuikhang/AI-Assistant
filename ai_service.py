"""Async streaming wrapper around Ollama. Used by the WebSocket handler."""

import asyncio
from typing import AsyncIterator

from app.core.ollama_client import (
    check_ollama_running,
    list_models,
    CHAT_TIMEOUT,
)
from app.core.text_chunker import chunk_text, word_count
from app.utils.config_manager import load_config
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Sync Ollama generate runs in a thread; we need to stream tokens to the async world.
# Use a queue: background thread puts tokens, async generator gets them.
import queue
import threading

MAX_FILE_WORDS = 6000


def _generate_sync_stream(
    model: str,
    messages: list[dict],
    token_queue: queue.Queue,
    stop_event: threading.Event,
    *,
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> None:
    """Run Ollama in a thread; put each token into token_queue. Put None when done, or {"error": msg} on error."""
    import json
    import requests
    from app.core.ollama_client import OLLAMA_BASE

    url = f"{OLLAMA_BASE}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    try:
        with requests.post(url, json=payload, stream=True, timeout=CHAT_TIMEOUT) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if stop_event.is_set():
                    token_queue.put(None)
                    return
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    piece = obj.get("message", {}).get("content", "") or ""
                    if piece:
                        token_queue.put(piece)
                except json.JSONDecodeError:
                    continue
        token_queue.put(None)
    except Exception as e:
        logger.exception("Ollama stream error: %s", e)
        token_queue.put({"error": str(e)})


def _generate_sync_full(
    model: str,
    messages: list[dict],
    *,
    temperature: float = 0.3,
    max_tokens: int = 500,
) -> str:
    """Blocking full response (for summarization)."""
    from app.core.ollama_client import generate_sync
    return generate_sync(model, messages, temperature=temperature, max_tokens=max_tokens, timeout=CHAT_TIMEOUT)


async def stream_response(
    messages: list[dict],
    model: str | None = None,
    ws_id: int | None = None,
) -> AsyncIterator[str]:
    """
    Async generator: stream LLM tokens. Uses system prompt from config.
    messages should already include the new user message.
    """
    cfg = load_config()
    if not model or not model.strip():
        model = cfg.get("default_model", "mixtral:8x7b") or "mixtral:8x7b"
    if not check_ollama_running():
        raise RuntimeError("Ollama is not running. Please start Ollama.")

    system_prompt = (cfg.get("system_prompt") or "").strip()
    if not system_prompt:
        system_prompt = "You are a helpful, concise, and intelligent AI assistant. Answer clearly and accurately. If you're unsure, say so."
    temperature = float(cfg.get("temperature", 0.7))
    max_tokens = int(cfg.get("max_tokens", 2048))

    messages_for_api = [{"role": "system", "content": system_prompt}]
    messages_for_api.extend([{"role": m["role"], "content": m["content"]} for m in messages])

    token_queue: queue.Queue = queue.Queue()
    stop_event = threading.Event()

    def run():
        _generate_sync_stream(
            model,
            messages_for_api,
            token_queue,
            stop_event,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    try:
        while True:
            try:
                # Non-blocking get with timeout so we can check asyncio
                item = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: token_queue.get(timeout=0.2),
                )
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue
            if item is None:
                break
            if isinstance(item, dict) and "error" in item:
                raise RuntimeError(item["error"])
            yield item
    finally:
        stop_event.set()


async def summarize_long_text(raw_text: str, model: str | None = None) -> str:
    """Chunk long text, summarize each chunk via Ollama, return combined summary. Runs sync calls in thread."""
    cfg = load_config()
    if not model or not model.strip():
        model = cfg.get("default_model", "mixtral:8x7b") or "mixtral:8x7b"
    chunks = chunk_text(raw_text, MAX_FILE_WORDS)
    if not chunks:
        return ""
    n = len(chunks)
    logger.info("Summarizing %d chunk(s)...", n)
    summaries = []
    for i, ch in enumerate(chunks):
        msg = [{"role": "user", "content": f"Summarize the following text concisely, preserving key information:\n\n{ch}"}]
        try:
            out = await asyncio.to_thread(
                _generate_sync_full,
                model,
                msg,
                temperature=0.3,
                max_tokens=500,
            )
            summaries.append(out.strip())
        except Exception as e:
            summaries.append(f"[Chunk {i+1} summary failed: {e}]")
    return "\n\n---\n\n".join(summaries)


def get_models() -> list[str]:
    """Return list of available Ollama model names."""
    try:
        return list_models()
    except Exception as e:
        logger.warning("list_models failed: %s", e)
        return []
