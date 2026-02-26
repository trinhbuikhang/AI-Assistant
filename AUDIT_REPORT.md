# 🔍 AUDIT REPORT — AI Assistant Codebase

## EXECUTIVE SUMMARY

The codebase is well-structured with clear separation between launcher, server, AI layer, and config. The most serious issues are **frontend XSS** (AI/LLM output rendered via `marked.parse()` into `innerHTML` without sanitization), **missing upload filename sanitization** (path traversal / malicious names), and **port fallback logic** that can return a port that’s already in use. Server correctly binds to 127.0.0.1 and uses logging; main gaps are WebSocket message limits, conversation history caps, temp file location vs config, and a few UX/error-handling improvements. Prioritize XSS, filename sanitization, and port handling, then add message/history limits and minor hardening.

---

## CRITICAL ISSUES 🔴 (must fix — security/crash risks)

### C1. XSS via unsanitized Markdown/HTML from AI
- **File:** `static/index.html` (lines 247, 353)
- **Problem:** AI response content is passed through `marked.parse()` and assigned to `contentEl.innerHTML` with no sanitization. A malicious or jailbroken model could return HTML/JS that runs in the user’s browser.
- **Risk:** Cross-site scripting (XSS), session theft, or arbitrary code execution in the browser.
- **Fix:** Sanitize HTML after markdown rendering (e.g. use DOMPurify: `DOMPurify.sanitize(marked.parse(content))`) before assigning to `innerHTML`. Add DOMPurify script and call it for both streaming-complete and non-streaming message rendering.

### C2. Upload filename not sanitized (path traversal / malicious names)
- **File:** `server.py` (lines 109–110)
- **Problem:** `name = file.filename or "file"` is used as-is. Filenames like `../../etc/passwd` or names containing `<script>` can be stored and sent to the client; client then uses `file.name` in `innerHTML` (line 531) without escaping.
- **Risk:** Path confusion in logs/storage; XSS in UI when displaying file names from server.
- **Fix:** (1) Backend: sanitize `name` — take basename only (e.g. `Path(name).name` or `os.path.basename`), strip path separators, and optionally restrict to safe character set. (2) Frontend: escape `displayName` when building chip HTML (use existing `escapeHtml()` for the display name).

### C3. Port fallback returns unusable port when all are busy
- **File:** `main.py` (lines 25–36)
- **Problem:** When every port in `PORT_FALLBACKS` fails to bind, `_find_free_port()` still returns `config.PORT_DEFAULT` (8000). Uvicorn then tries to bind to 8000 and fails with “Address already in use.”
- **Risk:** Confusing startup failure; no clear message that all configured ports are busy.
- **Fix:** If no port in the list binds, raise an exception (e.g. `RuntimeError`) or `sys.exit(1)` with a clear message instead of returning `PORT_DEFAULT`. In `main()`, catch that and print the message before exiting.

---

## MAJOR ISSUES 🟠 (should fix — bugs/performance)

### M1. Temp files not written to configured upload directory
- **File:** `server.py` (lines 121–126)
- **Problem:** Upload uses `tempfile.NamedTemporaryFile(delete=False, suffix=suffix)` with no `dir=` argument, so files go to the system temp directory. `config.py` defines `UPLOAD_TEMP_DIR = BASE_DIR / "uploads_temp"` and docs say temp files go there.
- **Risk:** Config is misleading; project temp dir is never used; possible permission or cleanup expectations mismatch.
- **Fix:** Create `config.UPLOAD_TEMP_DIR` if missing, then use `tempfile.NamedTemporaryFile(..., dir=str(config.UPLOAD_TEMP_DIR), delete=False, suffix=suffix)`.

### M2. WebSocket has no max message size
- **File:** `server.py` (line 163)
- **Problem:** `await websocket.receive_text()` accepts arbitrarily large messages. A client could send a huge payload and exhaust memory.
- **Risk:** DoS via memory exhaustion.
- **Fix:** Enforce a maximum text message size (e.g. 512 KB or 1 MB). Use `receive_bytes()` and check `len(data)` before decoding, or use Starlette’s WebSocket limits if available; reject with a clear error message when over limit.

### M3. No max length on user message content
- **File:** `server.py` (lines 173–176)
- **Problem:** User message is trimmed but not length-limited. Very long messages (e.g. 100k+ chars) can stress the LLM and memory.
- **Risk:** Performance degradation, possible OOM, poor UX.
- **Fix:** Add a config constant (e.g. `MAX_MESSAGE_LENGTH = 50000` in `config.py`) and reject messages exceeding it with a clear WebSocket error.

### M4. Conversation history unbounded in session
- **File:** `server.py` (lines 193–194, 212)
- **Problem:** `session["messages"]` is appended to without limit. Long sessions can accumulate thousands of messages and grow memory.
- **Risk:** Memory growth over time, slower LLM context.
- **Fix:** Cap history (e.g. keep last N messages or last N tokens). Add `MAX_SESSION_MESSAGES` (or similar) in config and trim `session["messages"]` before appending new ones (e.g. keep last 50 exchanges).

