"""
Agent 1 — Indexer & Fact Extractor
Uses direct chat completions via Azure AI Inference SDK for speed.
Registered in Foundry for portal visibility, but runtime calls use
single-shot chat completions instead of the Assistants API.

For large documents (200+ pages), uses a chunked processing path:
chunks are processed concurrently and fact sheets are merged with deduplication.
"""

import asyncio
import json
import logging
import os
import re
import time

from foundry_client import get_agents_client, get_indexer_model_name, get_inference_client

logger = logging.getLogger("vigil.agents.indexer")

INSTRUCTIONS = """\
You are the **Indexer** agent. Extract structured facts from documents into JSON.

For each document extract:
- Metadata: title, type, version, date, document_number, source_file (EXACT uploaded filename)
- document_overview: 2-3 sentence description
- sections: every section/article/clause with heading, section_number, summary (capture ALL key terms and values), original_quote (verbatim text)
- facts: category (date|amount|party|obligation|kpi|identifier|reference), label, value, section
- number_registry: EVERY number in the document — value, normalized_value, unit, context, section

The number_registry is CRITICAL — downstream agents use it for cross-document consistency checks.
Section summaries must be detailed enough for section-by-section comparison.

Return ONLY a JSON object (no markdown fences):
{
  "documents": [
    {
      "doc_id": "doc-1",
      "source_file": "exact_filename.pdf",
      "title": "...",
      "type": "contract|invoice|policy|sow|budget|specification|report|other",
      "version": "...",
      "date": "...",
      "document_number": "...",
      "document_overview": "2-3 sentence description",
      "sections": [
        {"heading": "...", "section_number": "...", "summary": "detailed summary with all values", "original_quote": "verbatim text"}
      ],
      "facts": [
        {"category": "date|amount|party|obligation|kpi|identifier", "label": "...", "value": "...", "section": "..."}
      ],
      "number_registry": [
        {"value": "exact number", "normalized_value": 0, "unit": "...", "context": "what it represents", "section": "..."}
      ]
    }
  ]
}

RULES:
- Extract only explicitly stated facts. Use exact values from the document.
- source_file MUST match the exact uploaded filename.
- Be exhaustive — it is better to extract too many facts than to miss any.
"""


AGENT_NAME = "vigil-indexer"
INDEXER_RETRY_ATTEMPTS = max(1, int(os.getenv("INDEXER_RETRY_ATTEMPTS", "2")))
INDEXER_CALL_RETRY_ATTEMPTS = max(1, int(os.getenv("INDEXER_CALL_RETRY_ATTEMPTS", "3")))
INDEXER_CALL_RETRY_BACKOFF_SECONDS = max(0.2, float(os.getenv("INDEXER_CALL_RETRY_BACKOFF_SECONDS", "2.0")))
FALLBACK_MAX_NUMBERS = max(20, int(os.getenv("INDEXER_FALLBACK_MAX_NUMBERS", "200")))
FALLBACK_QUOTE_MAX_CHARS = max(2000, int(os.getenv("INDEXER_FALLBACK_QUOTE_MAX_CHARS", "12000")))


def ensure_indexer_agent() -> str:
    """Find or create the Indexer agent in Foundry. Updates instructions if agent exists."""
    from agents import find_agent_by_name

    client = get_agents_client()
    model = get_indexer_model_name()
    existing_id = find_agent_by_name(AGENT_NAME)
    if existing_id:
        try:
            kwargs = dict(agent_id=existing_id, model=model, instructions=INSTRUCTIONS)
            try:
                client.update_agent(**kwargs, temperature=0.1)
            except Exception:
                client.update_agent(**kwargs)
            logger.info("Updated Foundry agent '%s' (model=%s): %s", AGENT_NAME, model, existing_id)
        except Exception as exc:
            logger.warning("Could not update agent '%s', using existing: %s", AGENT_NAME, exc)
        return existing_id

    try:
        agent = client.create_agent(model=model, name=AGENT_NAME, instructions=INSTRUCTIONS, temperature=0.1)
    except Exception:
        agent = client.create_agent(model=model, name=AGENT_NAME, instructions=INSTRUCTIONS)
    logger.info("Created Foundry agent '%s' (model=%s): %s", AGENT_NAME, model, agent.id)
    return agent.id


