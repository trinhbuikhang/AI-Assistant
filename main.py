"""Launcher: start FastAPI server, wait until ready, open browser, keep running until Enter or Ctrl+C."""

import sys
import threading
import time
import webbrowser
from pathlib import Path

# Ensure app package is on path when run as script
_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import uvicorn

import config

# Import app after path is set
from server import app

_http_port: int | None = None
_server_thread: threading.Thread | None = None


def _find_free_port() -> int:
    """Return first port from config that is not in use."""
    import socket
    for port in config.PORT_FALLBACKS:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return config.PORT_DEFAULT


def _run_server(port: int) -> None:
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


def _wait_ready(port: int, timeout: float = 15.0) -> bool:
    try:
        import urllib.request
        url = f"http://127.0.0.1:{port}/health"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1) as r:
                    if r.status == 200:
                        return True
            except Exception:
                time.sleep(0.3)
        return False
    except Exception:
        return False


def main() -> None:
    global _http_port, _server_thread

    port = _find_free_port()
    _http_port = port
    url = f"http://127.0.0.1:{port}"

    print(f"Starting AI Assistant server on {url}")
    _server_thread = threading.Thread(target=_run_server, args=(port,), daemon=True)
    _server_thread.start()

    if not _wait_ready(port):
        print("Server did not become ready in time. Exiting.")
        sys.exit(1)

    print(f"Server ready. Opening browser at {url}")
    webbrowser.open(url)

    try:
        input("Server running. Press Enter to stop...\n")
    except (KeyboardInterrupt, EOFError):
        pass
    print("Shutting down.")


if __name__ == "__main__":
    main()
