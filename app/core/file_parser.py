"""Extract text from PDF, Word, txt, and CSV files."""

import csv
import os
from pathlib import Path

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt", ".csv")
EXTRACT_MAX_WORKERS = min(6, max(2, (os.cpu_count() or 4)))


def collect_supported_files(folder: Path, recursive: bool = False) -> list[Path]:
    """Return sorted list of supported files in folder. recursive=True includes subfolders."""
    if not recursive:
        return sorted(
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        )
    return sorted(
        p for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


try:
    import fitz  # pymupdf
except ImportError:
    fitz = None

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None


def extract_text(file_path: str | Path) -> str:
    """
    Extract full text from file. Supports .pdf, .docx, .txt, .csv.
    Raises ValueError with a user-friendly message on failure.
    """
    path = Path(file_path)
    if not path.exists():
        raise ValueError(f"File not found: {path.name}")

    suffix = path.suffix.lower()
    logger.info("Extracting: %s (%s)", path.name, suffix)

    if suffix == ".txt":
        out = _read_txt(path)
    elif suffix == ".csv":
        out = _read_csv(path)
    elif suffix == ".pdf":
        out = _read_pdf(path)
    elif suffix == ".docx":
        out = _read_docx(path)
    else:
        raise ValueError(f"Unsupported format: {suffix}. Use .pdf, .docx, .txt, or .csv.")
    logger.info("  -> %d chars", len(out))
    return out


def _read_txt(path: Path) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as e:
        raise ValueError(f"Could not read file: {e}") from e


def _read_csv(path: Path) -> str:
    try:
        rows = []
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                rows.append(" | ".join(row))
        return "\n".join(rows)
    except OSError as e:
        raise ValueError(f"Could not read file: {e}") from e


def _read_pdf(path: Path) -> str:
    if fitz is None:
        raise ValueError("PDF support requires pymupdf. Install with: pip install pymupdf")
    try:
        doc = fitz.open(path)
    except Exception as e:
        logger.warning("Could not open PDF %s: %s", path, e)
        raise ValueError(f"Could not open PDF: {e}") from e
    try:
        parts = []
        for page in doc:
            parts.append(page.get_text())
        text = "\n\n".join(parts)
        return text.strip() if text else ""
    except Exception as e:
        logger.warning("Could not read PDF %s: %s", path, e)
        raise ValueError(f"Could not read PDF: {e}") from e
    finally:
        doc.close()


def _read_docx(path: Path) -> str:
    if DocxDocument is None:
        raise ValueError("Word support requires python-docx. Install with: pip install python-docx")
    try:
        doc = DocxDocument(path)
        return "\n\n".join(p.text or "" for p in doc.paragraphs)
    except Exception as e:
        logger.warning("Could not read Word file %s: %s", path, e)
        raise ValueError(f"Could not read Word file: {e}") from e