async def run_indexer(documents: list[dict], language: str = "en", custom_instructions: str = "") -> dict:
    """Run the Indexer on a list of parsed documents via direct chat completions."""
    # Build document text
    doc_text = ""
    for i, doc in enumerate(documents, 1):
        name = doc.get("filename", f"document-{i}")
        content = doc.get("content", "")
        doc_text += f"\n{'='*60}\nDOCUMENT {i}: {name}\n{'='*60}\n{content}\n"

    suffix = _build_lang_and_notes(language, custom_instructions)
    user_message = f"Extract and index the following documents:{suffix}\n{doc_text}"

    # Single chat completion call with retry + robust JSON parsing
    loop = asyncio.get_running_loop()
    parsed, text = await loop.run_in_executor(None, _call_and_parse_indexer_with_retries_sync, user_message)

    if parsed:
        if "documents" in parsed:
            return _ensure_all_confidence_scores(_normalize_indexer_documents(parsed, documents))
        normalized = _normalize_single_doc_result(parsed, 1, documents[0].get("filename", "document-1"))
        return _ensure_all_confidence_scores({"documents": [normalized], "raw_output": text})

    logger.warning("Indexer returned non-JSON. First 500 chars: %s", text[:500])
    fallback_documents = [
        _build_fallback_doc_result(i, doc.get("filename", f"document-{i}"), doc.get("content", ""))
        for i, doc in enumerate(documents, 1)
    ]
    return _ensure_all_confidence_scores({
        "documents": fallback_documents,
        "warning": "Indexer returned non-JSON; used deterministic fallback extraction",
    })


# ─── Chunked processing for large documents ───────────────────

MAX_CONCURRENT_CHUNKS = int(os.getenv("MAX_CONCURRENT_CHUNKS", "5"))


def _call_indexer_sync(user_message: str) -> str:
    """Synchronous chat completion call — runs in a thread-pool executor.

    Uses the Azure AI Inference SDK for a single HTTP call instead of the
    Agent Service's thread/message/run pattern (4-5 round-trips).
    """
    from azure.ai.inference.models import SystemMessage, UserMessage

    model = get_indexer_model_name()
    client = get_inference_client(model)

    call_kwargs = dict(
        messages=[
            SystemMessage(content=INSTRUCTIONS),
            UserMessage(content=user_message),
        ],
    )
    try:
        response = client.complete(**call_kwargs, temperature=0.1)
    except Exception:
        response = client.complete(**call_kwargs)

    return response.choices[0].message.content or ""


def _build_lang_and_notes(language: str, custom_instructions: str) -> str:
    """Build the language instruction + user notes suffix for Indexer prompts."""
    parts = ""
    if language == "pl":
        parts += (
            "\n\nIMPORTANT: All labels, summaries, and section headings in your output MUST be in Polish (polski). "
            "Keep JSON keys in English. Translate 'label', 'summary', and 'heading' values to Polish. "
            "However, the 'value' field in facts and the 'original_quote' fields MUST remain as the EXACT original text from the document — do NOT translate them."
        )
    if custom_instructions:
        parts += f"\n\nUSER'S SPECIFIC INSTRUCTIONS: {custom_instructions}"
    return parts


def _parse_indexer_json(text: str) -> dict | None:
    """Parse JSON from model output, handling fences, extra data, and truncation."""
    import re
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)

    start = stripped.find("{")
    if start < 0:
        return None

    end = stripped.rfind("}") + 1
    if end > start:
        try:
            return json.loads(stripped[start:end])
        except json.JSONDecodeError:
            pass

    # Find end of first complete JSON object
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(stripped)):
        c = stripped[i]
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(stripped[start:i + 1])
                except json.JSONDecodeError:
                    break

    # Truncation repair
    candidate = stripped[start:end] if end > start else stripped[start:]
    candidate = re.sub(r",\s*$", "", candidate)
    open_b = candidate.count("{") - candidate.count("}")
    open_sq = candidate.count("[") - candidate.count("]")
    candidate += "]" * max(0, open_sq)
    candidate += "}" * max(0, open_b)
    try:
        result = json.loads(candidate)
        logger.info("Indexer JSON repaired (closed %d braces, %d brackets)", open_b, open_sq)
        return result
    except json.JSONDecodeError:
        pass

    return None


