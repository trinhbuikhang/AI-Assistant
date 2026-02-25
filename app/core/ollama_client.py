"""Ollama API client with streaming support. Uses threading so UI never freezes."""

import json
import subprocess
import sys
import threading
import time
from typing import Callable

import requests

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

OLLAMA_BASE = "http://localhost:11434"
# Chat/stream timeout: large models (e.g. mixtral:8x7b) can take minutes to start on CPU
CHAT_TIMEOUT = 300  # 5 minutes
# How long to wait for Ollama to become ready after we start it
OLLAMA_START_TIMEOUT = 45


def _user_friendly_error(exc: Exception) -> str:
    """Convert exception to a short, user-friendly message."""
    if isinstance(exc, requests.exceptions.Timeout):
        return "Request timed out. Try a smaller model (e.g. mistral:7b) or wait longer; the app timeout has been increased."
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "Could not connect to Ollama. Please check that Ollama is running."
    if isinstance(exc, requests.exceptions.HTTPError):
        return f"Ollama returned an error: {exc.response.status_code if exc.response else 'unknown'}."
    return "An error occurred while talking to Ollama. Please try again."


def check_ollama_running() -> bool:
    """Return True if Ollama is reachable."""
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        return r.status_code == 200
    except requests.RequestException as e:
        logger.debug("Ollama check failed: %s", e)
        return False


def start_ollama() -> subprocess.Popen | None:
    """
    Start Ollama server if not already running. Returns the process if we started it
    (caller should pass it to stop_ollama on app exit). Returns None if already running
    or if we failed to start (e.g. ollama not in PATH).
    """
    if check_ollama_running():
        return None
    try:
        kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.Popen(["ollama", "serve"], **kwargs)
    except FileNotFoundError:
        logger.warning("Ollama not found in PATH; cannot auto-start. Please start Ollama manually.")
        return None
    except Exception as e:
        logger.warning("Could not start Ollama: %s", e)
        return None
    # Wait for server to be ready
    for _ in range(OLLAMA_START_TIMEOUT):
        if proc.poll() is not None:
            logger.warning("Ollama process exited early.")
            return None
        time.sleep(1)
        if check_ollama_running():
            logger.info("Ollama started by app.")
            return proc
    logger.warning("Ollama did not become ready in time.")
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    return None


def stop_ollama(proc: subprocess.Popen | None) -> None:
    """Terminate Ollama process if we started it. Safe to call with None."""
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
        logger.info("Ollama stopped by app.")
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
    except Exception as e:
        logger.debug("Error stopping Ollama: %s", e)


def list_models() -> list[str]:
    """Fetch installed Ollama model names. Returns empty list on error."""
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        r.raise_for_status()
        data = r.json()
        models = data.get("models", [])
        return [m.get("name", "") for m in models if m.get("name")]
    except requests.RequestException as e:
        logger.warning("Failed to list Ollama models: %s", e)
        return []


def generate(
    model: str,
    messages: list[dict],
    *,
    stream: bool = True,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    on_token: Callable[[str], None] | None = None,
    on_done: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    stop_check: Callable[[], bool] | None = None,
) -> None:
    """
    Call Ollama chat API. If stream=True, calls on_token for each token and on_done with full response.
    Runs in a background thread; call from UI and connect to signals/slots.
    If stop_check() returns True, streaming stops and on_done is called with partial text (or on_error with "Cancelled").
    """
    url = f"{OLLAMA_BASE}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }

    def _run() -> None:
        try:
            if stream:
                full = []
                with requests.post(url, json=payload, stream=True, timeout=CHAT_TIMEOUT) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if stop_check and stop_check():
                            if on_error:
                                on_error("Cancelled")
                            return
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                            piece = obj.get("message", {}).get("content", "") or ""
                            if piece and on_token:
                                on_token(piece)
                            full.append(piece)
                        except json.JSONDecodeError:
                            continue
                text = "".join(full)
                if on_done:
                    on_done(text)
            else:
                if stop_check and stop_check():
                    if on_error:
                        on_error("Cancelled")
                    return
                r = requests.post(url, json=payload, timeout=CHAT_TIMEOUT)
                r.raise_for_status()
                data = r.json()
                text = data.get("message", {}).get("content", "") or ""
                if on_token:
                    on_token(text)
                if on_done:
                    on_done(text)
        except requests.RequestException as e:
            logger.exception("Ollama request failed: %s", e)
            if on_error:
                on_error(_user_friendly_error(e))
        except Exception as e:
            logger.exception("Ollama generate error: %s", e)
            if on_error:
                on_error(_user_friendly_error(e) if isinstance(e, requests.RequestException) else "An error occurred. Please try again.")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


def generate_sync(
    model: str,
    messages: list[dict],
    *,
    temperature: float = 0.3,
    max_tokens: int = 500,
    timeout: int = CHAT_TIMEOUT,
) -> str:
    """
    Blocking call to Ollama chat API (no streaming). Returns full response text.
    Used for summarization. Raises requests.RequestException on failure.
    """
    url = f"{OLLAMA_BASE}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    return data.get("message", {}).get("content", "") or ""
