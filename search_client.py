"""
Azure AI Search integration for Vigil – Document Analyst.

Provides two search indexes:
1. ``vigil-document-chunks`` — Raw document chunks for follow-up chat RAG.
2. ``vigil-facts`` — Structured facts, sections, and numbers extracted by the
   Indexer agent. Used to build focused context for the Analyzer agent,
   reducing prompt size and improving speed and reliability.

All functions are best-effort: if Search is not configured, they return empty
results and the app continues without RAG grounding.
"""

import json
import logging
import os

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient

logger = logging.getLogger("vigil.search_client")

_chunks_client: SearchClient | None = None
_facts_client: SearchClient | None = None

CHUNKS_INDEX = os.getenv("AZURE_SEARCH_CHUNKS_INDEX", "vigil-document-chunks")
FACTS_INDEX = os.getenv("AZURE_SEARCH_FACTS_INDEX", "vigil-facts")
SNIPPET_MAX_CHARS = int(os.getenv("SEARCH_SNIPPET_MAX_CHARS", "3000"))
FACTS_TOP_K = int(os.getenv("SEARCH_FACTS_TOP_K", "15"))


def _get_credential():
    """Return API key credential if set, otherwise DefaultAzureCredential."""
    api_key = os.getenv("AZURE_SEARCH_API_KEY", "")
    if api_key:
        from azure.core.credentials import AzureKeyCredential
        return AzureKeyCredential(api_key)
    return DefaultAzureCredential()


def _get_endpoint() -> str | None:
    """Return the Azure AI Search endpoint, or None if not configured."""
    return os.getenv("AZURE_SEARCH_ENDPOINT")


def _to_search_text(value) -> str:
    """Normalize model outputs to string fields accepted by Azure Search."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


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


# ─── Facts index (structured Indexer output for Analyzer RAG) ─


def ensure_facts_index() -> bool:
    """Create the facts index if it doesn't exist. Returns True if successful."""
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
            SearchableField(name="source_file", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="entry_type", type=SearchFieldDataType.String, filterable=True),
            SearchableField(name="category", type=SearchFieldDataType.String, filterable=True),
            SearchableField(name="label", type=SearchFieldDataType.String),
            SearchableField(name="value", type=SearchFieldDataType.String),
            SearchableField(name="section", type=SearchFieldDataType.String),
            SearchableField(name="content", type=SearchFieldDataType.String),
        ]

        semantic_config = SemanticConfiguration(
            name="facts-semantic",
            prioritized_fields=SemanticPrioritizedFields(
                content_fields=[SemanticField(field_name="content")],
                title_field=SemanticField(field_name="label"),
            ),
        )

        index = SearchIndex(
            name=FACTS_INDEX,
            fields=fields,
            semantic_search=SemanticSearch(configurations=[semantic_config]),
        )

        index_client.create_or_update_index(index)
        logger.info("Facts index '%s' ready", FACTS_INDEX)
        return True
    except Exception as exc:
        logger.warning("Failed to create facts index: %s", exc)
        return False


def _get_facts_client() -> SearchClient | None:
    """Return a SearchClient for the facts index. Returns None if Search is not configured."""
    global _facts_client
    if _facts_client is not None:
        return _facts_client

    endpoint = _get_endpoint()
    if not endpoint:
        return None

    _facts_client = SearchClient(
        endpoint=endpoint,
        index_name=FACTS_INDEX,
        credential=_get_credential(),
    )
    return _facts_client


def index_facts(indexer_output: dict, job_id: str) -> int:
    """Index structured facts, sections, and numbers from Indexer output. Returns count indexed."""
    client = _get_facts_client()
    if not client:
        return 0

    documents: list[dict] = []
    seq = 0

    for doc in indexer_output.get("documents", []):
        doc_id = _to_search_text(doc.get("doc_id", "unknown"))
        source_file = _to_search_text(doc.get("source_file", doc.get("title", "unknown")))

        # Index sections
        for section in doc.get("sections", []):
            seq += 1
            heading = _to_search_text(section.get("heading", ""))
            summary = _to_search_text(section.get("summary", ""))
            section_num = _to_search_text(section.get("section_number", ""))
            quote = _to_search_text(section.get("original_quote", ""))
            content = f"{heading} {section_num}: {summary}"
            if quote:
                content += f" | Quote: {quote[:500]}"
            documents.append({
                "id": f"{job_id}-{doc_id}-s{seq}",
                "job_id": job_id,
                "doc_id": doc_id,
                "source_file": source_file,
                "entry_type": "section",
                "category": "",
                "label": heading or section_num,
                "value": "",
                "section": section_num or heading,
                "content": content[:5000],
            })

        # Index facts
        for fact in doc.get("facts", []):
            seq += 1
            label = _to_search_text(fact.get("label", ""))
            value = _to_search_text(fact.get("value", ""))
            category = _to_search_text(fact.get("category", ""))
            section_ref = _to_search_text(fact.get("section", ""))
            quote = _to_search_text(fact.get("original_quote", ""))
            content = f"{category}: {label} = {value} (section: {section_ref})"
            if quote:
                content += f" | Quote: {quote[:300]}"
            documents.append({
                "id": f"{job_id}-{doc_id}-f{seq}",
                "job_id": job_id,
                "doc_id": doc_id,
                "source_file": source_file,
                "entry_type": "fact",
                "category": category,
                "label": label,
                "value": value,
                "section": section_ref,
                "content": content[:5000],
            })

        # Index number_registry entries
        for nr in doc.get("number_registry", []):
            seq += 1
            nr_value = _to_search_text(nr.get("value", ""))
            context = _to_search_text(nr.get("context", ""))
            section_ref = _to_search_text(nr.get("section", ""))
            quote = _to_search_text(nr.get("original_quote", ""))
            content = f"Number: {nr_value} — {context} (section: {section_ref})"
            if quote:
                content += f" | Quote: {quote[:300]}"
            documents.append({
                "id": f"{job_id}-{doc_id}-n{seq}",
                "job_id": job_id,
                "doc_id": doc_id,
                "source_file": source_file,
                "entry_type": "number",
                "category": "number",
                "label": context or nr_value,
                "value": nr_value,
                "section": section_ref,
                "content": content[:5000],
            })

    if not documents:
        return 0

    try:
        # Upload in batches of 1000 (Search limit)
        batch_size = 1000
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            client.upload_documents(documents=batch)
        logger.info("Indexed %d facts/sections/numbers for job=%s", len(documents), job_id)
        return len(documents)
    except Exception as exc:
        logger.warning("Failed to index facts: %s", exc)
        return 0


