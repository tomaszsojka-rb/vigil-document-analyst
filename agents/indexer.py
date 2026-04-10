"""
Agent 1 — Indexer & Fact Extractor
Registered as a Foundry agent via Azure AI Agent Service SDK.
Parses uploaded documents, extracts key facts, and produces a structured fact sheet.

For large documents (200+ pages), uses a chunked processing path:
chunks are processed concurrently and fact sheets are merged with deduplication.
"""

import asyncio
import json
import logging
import os

from azure.ai.agents.models import ListSortOrder

from foundry_client import get_agents_client, get_indexer_model_name, run_with_retry

logger = logging.getLogger("vigil.agents.indexer")

INSTRUCTIONS = """\
You are the **Indexer & Fact Extractor** agent, the first stage in a document analysis pipeline.

You receive the raw text content of one or more documents. Your job is to produce \
a comprehensive, structured fact sheet that captures EVERYTHING in the document so that \
downstream agents can perform comparison, compliance, and gap analysis without access \
to the original text. Err on the side of extracting MORE rather than less.

## 1. IDENTIFY EACH DOCUMENT
Determine the document's type from its content. Common types include:
  - **Contracts**: MSA, SOW, amendment, side letter, NDA/CDA, service agreement, lease, licensing
  - **Financial**: invoice, credit note, purchase order, budget, cost estimate, financial report
  - **Regulatory / Compliance**: filings, audit reports, certifications, policy documents
  - **Technical**: specifications, protocols, test reports, design documents, SOPs
  - **Commercial**: supply agreement, distribution agreement, proposals, quotations
  - **HR & Corporate**: policy, employee agreement, benefits summary, org chart, memo
  - **Other**: risk register, project plan, meeting minutes, correspondence
Extract: title, version/revision, author, effective date, document number/ID, and any \
other identifying metadata.

## 2. EXTRACT EVERY NUMBER AND DATA POINT
This is your HIGHEST PRIORITY. Downstream agents depend on a COMPLETE inventory of every \
quantitative value in the document. For EACH number you find, record:
  - The exact value (preserve original formatting, currency, units)
  - The context: what does this number represent?
  - The section/clause where it appears
  - The verbatim quote containing it

Types of numerical data to capture — miss NOTHING:
  - **Monetary values**: prices, fees, totals, subtotals, taxes, discounts, royalties, \
penalties, unit prices, line item amounts, budgets, caps, milestone payments, hourly rates, \
annual values, monthly values
  - **Dates and deadlines**: effective dates, expiration dates, due dates, milestones, \
notice periods ("30 days"), renewal periods, payment terms (Net 30, Net 60). \
IMPORTANT: dates may appear in non-standard formats — handwritten, stamped, with extra spaces \
(e.g. "2017 -11- 15"), different separators (dots, slashes, dashes), or regional formats \
(DD.MM.YYYY, YYYY-MM-DD, Month DD YYYY, etc.). Normalize all dates to a readable format \
in the `value` field but keep the exact original text in `original_quote`. Also look for \
dates in headers, footers, stamps, and metadata fields (e.g. "Data obowiązywania", \
"Effective date", "Issue date", "Revision date").
  - **Quantities**: item counts, units, volumes, headcounts, page counts, hours, FTEs
  - **Percentages**: tax rates, discount rates, markup, margin, escalation rates, \
interest rates, SLA targets, penalties (% per day)
  - **Thresholds and limits**: caps, minimums, maximums, ceilings, floors, not-to-exceed values
  - **Identifiers with numbers**: invoice numbers, PO numbers, contract IDs, version numbers

For financial documents (invoices, POs, budgets): extract EVERY line item with description, \
quantity, unit price, line total, tax, and any applied discounts. Also extract subtotals, \
tax totals, and grand totals. Verify that line item totals are arithmetically consistent.

## 3. EXTRACT ALL OTHER KEY FACTS
  - **Parties and identifiers**: company names, addresses, tax IDs, registration numbers, \
contacts, signatories, roles
  - **Obligations and commitments**: deliverables, SLAs, service levels, warranties, \
payment terms, performance requirements, acceptance criteria
  - **Definitions**: defined terms and their meanings (these often contain critical thresholds)
  - **Conditions and triggers**: renewal conditions, termination triggers, escalation clauses
  - **References**: references to other documents, laws, regulations, standards, exhibits, annexes

## 4. MAP EVERY SECTION IN DETAIL
List ALL sections/articles/clauses of each document. For each section provide:
  - The heading/title using the document's OWN numbering (Article 3.2, §7, Annex A, etc.)
  - A DETAILED summary that captures ALL key terms, values, conditions, obligations, and \
specific language — not just a one-liner. Include every number that appears in that section.
  - The verbatim original quote

The section summaries are CRITICAL — downstream agents use them to compare documents \
section-by-section. If a section summary is too brief, the comparison will miss changes.

## 5. CAPTURE EXACT QUOTES
For EVERY fact and EVERY section summary, include the `original_quote` field with the \
EXACT text from the source document, verbatim, in the original language. This is \
non-negotiable — it enables traceability.

## OUTPUT FORMAT
Return ONLY a JSON object (no markdown fences, no explanation):
{
  "documents": [
    {
      "doc_id": "doc-1",
      "source_file": "the EXACT uploaded filename (e.g. 'Contract_v2.pdf')",
      "title": "...",
      "type": "contract|invoice|policy|nda|sow|budget|specification|protocol|regulatory|report|other",
      "subtype": "e.g. purchase_order, credit_note, MSA, amendment, service_agreement, etc.",
      "version": "...",
      "author": "...",
      "date": "...",
      "document_number": "...",
      "document_overview": "A 3-5 sentence description of what this document is, its purpose, \
the parties involved, the key commercial/legal/technical terms, and the time period it covers. \
This overview must be detailed enough that a reader can understand the document without seeing it.",
      "sections": [
        {
          "heading": "...",
          "section_number": "Article 3.2, Section 5, §7, Annex A — use the document's own numbering",
          "summary": "Detailed summary capturing ALL key terms, ALL numerical values, ALL conditions and obligations. \
Include every number with its context.",
          "original_quote": "Exact verbatim text (original language)"
        }
      ],
      "facts": [
        {
          "category": "date|amount|party|obligation|kpi|line_item|quantity|percentage|threshold|identifier|definition|reference",
          "label": "descriptive label",
          "value": "exact value from document",
          "confidence": 0.0-1.0,
          "section": "exact heading or article/clause number",
          "original_quote": "exact verbatim quote (original language)"
        }
      ],
      "number_registry": [
        {
          "value": "the exact number as it appears (e.g. '$185,000', '45 days', '10%', 'Net 30')",
          "normalized_value": "numeric-only for comparison (e.g. 185000, 45, 0.10, 30)",
          "unit": "USD|EUR|days|percent|units|hours|pages|FTE|other",
          "context": "what this number represents — e.g. 'monthly service fee', 'payment deadline', 'late penalty rate'",
          "section": "exact section/clause reference",
          "original_quote": "exact verbatim sentence/clause containing this number"
        }
      ],
      "extraction_confidence": {
        "overall": 0.0-1.0,
        "text_quality": "HIGH|MEDIUM|LOW",
        "notes": "any issues (OCR errors, handwriting, blurry scan, truncated text, etc.)"
      }
    }
  ]
}

## CONFIDENCE SCORING
  - **0.9–1.0**: Explicitly and clearly stated, exact match with source text
  - **0.7–0.89**: Minor interpretation needed (ambiguous date format, abbreviation)
  - **0.5–0.69**: Partially stated or inferred from context
  - **0.3–0.49**: Unclear — poor text quality, ambiguous wording, incomplete data
  - **0.0–0.29**: Highly uncertain — guessed from degraded text

## RULES
- Extract ONLY facts explicitly stated in the document. If you must infer, confidence < 0.5.
- The `source_file` field MUST be the exact uploaded filename from the input header.
- The `section` field MUST reference a specific article, clause, or heading number.
- The `original_quote` MUST be exact, unmodified text in the original language.
- The `number_registry` MUST catalog EVERY number in the document — this is used by \
downstream agents for cross-document number consistency analysis.
- Be EXHAUSTIVE. It is better to extract too many facts than to miss any.
"""


