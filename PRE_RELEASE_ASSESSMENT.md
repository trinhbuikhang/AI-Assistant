# Pre-Release Assessment — AI Assistant v1.0

**Assessor:** Senior product engineer / UX reviewer  
**Date:** 2026-02-26  
**Scope:** Local AI Assistant (FastAPI + single HTML, Ollama backend)

---

## PART 1 — RELEASE READINESS CHECKLIST

### Installation & First Run

| Item | Answer | Notes |
|------|--------|------|
| Can a non-technical user install and run in under 5 minutes? | **PARTIAL** | Yes if they follow README (venv + pip + python main.py), but “non-technical” may struggle with venv and “Start Ollama first.” |
| Clear README with step-by-step setup? | **YES** | Install, Run, Troubleshooting are clear; venv steps for Win/Mac/Linux. |
| All dependencies in requirements.txt with pinned versions? | **NO** | Uses `>=` (e.g. `fastapi>=0.110.0`). No pinned versions; risk of breakage on future releases. |
| App checks if Ollama is installed and running on startup? | **PARTIAL** | `check_ollama_running()` runs after server is ready; **only prints a warning to terminal**. No in-browser message; user may not see it. |
| App checks if at least one model is downloaded? | **NO** | No startup check. UI shows “(No models)” in dropdown but **does not tell user to run `ollama pull <model>`** in-app. |
| Single command start: `python main.py`? | **YES** | Starts server, finds port, opens browser. |
| Works on Windows, macOS, Linux without modification? | **YES** | Paths use `Path`, port bind to 127.0.0.1; no OS-specific code in main path. |
| All file paths relative (no hardcoded machine paths)? | **YES** | `config.py` uses `Path(__file__).resolve().parent`; `config_manager` uses same pattern. |

### Stability

| Item | Answer | Notes |
|------|--------|------|
| Tested on slow/low-RAM machine? | **UNKNOWN** | Not verifiable from codebase. |
| Recovers gracefully if Ollama crashes mid-conversation? | **PARTIAL** | Stream raises exception → server sends `type: error` and appends error to session; **no automatic reconnect or “Retry”**. |
| Handles being left open for hours? | **YES** | Session capped at `MAX_SESSION_MESSAGES`; upload store capped; no obvious leak. |
| Safe to close browser tab and reopen? | **PARTIAL** | **Reopen = new WebSocket = new session.** Previous messages are **lost** (sessions are in-memory, keyed by `ws_id`). |
| Ctrl+C shuts down cleanly? | **YES** | Main thread waits on `input()`; daemon server thread exits with process; no explicit cleanup of Ollama if app started it (main.py doesn’t start Ollama). |
| Port conflict handled? | **YES** | `_find_free_port()` tries 8000, 8001, 8002; clear error if none available. |

### Core Feature Completeness

| Item | Answer | Notes |
|------|--------|------|
| Chat works reliably with streaming? | **YES** | WebSocket streams tokens; `type: token` / `done`; typing indicator; markdown/code after done. |
| Conversation history persists across refresh? | **NO** | **Sessions are in-memory per WebSocket.** Refresh = new connection = empty chat. |
| Multiple conversations created and switched? | **NO** | Sidebar shows only **one** “Current” conversation (today). No list of past chats; no persistence. |
| Model change without restart? | **YES** | Dropdown in sidebar; selection sent per message; no restart. |
| File upload works and content sent to AI? | **YES** | `/upload` → file_id; chat payload includes file_id/file_ids; server builds user message with file text/summary. |
| New Chat clears context and starts fresh? | **YES** | Clear chat clears DOM and local state; new WebSocket connection gets new server session. |
| User can stop/cancel generation mid-stream? | **NO** | **No stop button.** Backend has `stop_event` in thread but **no WebSocket message type to trigger it**; UI has no “Stop” control. |

### Distribution Readiness

| Item | Answer | Notes |
|------|--------|------|
| .gitignore present (if sharing via git)? | **YES** | venv, __pycache__, .env, app.log, uploads_temp, chat_history, IDE, OS. |
| No sensitive data in codebase? | **YES** | No API keys; OLLAMA_BASE is localhost; config.json is local and gitignored if desired (not in .gitignore currently — consider adding). |
| Folder structure clean (no temp/debug/test)? | **PARTIAL** | `config.json`, `app.log` may be present; `test_folder_summary.py` in repo. Fine for dev; for zip distribution exclude logs/config or document. |
| Packaged as .exe / .app for non-Python users? | **NO** | README targets “run python main.py.” No PyInstaller/spec or similar. |
| App size reasonable? | **YES** | No model files in repo; dependencies are normal for stack. |

---

