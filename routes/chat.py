"""
Chat route — RAG-first follow-up conversation about documents.
Always queries Azure AI Search facts index to ground answers in actual
document data. Pipeline report provides supplementary context.
"""

import asyncio
import logging

from aiohttp import web

from routes import (
    VALID_LANGUAGES,
    MAX_MESSAGE_LENGTH,
    MAX_CHAT_HISTORY,
    JOB_ID_PATTERN,
    SEARCH_CONTEXT_TOP_K,
    jobs,
)

logger = logging.getLogger("vigil")


async def handle_chat(request: web.Request) -> web.Response:
    """Follow-up chat — RAG-first, grounded in document data via Azure AI Search."""
    body = await request.json()
    job_id = body.get("job_id", "")
    message = body.get("message", "")
    history = body.get("history", [])
    language = body.get("language", "en")

    if not message:
        return web.json_response({"error": "No message provided"}, status=400)
    if len(message) > MAX_MESSAGE_LENGTH:
        return web.json_response({"error": "Message too long"}, status=400)
    if job_id and not JOB_ID_PATTERN.match(job_id):
        return web.json_response({"error": "Invalid job ID format"}, status=400)
    if language not in VALID_LANGUAGES:
        language = "en"
    history = [
        {"role": str(h.get("role", "user"))[:10], "content": str(h.get("content", ""))[:MAX_MESSAGE_LENGTH]}
        for h in history[:MAX_CHAT_HISTORY]
        if isinstance(h, dict) and h.get("role") in ("user", "assistant")
    ]

    job = jobs.get(job_id)

    # ── 1. RAG: retrieve relevant document data from facts index (PRIMARY source) ──
    facts_context = ""
    try:
        from search_client import search_facts
        facts = search_facts(message, job_id=job_id, top=10)
        if facts:
            parts: list[str] = []
            for f in facts:
                source = f.get("source_file", "")
                entry_type = f.get("entry_type", "")
                section = f.get("section", "")
                if entry_type == "section":
                    parts.append(f"[{source}, {section}] SECTION: {f.get('content', '')}")
                elif entry_type == "fact":
                    parts.append(f"[{source}, {section}] FACT: {f.get('label', '')} = {f.get('value', '')}")
                elif entry_type == "number":
                    parts.append(f"[{source}, {section}] NUMBER: {f.get('value', '')} — {f.get('label', '')}")
            facts_context = "\n".join(parts)
            logger.info("Chat RAG: retrieved %d facts for query", len(facts))
    except Exception:
        pass

    # ── 2. Raw document chunks from chunks index (always available) ──
    chunks_context = ""
    try:
        from search_client import search_chunks
        chunks = search_chunks(message, job_id=job_id, top=SEARCH_CONTEXT_TOP_K)
        if chunks:
            chunk_parts = []
            for c in chunks:
                chunk_parts.append(f"[{c['filename']}, chunk {c['chunk_index'] + 1}]:\n{c['content']}")
            chunks_context = "\n\n".join(chunk_parts)
    except Exception:
        pass

    # ── 3. Pipeline report as supplementary context (compact) ──
    report_context = ""
    if job and job.get("status") == "done" and job.get("result"):
        result_text = str(job["result"])
        if len(result_text) > 6_000:
            result_text = result_text[:6_000] + "\n[...report truncated...]"
        report_context = result_text

    # ── Build system prompt — RAG-first ──
    lang_note = ""
    if language == "pl":
        lang_note = "\n\nIMPORTANT: Respond entirely in Polish (polski)."

    system_msg = (
        "You are **Vigil – Document Analyst**, a follow-up assistant. "
        "The user has analyzed documents and wants to ask questions about them.\n\n"
        "YOUR PRIMARY DATA SOURCE is the retrieved document data below — "
        "facts, sections, and numbers extracted directly from the uploaded documents. "
        "Always ground your answers in this data and cite specific document sections.\n\n"
        "The analysis report is provided as supplementary context — use it for the "
        "overall findings and recommendations, but prefer the raw document data for "
        "specific facts, numbers, and quotes.\n\n"
        "Always cite **[filename, section]** for every claim. Use markdown formatting."
        f"{lang_note}"
    )

    # ── Build user message with prioritized context ──
    user_content = ""

    if facts_context:
        user_content += f"DOCUMENT DATA (from Azure AI Search — primary source):\n{facts_context}\n\n"

    if chunks_context:
        user_content += f"RAW DOCUMENT SECTIONS:\n{chunks_context}\n\n"

    if report_context:
        user_content += f"ANALYSIS REPORT (supplementary):\n{report_context}\n\n"

    if not facts_context and not chunks_context and not report_context:
        user_content += "No analysis context available.\n\n"

    history_text = ""
    for h in history:
        role = h.get("role", "user")
        history_text += f"[{role}]: {h.get('content', '')}\n"
    if history_text:
        user_content += f"CONVERSATION HISTORY:\n{history_text}\n"
    user_content += f"USER QUESTION: {message}"

    # ── Call LLM ──
    from foundry_client import get_inference_client, get_advisor_model_name
    from azure.ai.inference.models import SystemMessage, UserMessage

    model = get_advisor_model_name()
    client = get_inference_client(model)

    def _call_chat_sync() -> str:
        call_kwargs = dict(
            messages=[
                SystemMessage(content=system_msg),
                UserMessage(content=user_content),
            ],
        )
        try:
            response = client.complete(**call_kwargs, temperature=0.3)
        except Exception:
            response = client.complete(**call_kwargs)
        return response.choices[0].message.content or "No response."

    try:
        loop = asyncio.get_running_loop()
        reply = await loop.run_in_executor(None, _call_chat_sync)
        return web.json_response({"reply": reply})
    except Exception as e:
        logger.error("Chat error: %s", e, exc_info=True)
        return web.json_response({"error": "An internal error occurred. Please try again."}, status=500)