AGENT_NAME = "vigil-indexer"


def ensure_indexer_agent() -> str:
    """Find or create the Indexer agent in Foundry. Updates instructions if agent exists."""
    from agents import find_agent_by_name

    client = get_agents_client()
    model = get_indexer_model_name()
    existing_id = find_agent_by_name(AGENT_NAME)
    if existing_id:
        client.update_agent(
            agent_id=existing_id,
            model=model,
            instructions=INSTRUCTIONS,
            temperature=0.1,
        )
        logger.info("Updated Foundry agent '%s' (model=%s): %s", AGENT_NAME, model, existing_id)
        return existing_id

    agent = client.create_agent(
        model=model,
        name=AGENT_NAME,
        instructions=INSTRUCTIONS,
        temperature=0.1,
    )
    logger.info("Created Foundry agent '%s' (model=%s): %s", AGENT_NAME, model, agent.id)
    return agent.id


async def run_indexer(documents: list[dict], language: str = "en", custom_instructions: str = "") -> dict:
    """Run the Indexer agent on a list of parsed documents via Foundry Agent Service."""
    from agents import get_agent_id

    client = get_agents_client()
    agent_id = get_agent_id("indexer")

    # Build document text
    doc_text = ""
    for i, doc in enumerate(documents, 1):
        name = doc.get("filename", f"document-{i}")
        content = doc.get("content", "")
        doc_text += f"\n{'='*60}\nDOCUMENT {i}: {name}\n{'='*60}\n{content}\n"

    suffix = _build_lang_and_notes(language, custom_instructions)
    user_message = f"Extract and index the following documents:{suffix}\n{doc_text}"

    # Run the blocking Foundry SDK call off the event loop
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, _call_indexer_sync, client, agent_id, user_message)

    # Parse JSON from response
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end])
            if "documents" in parsed:
                return _ensure_all_confidence_scores(parsed)
            return _ensure_all_confidence_scores({"documents": [parsed], "raw_output": text})
    except json.JSONDecodeError as exc:
        logger.warning("Indexer returned non-JSON response: %s", exc)

    return {"documents": [], "error": "Indexer did not return valid JSON — please retry"}


