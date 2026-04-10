"""
Azure AI Search integration for Vigil – Document Analyst.

Provides chunk indexing and semantic search for the follow-up chat RAG pipeline.
When large documents (200+ pages) are processed, their chunks are indexed in the
``vigil-document-chunks`` index. Follow-up chat queries use semantic search over
these chunks to retrieve relevant original document sections.

All functions are best-effort: if Search is not configured, they return empty
results and the app continues without RAG grounding.
"""

import logging
import os

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient

logger = logging.getLogger("vigil.search_client")

_chunks_client: SearchClient | None = None

CHUNKS_INDEX = os.getenv("AZURE_SEARCH_CHUNKS_INDEX", "vigil-document-chunks")
SNIPPET_MAX_CHARS = int(os.getenv("SEARCH_SNIPPET_MAX_CHARS", "3000"))


def _get_credential():
    """Return DefaultAzureCredential for RBAC-based authentication (production-ready)."""
    return DefaultAzureCredential()


def _get_endpoint() -> str | None:
    """Return the Azure AI Search endpoint, or None if not configured."""
    return os.getenv("AZURE_SEARCH_ENDPOINT")


# ─── Chunk index management (for large document processing) ───


def ensure_chunks_index() -> bool:
    """Create the chunks index if it doesn't exist. Returns True if successful."""
    endpoint = _get_endpoint()
    if not endpoint:
        return False

    try:
        from azure.search.documents.indexes import SearchIndexClient
        from azure.search.documents.indexes.models import (
            SearchableField,
            SearchFieldDataType,
            SearchIndex,
            SemanticConfiguration,
            SemanticField,
            SemanticPrioritizedFields,
            SemanticSearch,
            SimpleField,
        )

        index_client = SearchIndexClient(endpoint=endpoint, credential=_get_credential())

        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(name="job_id", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="doc_id", type=SearchFieldDataType.String, filterable=True),
            SearchableField(name="filename", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="chunk_index", type=SearchFieldDataType.Int32, sortable=True),
            SearchableField(name="content", type=SearchFieldDataType.String),
            SimpleField(name="word_count", type=SearchFieldDataType.Int32),
        ]

        semantic_config = SemanticConfiguration(
            name="chunks-semantic",
            prioritized_fields=SemanticPrioritizedFields(
                content_fields=[SemanticField(field_name="content")],
            ),
        )

        index = SearchIndex(
            name=CHUNKS_INDEX,
            fields=fields,
            semantic_search=SemanticSearch(configurations=[semantic_config]),
        )

        index_client.create_or_update_index(index)
        logger.info("Chunks index '%s' ready", CHUNKS_INDEX)
        return True
    except Exception as exc:
        logger.warning("Failed to create chunks index: %s", exc)
        return False


def _get_chunks_client() -> SearchClient | None:
    """Return a SearchClient for the chunks index. Returns None if Search is not configured."""
    global _chunks_client
    if _chunks_client is not None:
        return _chunks_client

    endpoint = _get_endpoint()
    if not endpoint:
        return None

    _chunks_client = SearchClient(
        endpoint=endpoint,
        index_name=CHUNKS_INDEX,
        credential=_get_credential(),
    )
    return _chunks_client


def index_document_chunks(chunks: list[dict], job_id: str, doc_id: str, filename: str) -> None:
    """Upload document chunks to Search for follow-up chat RAG. Best-effort."""
    client = _get_chunks_client()
    if not client:
        return

    try:
        documents = [
            {
                "id": f"{job_id}-{doc_id}-{chunk['index']}",
                "job_id": job_id,
                "doc_id": doc_id,
                "filename": filename,
                "chunk_index": chunk["index"],
                "content": chunk["content"],
                "word_count": chunk["word_count"],
            }
            for chunk in chunks
        ]
        client.upload_documents(documents=documents)
        logger.info("Indexed %d chunks for '%s' (job=%s)", len(documents), filename, job_id)
    except Exception as exc:
        logger.warning("Failed to index chunks for '%s': %s", filename, exc)


def search_chunks(query: str, job_id: str | None = None, top: int = 5) -> list[dict]:
    """Semantic search over indexed chunks. Returns empty list if Search is unavailable."""
    client = _get_chunks_client()
    if not client:
        return []

    try:
        # Sanitize job_id to prevent OData injection
        safe_job_id = "".join(c for c in (job_id or "") if c.isalnum() or c in "-_")
        filter_expr = f"job_id eq '{safe_job_id}'" if safe_job_id else None
        search_kwargs: dict = {
            "search_text": query,
            "filter": filter_expr,
            "top": top,
            "select": ["filename", "chunk_index", "content"],
        }

        # Use semantic search if available
        try:
            search_kwargs["query_type"] = "semantic"
            search_kwargs["semantic_configuration_name"] = "chunks-semantic"
            results = list(client.search(**search_kwargs))
        except Exception:
            # Fall back to keyword search if semantic isn't available
            logger.debug("Semantic search unavailable — falling back to keyword search")
            del search_kwargs["query_type"]
            del search_kwargs["semantic_configuration_name"]
            results = list(client.search(**search_kwargs))

        return [
            {
                "filename": r.get("filename", ""),
                "chunk_index": r.get("chunk_index", 0),
                "content": (r.get("content") or "")[:SNIPPET_MAX_CHARS],
                "score": r.get("@search.score", 0),
            }
            for r in results
        ]
    except Exception as exc:
        logger.warning("Chunk search failed: %s", exc)
        return []