def search_facts(query: str, job_id: str, top: int | None = None, entry_type: str | None = None) -> list[dict]:
    """Semantic search over indexed facts. Returns relevant facts for Analyzer context."""
    client = _get_facts_client()
    if not client:
        return []

    if top is None:
        top = FACTS_TOP_K

    try:
        safe_job_id = "".join(c for c in (job_id or "") if c.isalnum() or c in "-_")
        filter_parts = [f"job_id eq '{safe_job_id}'"]
        if entry_type:
            safe_type = "".join(c for c in entry_type if c.isalnum() or c == "_")
            filter_parts.append(f"entry_type eq '{safe_type}'")
        filter_expr = " and ".join(filter_parts)

        search_kwargs: dict = {
            "search_text": query,
            "filter": filter_expr,
            "top": top,
            "select": ["source_file", "entry_type", "category", "label", "value", "section", "content"],
        }

        try:
            search_kwargs["query_type"] = "semantic"
            search_kwargs["semantic_configuration_name"] = "facts-semantic"
            results = list(client.search(**search_kwargs))
        except Exception:
            logger.debug("Semantic search unavailable for facts — falling back to keyword")
            del search_kwargs["query_type"]
            del search_kwargs["semantic_configuration_name"]
            results = list(client.search(**search_kwargs))

        return [
            {
                "source_file": r.get("source_file", ""),
                "entry_type": r.get("entry_type", ""),
                "category": r.get("category", ""),
                "label": r.get("label", ""),
                "value": r.get("value", ""),
                "section": r.get("section", ""),
                "content": r.get("content", ""),
                "score": r.get("@search.score", 0),
            }
            for r in results
        ]
    except Exception as exc:
        logger.warning("Facts search failed: %s", exc)
        return []


def build_analyzer_context(job_id: str, workflow: str, indexer_output: dict, custom_instructions: str = "") -> str:
    """Build focused Analyzer context by querying the facts index.

    Returns a text block with relevant facts/sections retrieved via semantic search,
    plus document metadata from the Indexer output. If Search is unavailable,
    returns empty string and the pipeline falls back to full Indexer JSON.
    """
    if not _get_endpoint():
        return ""

    # Build workflow-specific search queries
    workflow_queries = {
        "version_comparison": [
            "dates amounts prices fees totals penalties payment terms",
            "changes modifications additions removals clauses conditions",
            "parties obligations commitments deliverables",
        ],
        "compliance_check": [
            "requirements obligations compliance standards policies",
            "deviations missing clauses controls references",
            "amounts thresholds limits penalties",
        ],
        "document_pack": [
            "parties dates amounts obligations deliverables",
            "conflicts inconsistencies discrepancies gaps",
            "completeness missing information",
        ],
        "fact_extraction": [
            "amounts dates parties obligations thresholds percentages",
            "facts numbers values quantities identifiers",
            "discrepancies inconsistencies cross-check",
        ],
        "summary": [
            "key findings risks financial operational legal",
            "amounts dates obligations parties highlights",
            "critical items attention required",
        ],
    }

    queries = workflow_queries.get(workflow, workflow_queries["summary"])
    if custom_instructions:
        queries.append(custom_instructions[:200])

    # Retrieve facts for each query and deduplicate
    all_results: list[dict] = []
    seen_ids: set[str] = set()

    for q in queries:
        results = search_facts(q, job_id=job_id, top=FACTS_TOP_K)
        for r in results:
            result_id = f"{r['source_file']}:{r['entry_type']}:{r['label']}:{r['value']}"
            if result_id not in seen_ids:
                seen_ids.add(result_id)
                all_results.append(r)

    if not all_results:
        return ""

    # Build structured context text
    parts: list[str] = []

    # Group by document
    docs_data: dict[str, list[dict]] = {}
    for r in all_results:
        sf = r.get("source_file", "unknown")
        docs_data.setdefault(sf, []).append(r)

    for source_file, entries in docs_data.items():
        parts.append(f"\n--- Relevant extracted data from [{source_file}] ---")
        for e in entries:
            entry_type = e.get("entry_type", "")
            if entry_type == "section":
                parts.append(f"  Section [{e.get('section', '')}]: {e.get('content', '')}")
            elif entry_type == "fact":
                parts.append(f"  Fact [{e.get('category', '')}] {e.get('label', '')} = {e.get('value', '')} (section: {e.get('section', '')})")
            elif entry_type == "number":
                parts.append(f"  Number: {e.get('value', '')} — {e.get('label', '')} (section: {e.get('section', '')})")

    context = "\n".join(parts)
    logger.info("Built Analyzer context: %d entries, %d chars from facts index", len(all_results), len(context))
    return context
