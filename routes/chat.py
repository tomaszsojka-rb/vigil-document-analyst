"""
Chat route — follow-up conversation about analysis results.
Uses the Advisor agent with full pipeline context + optional Azure AI Search RAG.
"""

import asyncio
import json
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
    """Follow-up chat about analysis results. Uses the Advisor agent with full context."""
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
    context_parts: list[str] = []
    if job and job.get("status") == "done":
        for stage in job.get("stages") or []:
            output = stage.get("output")
            if output:
                snippet = json.dumps(output, indent=1, default=str)
                # Truncate large stage outputs to keep within token budget
                if len(snippet) > 8_000:
                    snippet = snippet[:8_000] + "\n[...truncated for brevity...]"
                context_parts.append(f"--- {stage['agent']} output ---\n{snippet}")
        if job.get("result"):
            result_text = str(job["result"])
            if len(result_text) > 12_000:
                result_text = result_text[:12_000] + "\n[...truncated for brevity...]"
            context_parts.append(f"--- Final Report ---\n{result_text}")

    context_text = "\n\n".join(context_parts) if context_parts else "No analysis context available."

    # For chunked jobs, search for relevant document sections via Azure AI Search
    search_context = ""
    if job and job.get("_chunked"):
        try:
            from search_client import search_chunks
            chunks = search_chunks(message, job_id=job_id, top=SEARCH_CONTEXT_TOP_K)
            if chunks:
                search_context = "\n\n--- Relevant document sections (retrieved via Azure AI Search) ---\n"
                for c in chunks:
                    search_context += f"\n[{c['filename']}, section {c['chunk_index'] + 1}]:\n{c['content']}\n"
        except Exception:
            pass  # Search not available — no problem

    lang_note = ""
    if language == "pl":
        lang_note = "\n\nIMPORTANT: Respond entirely in Polish (polski)."

    system_msg = (
        "You are **Vigil – Document Analyst**, a follow-up assistant. "
        "The user has just completed a document analysis with your multi-agent pipeline. "
        "Below is the full context from all three agents (Indexer, Analyzer, Advisor).\n\n"
        f"{context_text}\n\n"
        f"{search_context}\n\n"
        "Answer the user's follow-up questions about this analysis. "
        "You can drill deeper into specific findings, explain changes in more detail, "
        "compare specific sections, extract additional facts, or provide alternative perspectives. "
        "Always cite specific document sections. Use markdown formatting."
        f"{lang_note}"
    )

    from foundry_client import get_agents_client, run_with_retry
    from agents import get_agent_id
    from azure.ai.agents.models import ListSortOrder

    client = get_agents_client()
    advisor_id = get_agent_id("advisor")

    # Build the full user message with context for the Foundry agent thread
    context_preamble = f"ANALYSIS CONTEXT:\n{context_text}\n\n" if context_text != "No analysis context available." else ""
    history_text = ""
    for h in history:
        role = h.get("role", "user")
        history_text += f"[{role}]: {h.get('content', '')}\n"
    if history_text:
        history_text = f"CONVERSATION HISTORY:\n{history_text}\n"

    full_message = f"{system_msg}\n\n{context_preamble}{history_text}USER QUESTION: {message}"

    def _call_chat_sync() -> str:
        """Synchronous Foundry chat call — runs in a thread-pool executor."""
        thread = client.threads.create()
        client.messages.create(thread_id=thread.id, role="user", content=full_message)
        run = run_with_retry(client.runs.create_and_process, thread_id=thread.id, agent_id=advisor_id)
        if run.status == "failed":
            raise RuntimeError(f"Chat agent run failed: {run.last_error}")
        messages_list = client.messages.list(thread_id=thread.id, order=ListSortOrder.ASCENDING)
        for msg in messages_list:
            if msg.role == "assistant" and msg.text_messages:
                return msg.text_messages[-1].text.value
        return "No response."

    try:
        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(None, _call_chat_sync)
        return web.json_response({"reply": reply})
    except Exception as e:
        logger.error("Chat error: %s", e, exc_info=True)
        return web.json_response({"error": "An internal error occurred. Please try again."}, status=500)