### M5. No check that Ollama is running at startup
- **File:** `main.py`, `server.py`
- **Problem:** App starts and opens the browser even if Ollama is not running. User only sees “Ollama is not running” when sending the first message.
- **Risk:** Poor first-run experience; no clear upfront requirement.
- **Fix:** Option A: In `main.py` after server is ready (or before opening browser), call `check_ollama_running()` and print a warning (or non-fatal message) if Ollama is down. Option B: Add a `/health` dependency that checks Ollama and returns 503 if down, and have the frontend show a banner when health reports Ollama down. Prefer at least a startup check + warning so the user knows before chatting.

### M6. Frontend file name in chip uses innerHTML without escape
- **File:** `static/index.html` (line 531)
- **Problem:** `chip.innerHTML = '📄 ' + displayName + ' ...'` — `displayName` comes from `file.name` (server response or local file). If server sends a name with HTML, it’s XSS.
- **Risk:** XSS when displaying attached file names (especially from server-supplied names).
- **Fix:** Use `escapeHtml(displayName)` (or equivalent) when building the chip HTML, e.g. `chip.innerHTML = '📄 ' + escapeHtml(displayName) + ' <button ...';`.

### M7. Duplicate `import os` in upload handler
- **File:** `server.py` (lines 6 and 123)
- **Problem:** `import os` appears at top level and again inside `upload()`.
- **Risk:** Redundant; minor style/consistency issue.
- **Fix:** Remove the inner `import os`; use the top-level import.

---

## MINOR ISSUES 🟡 (nice to fix — quality/polish)

### N1. requirements.txt versions not pinned
- **File:** `requirements.txt`
- **Problem:** Uses `>=` ranges (e.g. `fastapi>=0.110.0`). Builds at different times can get different versions and break.
- **Fix:** Pin exact versions (e.g. `fastapi==0.110.0`) or use a lock file; document in README.

### N2. Magic values in ollama_client.py
- **File:** `app/core/ollama_client.py` (lines 16–20)
- **Problem:** `OLLAMA_BASE`, `CHAT_TIMEOUT`, `OLLAMA_START_TIMEOUT` are hardcoded. Better in config for overrides.
- **Fix:** Move to `config.py` (or env) and import in `ollama_client`, or document as constants and add optional env overrides.

### N3. ai_service.py duplicates MAX_FILE_WORDS
- **File:** `ai_service.py` (line 22)
- **Problem:** `MAX_FILE_WORDS = 6000` duplicates config/chunker constant.
- **Fix:** Import from config or text_chunker (e.g. `from config import MAX_FILE_WORDS` or from chunker) and remove local constant.

### N4. WebSocket "load_conversation" does nothing
- **File:** `server.py` (lines 214–215)
- **Problem:** `elif msg_type == "load_conversation": pass` — no implementation; dead path.
- **Fix:** Either implement load from history_manager and send messages to client, or remove this branch and document that persistence is not yet wired.

### N5. No “Stop” generation button
- **File:** Frontend + backend
- **Problem:** User cannot cancel a streaming response. Backend has `stop_event` in ai_service but no WebSocket message to trigger it.
- **Risk:** UX only; user must wait for long generations to finish.
- **Fix:** Add a “Stop” message type; WebSocket handler sets a per-session “cancel” flag that stream_response checks (or pass a cancel future); frontend shows “Stop” while streaming and sends stop on click.

### N6. textarea not auto-focused on load
- **File:** `static/index.html`
- **Problem:** Input textarea does not receive focus on page load.
- **Fix:** After `connect(); updateSendButton(); ...` add `inputText.focus();` (or defer once so it doesn’t fight with browser restore).

### N7. ALLOWED_FOLDER_BASES empty allows any path
- **File:** `config.py` (line 22)
- **Problem:** Comment says “Empty = allow any absolute path.” If server were ever exposed beyond localhost, this could be a data-exposure risk.
- **Risk:** Low for localhost-only; medium if app is ever bound to 0.0.0.0.
- **Fix:** Document clearly in README and config; consider defaulting to a safe list (e.g. user home or a configured base) if you want to harden for future use.

### N8. 0-byte file upload
- **File:** `server.py` (upload)
- **Problem:** 0-byte files are allowed; extract_text may return "" and they’re stored. No explicit validation.
- **Fix:** Optionally reject 0-byte files with HTTP 400 and a clear message, or document that they are allowed and produce empty content.

---

## POSITIVE OBSERVATIONS ✅

