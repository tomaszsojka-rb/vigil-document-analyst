"""
Document chunker for large document processing.

Splits documents into manageable chunks so the Indexer agent can process
200+ page documents without exceeding token budgets or losing quality
to "lost in the middle" degradation.

Small documents (< LARGE_DOC_THRESHOLD words) bypass chunking entirely
and use the fast single-call path.
"""

import logging
import os

logger = logging.getLogger("vigil.chunker")

# Documents above this word count use the chunked pipeline
LARGE_DOC_THRESHOLD = int(os.getenv("LARGE_DOC_THRESHOLD", "15000"))  # ~30 pages

# Each chunk size in words (~8 pages, ~5K tokens)
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "4000"))

# Word overlap between consecutive chunks to preserve context at boundaries
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))


def is_large(documents: list[dict]) -> bool:
    """Return True if any document exceeds the large-document threshold."""
    return any(
        len(doc.get("content", "").split()) > LARGE_DOC_THRESHOLD
        for doc in documents
    )


def chunk_document(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[dict]:
    """Split a document into overlapping word-boundary chunks.

    Returns a list of dicts: {"index": int, "content": str, "word_count": int}.
    Documents shorter than chunk_size are returned as a single chunk.
    """
    words = text.split()

    if len(words) <= chunk_size:
        return [{"index": 0, "content": text, "word_count": len(words)}]

    chunks: list[dict] = []
    start = 0

    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk_words = words[start:end]
        chunks.append({
            "index": len(chunks),
            "content": " ".join(chunk_words),
            "word_count": len(chunk_words),
        })
        if end >= len(words):
            break
        start += chunk_size - overlap

    logger.info(
        "Split %d words into %d chunks (size=%d, overlap=%d)",
        len(words), len(chunks), chunk_size, overlap,
    )
    return chunks