# ─── Chunked processing for large documents ───────────────────

MAX_CONCURRENT_CHUNKS = int(os.getenv("MAX_CONCURRENT_CHUNKS", "5"))


def _call_indexer_sync(client, agent_id: str, user_message: str) -> str:
    """Synchronous Foundry Indexer call — runs in a thread-pool executor for true parallelism."""
    thread = client.threads.create()
    client.messages.create(thread_id=thread.id, role="user", content=user_message)
    run = run_with_retry(client.runs.create_and_process, thread_id=thread.id, agent_id=agent_id)
    if run.status == "failed":
        raise RuntimeError(f"Indexer run failed: {run.last_error}")
    messages = client.messages.list(thread_id=thread.id, order=ListSortOrder.ASCENDING)
    for msg in messages:
        if msg.role == "assistant" and msg.text_messages:
            return msg.text_messages[-1].text.value
    return ""


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
    """Try to parse a JSON object from the Indexer's text response."""
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except json.JSONDecodeError:
        pass
    return None


async def run_indexer_parallel(documents: list[dict], language: str = "en", custom_instructions: str = "") -> dict:
    """Process multiple documents concurrently — each in its own Indexer thread.

    Each document gets an independent Foundry API call via the thread-pool executor,
    enabling true parallelism (up to MAX_CONCURRENT_CHUNKS concurrent calls).
    Large individual documents (>15K words) are auto-chunked internally.
    """
    from agents import get_agent_id
    from chunker import chunk_document, LARGE_DOC_THRESHOLD

    client = get_agents_client()
    agent_id = get_agent_id("indexer")
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
                _process_single_chunk(client, agent_id, sem, chunk, filename, doc_idx, len(chunks), language, custom_instructions)
                for chunk in chunks
            ]
            chunk_results = await asyncio.gather(*tasks, return_exceptions=True)
            valid = [r for r in chunk_results if not isinstance(r, Exception)]
            for i, r in enumerate(chunk_results):
                if isinstance(r, Exception):
                    logger.error("[parallel] Doc %d chunk %d failed: %s", doc_idx, i + 1, r)
            return _merge_chunk_facts(valid, doc_idx, filename)

        # Small/medium doc → single Indexer call
        async with sem:
            logger.info("[parallel] Doc %d '%s': %d words", doc_idx, filename, word_count)
            user_message = (
                f"Extract and index the following document:{suffix}\n\n"
                f"{'=' * 60}\nDOCUMENT {doc_idx}: {filename}\n{'=' * 60}\n{content}"
            )
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(None, _call_indexer_sync, client, agent_id, user_message)

            parsed = _parse_indexer_json(text)
            if parsed:
                if "documents" in parsed and parsed["documents"]:
                    doc_result = parsed["documents"][0]
                    doc_result["doc_id"] = f"doc-{doc_idx}"
                    return doc_result
                parsed["doc_id"] = f"doc-{doc_idx}"
                return parsed

            logger.warning("[parallel] Doc %d '%s' returned non-JSON", doc_idx, filename)
            return {"doc_id": f"doc-{doc_idx}", "title": filename, "type": "other", "sections": [], "facts": []}

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
    from agents import get_agent_id
    from chunker import chunk_document

    client = get_agents_client()
    agent_id = get_agent_id("indexer")
    sem = asyncio.Semaphore(MAX_CONCURRENT_CHUNKS)

    all_doc_results = []

    for doc_idx, doc in enumerate(documents, 1):
        content = doc.get("content", "")
        filename = doc.get("filename", f"document-{doc_idx}")
        chunks = chunk_document(content)
        total_chunks = len(chunks)

        logger.info("[chunked] Processing '%s': %d words → %d chunks", filename, len(content.split()), total_chunks)

        tasks = [
            _process_single_chunk(client, agent_id, sem, chunk, filename, doc_idx, total_chunks, language, custom_instructions)
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


async def _process_single_chunk(client, agent_id, sem, chunk, filename, doc_idx, total_chunks, language, custom_instructions):
    """Extract facts from a single document chunk via the Indexer agent."""
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

        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, _call_indexer_sync, client, agent_id, user_message)

        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(text[start:end])
                if "documents" in parsed:
                    return parsed
                return {"documents": [parsed]}
        except json.JSONDecodeError as exc:
            logger.warning("[chunked] Chunk %d returned non-JSON: %s", chunk["index"] + 1, exc)

        return {"documents": []}


def _merge_chunk_facts(chunk_results: list[dict], doc_idx: int, filename: str) -> dict:
    """Merge fact sheets from multiple chunks into one unified document fact sheet."""
    merged: dict = {
        "doc_id": f"doc-{doc_idx}",
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