## PART 2 — USER EXPERIENCE FINAL PASS

### First Impression (first 10 seconds)

| Item | Answer | Notes |
|------|--------|------|
| Welcome screen inviting and self-explanatory? | **YES** | Greeting, “Powered by [model],” suggestion chips with clear labels. |
| User immediately understands what to do? | **YES** | Placeholder “Message...”, chips suggest actions, attach/folder hints. |
| App name/branding clear and consistent? | **YES** | “AI Assistant” in sidebar, header, title, welcome. |
| Feels fast and responsive on first load? | **YES** | Static HTML + CSS; WebSocket connect and /api/models are quick. |

### Core Interaction Loop

| Item | Answer | Notes |
|------|--------|------|
| Type → send → see response frictionless? | **YES** | Enter to send; send button; streaming into bubble. |
| Streaming text smooth and readable? | **YES** | Tokens append to one element; then full markdown render on `done`. |
| Code blocks formatted with syntax highlighting? | **YES** | highlight.js after render; `.copy-btn` on `pre`. |
| Markdown renders correctly? | **YES** | marked + DOMPurify; bold, lists, headers, links. |
| Chat scroll behavior natural? | **YES** | `scrollToBottom()` on token/done; `userScrolledUp` avoids fighting user. |

### Information Density

| Item | Answer | Notes |
|------|--------|------|
| Current model obvious? | **YES** | Header badge “model name” + sidebar dropdown. |
| “Thinking” vs done clear? | **YES** | Typing dots while streaming; spinner on send; dots removed on `done`. |
| How many conversations in sidebar clear? | **N/A** | Only one “conversation” (current) shown; no count. |
| Confusing UI element needing tooltip? | **PARTIAL** | “Or enter folder path” is clear; ⋯ on conversation might benefit “Clear chat.” |

### Empty / Edge States

| Item | Answer | Notes |
|------|--------|------|
| Empty sidebar looks intentional? | **PARTIAL** | When no messages, sidebar shows “Today” + one “Current” item with placeholder title; could look odd before first message. |
| Very long AI response: layout ok? | **YES** | `.message-content` flows; scroll on messagesWrap. |
| Very long user message: bubble ok? | **YES** | Same max-width 72%; wraps. |
| Unsupported file type: friendly error? | **PARTIAL** | **Upload (button):** server returns 400 with “Unsupported format. Use: .pdf, .docx, .txt, .csv” — good. **Drag-drop:** only allowed extensions are uploaded; **unsupported files are skipped with no message** — user may think nothing happened. |

---

## PART 3 — MISSING FEATURES ASSESSMENT

| Feature | Priority | Effort | Status |
|---------|----------|--------|--------|
| Export conversation (MD/PDF/TXT) | 🟠 High | Medium | **Missing** |
| Rename conversation (click to edit title) | 🟠 High | Easy | **Partial** (title auto-set from first message; no edit) |
| Delete individual conversation | 🟠 High | Easy | **N/A** (only one session shown) |
| Search conversation history | 🟡 Nice | Medium | **Missing** |
| Pin conversations to top | 🟡 Nice | Easy | **N/A** |
| Duplicate conversation | 🟡 Nice | Medium | **Missing** |
| **Stop/cancel generation button** | 🔴 **Must-have** | **Easy** | **Missing** (backend has stop_event; no WS + UI) |
| Regenerate last response | 🟠 High | Medium | **Missing** |
| Edit message and regenerate | 🟡 Nice | Medium | **Missing** |
| Copy individual message | 🟡 Nice | Easy | **Missing** |
| Copy code block button | ✅ | — | **Already exists** |
| System prompt / persona | ✅ | — | **Already exists** (Settings) |
| Temperature / creativity | ✅ | — | **Already exists** (Settings) |
| Context window indicator | 🟡 Nice | Hard | **Missing** |
| Drag and drop files onto chat | ✅ | — | **Already exists** |
| Preview uploaded file before send | 🟡 Nice | Medium | **Partial** (chips show name only) |
| Multiple file uploads in one message | ✅ | — | **Already exists** |
| Image upload (vision) | 🟡 Nice | Medium | **Missing** |
| Paste image from clipboard | 🟡 Nice | Medium | **Missing** |
| Prompt templates / quick prompts | ✅ | — | **Partial** (suggestion chips) |
| Keyboard shortcuts (Ctrl+N, Ctrl+K) | 🟠 High | Easy | **Missing** (Enter to send only) |
| Dark/light theme toggle | 🟡 Nice | Easy | **Missing** (dark only) |
| Font size adjustment | 🟡 Nice | Easy | **Missing** |
| Chat with specific document (RAG-lite) | 🟡 Nice | Medium | **Partial** (file attach) |
| Settings page (default model, Ollama URL, theme, etc.) | ✅ | — | **Exists** (modal: system prompt, temp, max tokens, default model) |
| Custom Ollama server URL | 🟠 High | Medium | **Missing** (hardcoded localhost:11434) |
| Model info on hover (params, context) | 🟡 Nice | Medium | **Missing** |
| Token count / response time per message | 🟡 Nice | Medium | **Missing** |
| Raw JSON view of conversation | 🟡 Nice | Easy | **Missing** |
| System prompt override per conversation | 🟡 Nice | Medium | **Missing** |
| API key for cloud models as fallback | 🟡 Nice | Hard | **Missing** |

