"""Test script: load folder, extract text, ask Ollama to summarize. Reports timing for each step."""
import sys
import time
from pathlib import Path

# Ensure ai_assistant is on path
_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from app.core.file_parser import (
    collect_supported_files,
    EXTRACT_MAX_WORKERS,
    extract_text,
)
from app.core.ollama_client import check_ollama_running, generate_sync, CHAT_TIMEOUT

FOLDER = r"C:\Users\du\Desktop\PyDeveloper\AI\test_data\Investigation_Naggs_Initia"


def main():
    folder = Path(FOLDER)
    if not folder.is_dir():
        print(f"Folder not found: {folder}")
        return 1

    print("=" * 60)
    print("TEST: Load folder + summarize via Ollama")
    print("=" * 60)
    print(f"Folder: {folder}")
    print()

    # Step 1: Collect files (recursive)
    t0 = time.perf_counter()
    paths = collect_supported_files(folder, recursive=True)
    t_collect = time.perf_counter() - t0
    print(f"[1] Collect files (recursive): {len(paths)} files in {t_collect:.2f}s")

    if not paths:
        print("\nNo supported files (.pdf, .docx, .txt, .csv) in this folder.")
        print("Add some to test. Current app only reads these formats.")
        return 0

    # Step 2: Extract text (parallel like the app)
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def extract_one(p: Path) -> tuple[Path, str | None]:
        try:
            return (p, extract_text(p))
        except Exception as e:
            print(f"  Skip {p.name}: {e}")
            return (p, None)

    t1 = time.perf_counter()
    n = len(paths)
    workers = min(EXTRACT_MAX_WORKERS, n)
    results: list[tuple[Path, str | None] | None] = [None] * n
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_idx = {executor.submit(extract_one, p): i for i, p in enumerate(paths)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            results[idx] = future.result()
    parts = [f"[File: {r[0].name}]\n{r[1]}" for r in results if r is not None and r[1] is not None]
    t_extract = time.perf_counter() - t1
    print(f"[2] Extract text (parallel, {workers} workers): {len(parts)} files in {t_extract:.2f}s")

    if not parts:
        print("Could not read any file.")
        return 1

    combined = "\n\n---\n\n".join(parts)
    total_chars = len(combined)
    print(f"    Total chars: {total_chars}")
    print()

    # Step 3: Ollama summarize
    if not check_ollama_running():
        print("[3] Ollama is not running. Start Ollama and run again.")
        return 1

    # Use smallest model available for faster response (or first in list)
    import requests
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        models = [m.get("name", "") for m in r.json().get("models", []) if m.get("name")]
    except Exception as e:
        print(f"Failed to list models: {e}")
        return 1
    if not models:
        print("No models in Ollama. Run: ollama pull llama3.2")
        return 1
    # Prefer smaller/faster models for testing
    fast_models = [m for m in models if any(x in m.lower() for x in ("llama3.2", "mistral:7b", "phi", "gemma:2b", "qwen2:0.5b"))]
    model = fast_models[0] if fast_models else models[0]
    print(f"[3] Calling Ollama (model: {model})...")

    prompt = (
        "Summarize the following documents in a few short paragraphs. "
        "Focus on the main points and conclusions.\n\n"
        f"{combined[:12000]}"
    )
    if len(combined) > 12000:
        prompt += "\n\n[... document truncated for length ...]"

    t2 = time.perf_counter()
    try:
        summary = generate_sync(
            model,
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1024,
            timeout=CHAT_TIMEOUT,
        )
    except Exception as e:
        print(f"Ollama error: {e}")
        return 1
    t_ollama = time.perf_counter() - t2
    print(f"    Ollama responded in {t_ollama:.2f}s")
    print()

    # Summary
    print("=" * 60)
    print("SUMMARY (from model)")
    print("=" * 60)
    print(summary.strip())
    print()
    print("=" * 60)
    print("TIMING")
    print("=" * 60)
    print(f"  Collect files:  {t_collect:.2f}s")
    print(f"  Extract text:   {t_extract:.2f}s")
    print(f"  Ollama call:    {t_ollama:.2f}s")
    print(f"  TOTAL:          {t_collect + t_extract + t_ollama:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