def _call_and_parse_indexer_sync(user_message: str) -> tuple[dict | None, str]:
    """Call the Indexer model and parse JSON with targeted retries on malformed output."""
    last_text = ""

    for attempt in range(1, INDEXER_RETRY_ATTEMPTS + 1):
        attempt_message = user_message
        if attempt > 1:
            attempt_message += (
                "\n\nIMPORTANT RETRY INSTRUCTION: The previous response was not valid JSON. "
                "Return ONLY a single valid JSON object matching the required schema. "
                "Do not include markdown code fences, prose, or trailing text."
            )

        last_text = _call_indexer_sync(attempt_message)
        parsed = _parse_indexer_json(last_text)
        if parsed is not None:
            if attempt > 1:
                logger.info("Indexer JSON recovered on retry attempt %d", attempt)
            return parsed, last_text

        logger.warning("Indexer returned non-JSON on attempt %d/%d", attempt, INDEXER_RETRY_ATTEMPTS)

    return None, last_text


def _call_and_parse_indexer_with_retries_sync(user_message: str) -> tuple[dict | None, str]:
    """Call Indexer with retry on transport/runtime failures (timeouts, transient errors)."""
    last_exc: Exception | None = None

    for attempt in range(1, INDEXER_CALL_RETRY_ATTEMPTS + 1):
        try:
            return _call_and_parse_indexer_sync(user_message)
        except Exception as exc:
            last_exc = exc
            if attempt >= INDEXER_CALL_RETRY_ATTEMPTS:
                break
            delay = INDEXER_CALL_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "Indexer call failed on attempt %d/%d (%s). Retrying in %.1fs...",
                attempt, INDEXER_CALL_RETRY_ATTEMPTS, exc, delay,
            )
            time.sleep(delay)

    raise RuntimeError(
        f"Indexer call failed after {INDEXER_CALL_RETRY_ATTEMPTS} attempts: {last_exc}"
    ) from last_exc


def _normalize_single_doc_result(doc_result: dict, doc_idx: int, filename: str) -> dict:
    """Normalize a single Indexer document object to expected structural fields."""
    normalized = dict(doc_result or {})
    normalized["doc_id"] = f"doc-{doc_idx}"
    normalized["source_file"] = filename
    normalized.setdefault("title", filename)
    normalized.setdefault("type", "other")
    normalized.setdefault("sections", [])
    normalized.setdefault("facts", [])
    normalized.setdefault("number_registry", [])
    normalized.setdefault("document_overview", "")
    return normalized


def _normalize_indexer_documents(indexer_json: dict, input_documents: list[dict]) -> dict:
    """Normalize model-returned documents and bind them to canonical uploaded filenames."""
    docs = indexer_json.get("documents", [])
    normalized_docs: list[dict] = []

    for idx, source_doc in enumerate(input_documents, 1):
        filename = source_doc.get("filename", f"document-{idx}")
        doc_result = docs[idx - 1] if idx - 1 < len(docs) and isinstance(docs[idx - 1], dict) else {}
        normalized_docs.append(_normalize_single_doc_result(doc_result, idx, filename))

    # Preserve any extra model docs, but label them as extras to avoid silent data loss.
    for extra_idx in range(len(input_documents), len(docs)):
        extra = docs[extra_idx]
        if isinstance(extra, dict):
            normalized_docs.append(
                _normalize_single_doc_result(extra, extra_idx + 1, f"extra-document-{extra_idx + 1}")
            )

    return {**indexer_json, "documents": normalized_docs}