---

## PART 4 — COMPETITIVE BASELINE CHECK

| Expectation | Status |
|-------------|--------|
| Markdown rendering in responses | ✅ Yes |
| Code syntax highlighting | ✅ Yes |
| Copy button on code blocks | ✅ Yes |
| **Stop generation button** | ❌ **No** — major gap |
| Conversation history sidebar | ⚠️ Partial (single “current” only; no persisted list) |
| New chat button | ✅ Yes |
| Model selector | ✅ Yes |
| Enter to send | ✅ Yes |
| Auto-focus on input when page loads | ✅ Yes (`inputText.focus()`) |
| Scroll to bottom on new message | ✅ Yes |
| Timestamp on messages | ❌ No |
| Clear user vs AI distinction | ✅ Yes (bubbles, alignment, avatar) |
| Responsive (window sizes) | ✅ Yes (mobile.css, sidebar toggle) |

---

## PART 5 — QUICK WIN IMPROVEMENTS

**[QUICK WIN #1]**  
**What:** Add a “Stop” button that appears while streaming and sends a stop signal to the server.  
**Why:** Users expect to cancel long or wrong generations; competitive baseline.  
**How:** In `index.html`: show a stop button (replace or beside send) when `streaming === true`; on click set a flag and send `{ type: "stop" }` over WebSocket. In `server.py`: handle `msg_type == "stop"` by setting a per-ws_id event that `stream_response` (or the thread) checks; ai_service already uses `stop_event`. Wire the same event from server to the generator.  
**Effort:** ~1–1.5 hrs  

**[QUICK WIN #2]**  
**What:** When Ollama is not running or models list is empty, show an in-browser banner or welcome message with next steps.  
**Why:** Terminal warning is easy to miss; in-app message reaches all users.  
**How:** Add a `/api/health/ollama` or extend `/api/models` to return `{ models: [], ollama_ok: bool }`. In frontend, if `!ollama_ok` or `models.length === 0`, show a dismissible banner: “Start Ollama and run: ollama pull &lt;model&gt;” with link to ollama.ai.  
**Effort:** ~45 min  

**[QUICK WIN #3]**  
**What:** Pin dependency versions in requirements.txt (e.g. fastapi==0.110.0, uvicorn==0.29.0).  
**Why:** Reproducible installs; fewer “works on my machine” issues.  
**How:** `pip freeze` from current venv (or pick last known-good versions) and replace `>=` with `==` in requirements.txt.  
**Effort:** ~15 min  

**[QUICK WIN #4]**  
**What:** When user drops only unsupported file types, show a toast: “Supported: .pdf, .docx, .txt, .csv”.  
**Why:** Avoids silent failure and confusion.  
**How:** In the drop handler, after filtering by `allowed`, if `list.length === 0` and `droppedFiles.length > 0`, call `showError('Supported formats: .pdf, .docx, .txt, .csv')`.  
**Effort:** ~15 min  

**[QUICK WIN #5]**  
**What:** Keyboard shortcut: Ctrl+N (or Cmd+N) for New Chat.  
**Why:** Power users expect it; matches common apps.  
**How:** `document.addEventListener('keydown', function(e) { if ((e.ctrlKey || e.metaKey) && e.key === 'n') { e.preventDefault(); clearChat(); } })`.  
**Effort:** ~15 min  

**[QUICK WIN #6]**  
**What:** Add a short timestamp (e.g. “2:34 PM”) to each message bubble.  
**Why:** Helps users see when something was said; expected in chat UIs.  
**How:** In `addMessage()`, append a `<span class="message-time">` with `new Date().toLocaleTimeString(...)`. Style small and muted in message-bubbles.css.  
**Effort:** ~30 min  

**[QUICK WIN #7]**  
**What:** After “(No models)” is loaded, set welcome sub text to “Install a model: run ollama pull &lt;model&gt; in terminal.”  
**Why:** In-app guidance without extra API.  
**How:** In `loadModels()` when `list.length === 0`, set `welcomeSub.textContent = 'Install a model: run ollama pull <model> in terminal.'` (and optionally show same in a small hint under model dropdown).  
**Effort:** ~15 min  

**[QUICK WIN #8]**  
**What:** Auto-focus input after sending a message (so user can type next message immediately).  
**Why:** Smoother flow; user doesn’t have to click back.  
**How:** In `sendMessage()` after `addMessage(…)` and clearing input, call `inputText.focus()`. On `done` handler, optionally focus input again.  
**Effort:** ~10 min  

**[QUICK WIN #9]**  
**What:** Add `config.json` to .gitignore (if not already) so local settings aren’t committed.  
**Why:** Avoid sharing personal system prompts/default model.  
**How:** Add `config.json` to .gitignore. Document in README that config is local.  
**Effort:** ~5 min  

**[QUICK WIN #10]**  
**What:** “Copy” for entire assistant message (not just code blocks).  
**Why:** Users often want to copy the full reply.  
**How:** Add a small copy icon/button on each assistant bubble (e.g. on hover); onclick copy `contentEl.innerText` or equivalent to clipboard and show “Copied!” briefly.  
**Effort:** ~30 min  

---

## PART 6 — RELEASE DECISION

### Verdict: **🟡 RELEASE WITH CAVEATS**

The app is **releasable** for a v1.0 “local AI assistant” if you **communicate limitations clearly**. It is not “not ready,” but missing a **stop button** and **persistent conversation history** will surprise users used to ChatGPT/Claude.

**Caveats to communicate (e.g. in README or release notes):**

1. **No stop button** — You cannot cancel a response once it’s generating; we’ll add it soon.
2. **Conversations don’t persist** — Closing the tab or refreshing clears the current chat; we don’t yet save history to disk.
3. **Single conversation** — The sidebar shows only the current chat; no list of past conversations yet.
4. **Ollama required** — Must be installed and running; if no models, run `ollama pull <model>` (document this clearly).

**Optional but recommended before calling it v1.0:** Implement **Quick Win #1 (Stop button)** so the competitive baseline is met.

---

### Release checklist (before sharing)

- [ ] Pin or document dependency versions (Quick Win #3).
- [ ] Add in-app hint when no models / Ollama not running (Quick Win #2 and/or #7).
- [ ] Add `config.json` to .gitignore if you don’t want to ship local config (Quick Win #9).
- [ ] README: state “No stop button yet” and “Conversations are not saved across refresh.”
- [ ] README: add “First time? Run `ollama pull llama3.2` (or another model) before using.”
- [ ] Test run: fresh venv, `pip install -r requirements.txt`, `python main.py`, send a message and refresh (confirm chat is empty).
- [ ] If packaging as zip: exclude `venv_web/`, `app.log`, `uploads_temp/`, `config.json` (or document that config is user-specific).

---

### Recommended post-release roadmap

**v1.1 (quick wins, 1–2 days)**  
- Stop generation button (Quick Win #1).  
- In-app Ollama/models guidance (Quick Win #2, #7).  
- Pinned requirements (Quick Win #3).  
- Unsupported file drop message (Quick Win #4).  
- Ctrl+N for new chat (Quick Win #5).  
- Message timestamps (Quick Win #6).  
- Copy full message (Quick Win #10).  

**v1.2 (medium, ~1 week)**  
- Persist conversations (e.g. localStorage or server-side with session id + file/DB).  
- Conversation list in sidebar (load/save/switch).  
- Rename/delete conversation.  
- Regenerate last response.  
- Custom Ollama URL in Settings.  

**v2.0 (future)**  
- Export conversation (Markdown/PDF).  
- Search in history.  
- Light/dark theme toggle.  
- Optional cloud API fallback (OpenAI/Anthropic/Groq) when Ollama unavailable.  

---

### Suggested elevator pitch (README or sharing)

**AI Assistant** is a **local, private chat app** that runs entirely on your machine. Point it at **Ollama** and use any model you’ve pulled—no accounts, no cloud. **One command** (`python main.py`) starts the server and opens the app in your browser: streaming chat, file and folder uploads, and a dark UI with Markdown and code highlighting. It’s for anyone who wants a **simple, offline-first** assistant without sending data to the cloud.

---

## PART 7 — IMPLEMENT APPROVED QUICK WINS

**No Quick Wins have been implemented in this assessment.**

After you decide which Quick Wins to approve, I will:

- Implement **one at a time**.
- Show the exact code change (diff-style).
- Explain what changed and confirm no other parts of the app are broken.
- Wait for your approval before moving to the next.

Tell me which number(s) you want (e.g. “Do #1 and #3”), and we’ll start with the first one.