- **Architecture:** Clear separation: `main.py` (launcher), `server.py` (HTTP/WS), `ai_service.py` (streaming), `config.py` (ports/paths/limits), `app/core/` (Ollama, file parsing, history, chunking). No circular imports detected.
- **Binding:** Server and launcher use `127.0.0.1` only; no `0.0.0.0` exposure.
- **Logging:** Python `logging` used in server and app modules; `setup_logger` with file + stderr; `logger.exception` in critical paths.
- **File types:** Upload restricted to whitelist `{".pdf", ".docx", ".txt", ".csv"}`; size limit via `UPLOAD_MAX_MB`.
- **Temp cleanup:** Upload handler deletes temp file in `finally` after extraction.
- **History manager:** Filename sanitization (`_sanitize_filename`) for saved conversation files; path traversal prevented for history paths.
- **Pydantic:** `FolderSummaryRequest` used for folder-summary API.
- **Async:** LLM streaming runs in thread with queue; async generator yields tokens; no blocking sync HTTP in async path without `to_thread`/`run_in_executor`.
- **Frontend:** Send button disabled when empty and when streaming; typing indicator; scroll-to-bottom with user-scroll detection; conversation title from first message; `escapeHtml` used for conversation title in sidebar.
- **Reconnection:** WebSocket uses limited retries with backoff (`RECONNECT_DELAYS`); not a tight loop.
- **Accessibility:** Sidebar toggle and buttons have `aria-label`; semantic structure.
- **README:** Setup, run, structure, API overview, and troubleshooting are documented.

---

## RECOMMENDED FIXES — PRIORITY ORDER

1. **C1 – XSS (marked + innerHTML)** — Add DOMPurify and sanitize all AI-rendered HTML before `innerHTML`. (Medium: ~30–45 min.)
2. **C2 – Filename sanitization** — Backend: basename + safe chars; frontend: `escapeHtml(displayName)` in file chips. (Easy.)
3. **C3 – Port fallback** — Raise/exit with clear message when no port in list is free. (Easy.)
4. **M1 – Upload temp dir** — Use `config.UPLOAD_TEMP_DIR` in `NamedTemporaryFile(..., dir=...)`. (Easy.)
5. **M2 – WebSocket max message size** — Enforce max size on `receive_text`/bytes and return error. (Medium.)
6. **M3 – Max message length** — Add `MAX_MESSAGE_LENGTH` and reject long messages. (Easy.)
7. **M4 – Session history cap** — Add `MAX_SESSION_MESSAGES` and trim before append. (Easy.)
8. **M5 – Ollama startup check** — Warning in main or health check; document in README. (Easy.)
9. **M6 – Escape file name in chips** — Use `escapeHtml(displayName)`. (Easy.)
10. **M7 – Remove duplicate `import os`** — Rely on top-level import. (Trivial.)
11. **N1 – Pin dependencies** — Pin versions in requirements.txt. (Easy.)
12. **N2–N4, N6–N8** — Config constants, remove dead branch, focus, document. (Various.)
13. **N5 – Stop generation** — Add cancel message and wire to `stop_event`. (Medium.)

---

## FIXED CODE

All CRITICAL and MAJOR issues have been fixed in the codebase. Summary of changes:

- **C1 (XSS):** `static/index.html` — Added DOMPurify script (CDN); introduced `safeMarkdown(text)` that runs `marked.parse()` then `DOMPurify.sanitize()`; all AI content rendered into `innerHTML` (streaming complete and non-streaming) now uses `safeMarkdown()`. Fallback to `escapeHtml()` if `marked` is missing.
- **C2 (Filename):** `server.py` — Upload handler now sanitizes filename with `os.path.basename(raw_name).lstrip(". ")` and uses a safe default when empty. `static/index.html` — File chip uses `escapeHtml(displayName)` when building innerHTML.
- **C3 (Port):** `main.py` — `_find_free_port()` raises `RuntimeError` with a clear message when no port in `PORT_FALLBACKS` is free; `main()` catches it and exits with that message.
- **M1 (Temp dir):** `server.py` — Creates `config.UPLOAD_TEMP_DIR` if needed and uses `tempfile.NamedTemporaryFile(..., dir=str(config.UPLOAD_TEMP_DIR))` for upload temp files.
- **M2 (WebSocket size):** `server.py` — WebSocket loop uses `websocket.receive()` instead of `receive_text()`; enforces `config.WS_MAX_MESSAGE_BYTES` (512 KB) on raw payload (bytes or encoded text) and sends a clear error when exceeded.
- **M3 (Message length):** `config.py` — Added `MAX_MESSAGE_LENGTH = 50000`. `server.py` — After building `user_text`, rejects with WebSocket error if length exceeds limit.
- **M4 (Session cap):** `config.py` — Added `MAX_SESSION_MESSAGES = 100`. `server.py` — Before appending a new user message, trims session to last `MAX_SESSION_MESSAGES - 2` when at cap; after appending assistant message, trims to last `MAX_SESSION_MESSAGES`.
- **M5 (Ollama check):** `main.py` — After server is ready and before opening browser, calls `check_ollama_running()` and prints a clear warning if Ollama is not running.
- **M6 (Escape file name):** `static/index.html` — In `renderFileChips()`, chip content uses `escapeHtml(displayName)`.
- **M7 (Duplicate import):** `server.py` — Removed the second `import os` from inside `upload()`; uses top-level `import os` only.

**Minor:** `static/index.html` — Added `inputText.focus()` on load for better accessibility (N6).