async def run_indexer_parallel(documents: list[dict], language: str = "en", custom_instructions: str = "") -> dict:
    """Process multiple documents concurrently via direct chat completions.

    Each document gets an independent chat completion call via the thread-pool executor,
    enabling true parallelism (up to MAX_CONCURRENT_CHUNKS concurrent calls).
    Large individual documents (>15K words) are auto-chunked internally.
    """
    from chunker import chunk_document, LARGE_DOC_THRESHOLD

    sem = asyncio.Semaphore(MAX_CONCURRENT_CHUNKS)
    suffix = _build_lang_and_notes(language, custom_instructions)

    async def _handle_doc(doc_idx: int, doc: dict) -> dict:
        content = doc.get("content", "")
        filename = doc.get("filename", f"document-{doc_idx}")
        word_count = len(content.split())

        if word_count > LARGE_DOC_THRESHOLD:
            # Large doc → chunk and process chunks concurrently
            chunks = chunk_document(content)
            logger.info("[parallel] Doc %d '%s': %d words → %d chunks", doc_idx, filename, word_count, len(chunks))
            tasks = [
                _process_single_chunk(sem, chunk, filename, doc_idx, len(chunks), language, custom_instructions)
                for chunk in chunks
            ]
            chunk_results = await asyncio.gather(*tasks, return_exceptions=True)
            valid = [r for r in chunk_results if not isinstance(r, Exception)]
            for i, r in enumerate(chunk_results):
                if isinstance(r, Exception):
                    logger.error("[parallel] Doc %d chunk %d failed: %s", doc_idx, i + 1, r)
            return _merge_chunk_facts(valid, doc_idx, filename)

        # Small/medium doc → single chat completion call
        async with sem:
            logger.info("[parallel] Doc %d '%s': %d words", doc_idx, filename, word_count)
            user_message = (
                f"Extract and index the following document:{suffix}\n\n"
                f"{'=' * 60}\nDOCUMENT {doc_idx}: {filename}\n{'=' * 60}\n{content}"
            )
            loop = asyncio.get_running_loop()
            try:
                parsed, text = await loop.run_in_executor(None, _call_and_parse_indexer_with_retries_sync, user_message)
                if parsed:
                    if "documents" in parsed and parsed["documents"]:
                        doc_result = _normalize_single_doc_result(parsed["documents"][0], doc_idx, filename)
                        return doc_result
                    return _normalize_single_doc_result(parsed, doc_idx, filename)

                logger.warning("[parallel] Doc %d '%s' returned non-JSON after retries", doc_idx, filename)
                return _build_fallback_doc_result(doc_idx, filename, content)
            except Exception as exc:
                logger.error(
                    "[parallel] Doc %d '%s' failed after retries, using fallback: %s",
                    doc_idx, filename, exc,
                )
                return _build_fallback_doc_result(doc_idx, filename, content)

    tasks = [_handle_doc(i, doc) for i, doc in enumerate(documents, 1)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_docs = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("[parallel] Document %d failed: %s", i + 1, result)
        elif isinstance(result, dict):
            all_docs.append(result)

    if not all_docs:
        return {"documents": [], "error": "All documents failed during parallel indexing"}

    return _ensure_all_confidence_scores({"documents": all_docs})


async def run_indexer_chunked(documents: list[dict], language: str = "en", custom_instructions: str = "") -> dict:
    """Process large documents by chunking, extracting facts concurrently, and merging results."""
    from chunker import chunk_document

    sem = asyncio.Semaphore(MAX_CONCURRENT_CHUNKS)

    all_doc_results = []

    for doc_idx, doc in enumerate(documents, 1):
        content = doc.get("content", "")
        filename = doc.get("filename", f"document-{doc_idx}")
        chunks = chunk_document(content)
        total_chunks = len(chunks)

        logger.info("[chunked] Processing '%s': %d words → %d chunks", filename, len(content.split()), total_chunks)

        tasks = [
            _process_single_chunk(sem, chunk, filename, doc_idx, total_chunks, language, custom_instructions)
            for chunk in chunks
        ]
        chunk_results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_results = []
        for i, result in enumerate(chunk_results):
            if isinstance(result, Exception):
                logger.error("[chunked] Chunk %d/%d of '%s' failed: %s", i + 1, total_chunks, filename, result)
            else:
                valid_results.append(result)

        merged = _merge_chunk_facts(valid_results, doc_idx, filename)
        all_doc_results.append(merged)

    return _ensure_all_confidence_scores({"documents": all_doc_results})


async def _process_single_chunk(sem, chunk, filename, doc_idx, total_chunks, language, custom_instructions):
    """Extract facts from a single document chunk via direct chat completions."""
    async with sem:
        lang_instruction = ""
        if language == "pl":
            lang_instruction = (
                "\n\nIMPORTANT: All labels, summaries, and section headings in your output "
                "MUST be in Polish (polski). Keep JSON keys in English. Translate 'label', 'summary', and 'heading' values to Polish. "
                "However, the 'value' field in facts and the 'original_quote' fields MUST remain as the EXACT original text from the document — do NOT translate them."
            )

        user_note = ""
        if custom_instructions:
            user_note = f"\n\nUSER'S SPECIFIC INSTRUCTIONS: {custom_instructions}"

        user_message = (
            f"Extract and index the following CHUNK ({chunk['index'] + 1} of {total_chunks}) "
            f"of document '{filename}'.{lang_instruction}{user_note}\n\n"
            f"{'=' * 60}\nCHUNK {chunk['index'] + 1}/{total_chunks}: {filename}\n{'=' * 60}\n{chunk['content']}"
        )

        loop = asyncio.get_running_loop()
        try:
            parsed, text = await loop.run_in_executor(None, _call_and_parse_indexer_with_retries_sync, user_message)
            if parsed:
                if "documents" in parsed:
                    normalized = []
                    for i, raw_doc in enumerate(parsed.get("documents", []), 1):
                        if isinstance(raw_doc, dict):
                            normalized.append(_normalize_single_doc_result(raw_doc, doc_idx, filename))
                    return {**parsed, "documents": normalized}
                return {"documents": [_normalize_single_doc_result(parsed, doc_idx, filename)]}

            logger.warning("[chunked] Chunk %d returned non-JSON after retries", chunk["index"] + 1)
            fallback_doc = _build_fallback_doc_result(
                doc_idx,
                filename,
                chunk.get("content", ""),
                doc_id=f"doc-{doc_idx}-chunk-{chunk['index'] + 1}",
            )
            fallback_doc["document_overview"] = (
                f"Fallback extraction for chunk {chunk['index'] + 1}/{total_chunks} due to malformed model output."
            )
            return {"documents": [fallback_doc], "raw_output": text}
        except Exception as exc:
            logger.error(
                "[chunked] Chunk %d/%d of '%s' failed after retries, using fallback: %s",
                chunk["index"] + 1, total_chunks, filename, exc,
            )
            fallback_doc = _build_fallback_doc_result(
                doc_idx,
                filename,
                chunk.get("content", ""),
                doc_id=f"doc-{doc_idx}-chunk-{chunk['index'] + 1}",
            )
            fallback_doc["document_overview"] = (
                f"Fallback extraction for chunk {chunk['index'] + 1}/{total_chunks} due to model call failure."
            )
            return {"documents": [fallback_doc]}


def _merge_chunk_facts(chunk_results: list[dict], doc_idx: int, filename: str) -> dict:
    """Merge fact sheets from multiple chunks into one unified document fact sheet."""
    merged: dict = {
        "doc_id": f"doc-{doc_idx}",
        "source_file": filename,
        "title": "",
        "type": "other",
        "version": "",
        "author": "",
        "date": "",
        "document_overview": "",
        "sections": [],
        "facts": [],
        "number_registry": [],
    }

    seen_facts: set[tuple] = set()
    seen_numbers: set[tuple] = set()

    for result in chunk_results:
        for doc in result.get("documents", []):
            # Take metadata from the first chunk that provides it
            if not merged["title"] and doc.get("title"):
                merged["title"] = doc["title"]
                merged["type"] = doc.get("type", "other")
                merged["version"] = doc.get("version", "")
                merged["author"] = doc.get("author", "")
                merged["date"] = doc.get("date", "")
            if not merged["document_overview"] and doc.get("document_overview"):
                merged["document_overview"] = doc["document_overview"]

            # Accumulate sections (different chunks → different sections)
            merged["sections"].extend(doc.get("sections", []))

            # Deduplicate facts by (category, label, value)
            for fact in doc.get("facts", []):
                key = (
                    fact.get("category", ""),
                    fact.get("label", "").lower().strip(),
                    fact.get("value", "").lower().strip(),
                )
                if key not in seen_facts:
                    seen_facts.add(key)
                    merged["facts"].append(fact)

            # Deduplicate number_registry by (value, context)
            for nr in doc.get("number_registry", []):
                key = (
                    str(nr.get("value", "")).lower().strip(),
                    nr.get("context", "").lower().strip(),
                )
                if key not in seen_numbers:
                    seen_numbers.add(key)
                    merged["number_registry"].append(nr)

    if not merged["title"]:
        merged["title"] = filename

    logger.info(
        "[chunked] Merged '%s': %d sections, %d unique facts",
        merged["title"], len(merged["sections"]), len(merged["facts"]),
    )
    _ensure_confidence_scores(merged)
    return merged


def _build_fallback_doc_result(doc_idx: int, filename: str, content: str, doc_id: str | None = None) -> dict:
    """Build a deterministic fallback doc result when model JSON extraction fails."""
    normalized_content = content or ""
    excerpt = " ".join(normalized_content.strip().split())
    excerpt = excerpt[:450] + ("..." if len(excerpt) > 450 else "")

    numbers = _extract_number_registry_from_text(normalized_content, max_items=FALLBACK_MAX_NUMBERS)
    facts = [
        {
            "category": "number",
            "label": n.get("context", "Detected numeric value")[:120],
            "value": n.get("value", ""),
            "section": n.get("section", "Extracted text"),
            "original_quote": n.get("original_quote", ""),
            "confidence": 0.45,
        }
        for n in numbers[:120]
    ]

    quote = normalized_content[:FALLBACK_QUOTE_MAX_CHARS]
    return {
        "doc_id": doc_id or f"doc-{doc_idx}",
        "source_file": filename,
        "title": filename,
        "type": "other",
        "version": "",
        "author": "",
        "date": "",
        "document_overview": (
            "Fallback deterministic extraction was used because the model response was malformed. "
            "Review source quotes for validation."
        ),
        "sections": [
            {
                "section_number": "1",
                "heading": "Extracted text snapshot",
                "summary": excerpt or "No extractable text content.",
                "original_quote": quote,
            }
        ],
        "facts": facts,
        "number_registry": numbers,
    }


def _extract_number_registry_from_text(text: str, max_items: int = 200) -> list[dict]:
    """Deterministically extract numeric evidence from raw text for fallback mode."""
    if not text:
        return []

    # Matches integers/decimals with optional thousands separators and optional trailing %.
    number_pattern = re.compile(r"(?<![\w-])(\d{1,3}(?:[\s\u00A0.,']\d{3})*(?:[.,]\d+)?%?|\d+(?:[.,]\d+)?%?)(?![\w-])")
    unit_pattern = re.compile(r"^(mg|g|kg|mcg|ml|l|cm|mm|%|pln|eur|usd|gbp|days?|months?|years?)$", re.IGNORECASE)

    registry: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for match in number_pattern.finditer(text):
        raw = match.group(1).strip()
        if not raw:
            continue

        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        if line_end == -1:
            line_end = len(text)
        line_text = " ".join(text[line_start:line_end].split())

        snippet_start = max(0, match.start() - 50)
        snippet_end = min(len(text), match.end() + 50)
        snippet = " ".join(text[snippet_start:snippet_end].split())

        key = (raw.lower(), line_text.lower())
        if key in seen:
            continue
        seen.add(key)

        tail = text[match.end(): min(len(text), match.end() + 12)].strip().split()
        unit = "%" if raw.endswith("%") else ""
        if not unit and tail:
            candidate = re.sub(r"[^a-zA-Z%]", "", tail[0])
            if unit_pattern.match(candidate):
                unit = candidate.lower()

        registry.append({
            "value": raw,
            "unit": unit,
            "context": line_text[:200] if line_text else snippet[:200],
            "section": "Extracted text",
            "original_quote": snippet[:260],
            "confidence": 0.4,
        })

        if len(registry) >= max_items:
            break

    return registry


# ─── Confidence scoring post-processing ───────────────────────

def _ensure_confidence_scores(doc_result: dict) -> None:
    """Ensure all facts have confidence scores and compute extraction_confidence summary.

    If the model didn't return confidence scores (e.g. older prompts, chunked merge),
    defaults are assigned based on whether an original_quote is present.
    """
    facts = doc_result.get("facts", [])
    scores = []

    for fact in facts:
        if "confidence" not in fact or not isinstance(fact.get("confidence"), (int, float)):
            # Default: high confidence if we have an original_quote, medium otherwise
            fact["confidence"] = 0.85 if fact.get("original_quote") else 0.6
        # Clamp to [0, 1]
        fact["confidence"] = max(0.0, min(1.0, float(fact["confidence"])))
        scores.append(fact["confidence"])

    # Build or update extraction_confidence summary
    if "extraction_confidence" not in doc_result:
        avg = sum(scores) / len(scores) if scores else 0.0
        doc_result["extraction_confidence"] = {
            "overall": round(avg, 2),
            "text_quality": "HIGH" if avg >= 0.8 else ("MEDIUM" if avg >= 0.5 else "LOW"),
            "notes": "",
        }
    else:
        ec = doc_result["extraction_confidence"]
        if not isinstance(ec.get("overall"), (int, float)):
            avg = sum(scores) / len(scores) if scores else 0.0
            ec["overall"] = round(avg, 2)
        if ec.get("text_quality") not in ("HIGH", "MEDIUM", "LOW"):
            ec["text_quality"] = "HIGH" if ec["overall"] >= 0.8 else ("MEDIUM" if ec["overall"] >= 0.5 else "LOW")


def _ensure_all_confidence_scores(indexer_result: dict) -> dict:
    """Apply confidence scoring to all documents in an Indexer result."""
    for doc in indexer_result.get("documents", []):
        _ensure_confidence_scores(doc)
    return indexer_result
