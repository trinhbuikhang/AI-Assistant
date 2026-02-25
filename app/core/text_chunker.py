"""Chunk long documents and optionally summarize chunks before combining."""

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

MAX_WORDS_PER_CHUNK = 6000


def word_count(text: str) -> int:
    """Approximate word count (split on whitespace)."""
    return len(text.split()) if text else 0


def chunk_text(text: str, max_words: int = MAX_WORDS_PER_CHUNK) -> list[str]:
    """Split text into chunks of at most max_words. Tries to break on paragraph boundaries."""
    if not text or word_count(text) <= max_words:
        return [text] if text else []

    chunks = []
    words = text.split()
    current = []
    current_count = 0

    for w in words:
        current.append(w)
        current_count += 1
        if current_count >= max_words:
            chunks.append(" ".join(current))
            current = []
            current_count = 0
    if current:
        chunks.append(" ".join(current))

    return chunks
