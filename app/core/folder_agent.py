"""Folder-level helper for per-file processing.

This module is designed for the *agent* / backend to handle a folder of
documents by processing **each file one-by-one**, instead of concatenating
all texts into a single huge prompt.

Motivation:
- Save context/window tokens by summarizing each file separately.
- Start returning useful results earlier (first files) without waiting for
  the entire folder to finish.

Typical usage (async):

    from pathlib import Path
    from app.core.folder_agent import iter_file_summaries

    async for info in iter_file_summaries(Path("C:/data/reports")):
        print(f"Summary for {info['path'].name}:")
        print(info['summary'])

The interface is an async generator so it can be easily wired to a WebSocket
or streaming HTTP endpoint in the future.
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator, Dict, Any

import asyncio

from app.core.file_parser import collect_supported_files, extract_text
from app.utils.logger import setup_logger
from ai_service import summarize_long_text

logger = setup_logger(__name__)


async def _extract_text_async(path: Path) -> str:
    """Run extract_text in a thread so callers remain async-friendly."""
    return await asyncio.to_thread(extract_text, path)


async def iter_file_summaries(
    folder: Path,
    *,
    recursive: bool = True,
    model: str | None = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Yield summaries for each supported file in a folder, one by one.

    Parameters
    ----------
    folder:
        Base folder containing documents.
    recursive:
        If True, scan subfolders. If False, only direct children.
    model:
        Optional explicit model name. If None, uses default from config.

    Yields
    ------
    dict with keys:
        - "path": Path          # absolute path to the file
        - "name": str           # file name only
        - "summary": str        # model summary (may be empty on error)
        - "error": str | None   # non-empty if something failed
    """
    folder = Path(folder)
    if not folder.is_dir():
        msg = f"Folder not found: {folder}"
        logger.warning(msg)
        yield {"path": folder, "name": folder.name, "summary": "", "error": msg}
        return

    paths = collect_supported_files(folder, recursive=recursive)
    if not paths:
        msg = "No supported files (.pdf, .docx, .txt, .csv) in this folder."
        logger.info("%s (%s)", msg, folder)
        yield {"path": folder, "name": folder.name, "summary": "", "error": msg}
        return

    logger.info(
        "Processing folder %s: %d file(s), recursive=%s",
        folder,
        len(paths),
        recursive,
    )

    for path in paths:
        file_error: str | None = None
        summary: str = ""

        try:
            text = await _extract_text_async(path)
        except Exception as e:  # pragma: no cover - defensive
            file_error = f"Failed to read file: {e}"
            logger.warning("%s (%s)", file_error, path)
            yield {
                "path": path,
                "name": path.name,
                "summary": "",
                "error": file_error,
            }
            continue

        try:
            # Use the same long-text summarization pipeline as uploads.
            summary = await summarize_long_text(text, model=model)
        except Exception as e:  # pragma: no cover - defensive
            file_error = f"Summarization failed: {e}"
            logger.warning("%s (%s)", file_error, path)

        yield {
            "path": path,
            "name": path.name,
            "summary": summary.strip(),
            "error": file_error,
        }


async def iter_uploaded_file_summaries(
    items: list[tuple[str, str]],
    model: str | None = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Yield summaries for each (name, text) — same shape as iter_file_summaries.
    Used when user uploads multiple files; logic matches per-file folder processing.
    """
    for name, text in items:
        file_error: str | None = None
        summary: str = ""
        try:
            summary = await summarize_long_text(text, model=model)
        except Exception as e:
            file_error = f"Summarization failed: {e}"
            logger.warning("%s (%s)", file_error, name)
        yield {"path": None, "name": name, "summary": summary.strip(), "error": file_error}

