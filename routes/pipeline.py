"""
Pipeline routes — run workflow, stream progress, get job status.
Orchestrates the 3-agent pipeline (Indexer → Analyzer → Advisor).
"""

import asyncio
import json
import logging
import os
import time
import uuid

from aiohttp import web

from chunker import is_large
from gap_rules import load_ruleset, evaluate_rules
from agents.indexer import run_indexer, run_indexer_chunked, run_indexer_parallel
from agents.analyzer import run_analyzer
from agents.advisor import run_advisor_streaming
from routes import (
    DOCUMENT_ID_PATTERN,
    VALID_WORKFLOWS,
    VALID_LANGUAGES,
    MAX_MESSAGE_LENGTH,
    JOB_ID_PATTERN,
    cleanup_expired_upload_sessions,
    get_upload_documents,
    jobs,
    cleanup_expired_jobs,
)

logger = logging.getLogger("vigil")


# ─── Start pipeline ───────────────────────────────────────────

async def handle_run(request: web.Request) -> web.Response:
    """Start a 3-agent workflow pipeline. Returns a job ID for SSE progress."""
    body = await request.json()
    workflow = body.get("workflow", "summary")
    upload_id = str(body.get("upload_id", "")).strip()
    document_ids = body.get("document_ids", [])
    language = body.get("language", "en")
    custom_instructions = body.get("custom_instructions", "")

    if not upload_id or not JOB_ID_PATTERN.match(upload_id):
        return web.json_response({"error": "Invalid or missing upload session ID"}, status=400)
    if document_ids is not None and not isinstance(document_ids, list):
        return web.json_response({"error": "document_ids must be a list"}, status=400)
    if workflow not in VALID_WORKFLOWS:
        return web.json_response({"error": f"Invalid workflow: {workflow}"}, status=400)
    if language not in VALID_LANGUAGES:
        language = "en"
    if len(custom_instructions) > MAX_MESSAGE_LENGTH:
        return web.json_response({"error": "Custom instructions too long"}, status=400)

    for document_id in document_ids:
        if not isinstance(document_id, str) or not DOCUMENT_ID_PATTERN.match(document_id):
            return web.json_response({"error": "Invalid document ID format"}, status=400)

    cleanup_expired_jobs()
    cleanup_expired_upload_sessions()

    documents = get_upload_documents(upload_id, document_ids or None)
    if documents is None:
        return web.json_response({"error": "Upload session expired. Please upload your files again."}, status=410)
    if not documents:
        return web.json_response({"error": "No documents selected for analysis"}, status=400)

    job_id = str(uuid.uuid4())[:12]
    jobs[job_id] = {
        "status": "running",
        "upload_id": upload_id,
        "workflow": workflow,
        "language": language,
        "custom_instructions": custom_instructions,
        "stages": [],
        "current_stage": "indexer",
        "result": None,
        "error": None,
        "advisor_chunks": [],
        "advisor_streaming": False,
        "advisor_stream_done": False,
        "_created": time.monotonic(),
    }

    # Run pipeline in background
    asyncio.create_task(_run_pipeline(job_id, workflow, documents, language, custom_instructions))

    return web.json_response({"job_id": job_id, "status": "running"})


# ─── Pipeline execution ───────────────────────────────────────

async def _run_pipeline(job_id: str, workflow: str, documents: list[dict], language: str = "en", custom_instructions: str = ""):
    """Execute the 3-agent pipeline."""
    job = jobs[job_id]

    try:
        chunked = is_large(documents)
        multi_doc = len(documents) > 1

        # ── Stage 1: Indexer ──
        job["current_stage"] = "indexer"
        job["stages"].append({"agent": "Indexer & Extractor", "status": "running", "output": None})

        if multi_doc:
            total_words = sum(len(d.get("content", "").split()) for d in documents)
            logger.info("[%s] Stage 1: Indexer starting PARALLEL (%d docs, %d words)", job_id, len(documents), total_words)
            indexer_result = await run_indexer_parallel(documents, language=language, custom_instructions=custom_instructions)
        elif chunked:
            total_words = sum(len(d.get("content", "").split()) for d in documents)
            logger.info("[%s] Stage 1: Indexer starting CHUNKED (%d docs, %d words)", job_id, len(documents), total_words)
            indexer_result = await run_indexer_chunked(documents, language=language, custom_instructions=custom_instructions)
        else:
            logger.info("[%s] Stage 1: Indexer starting (%d docs)", job_id, len(documents))
            indexer_result = await run_indexer(documents, language=language, custom_instructions=custom_instructions)

        # Always index document chunks in Search for RAG (chat can query raw text)
        _try_index_chunks_in_search(job_id, documents)

        job["stages"][-1]["status"] = "done"
        job["stages"][-1]["output"] = indexer_result
        job["_chunked"] = chunked
        logger.info("[%s] Stage 1: Indexer done", job_id)

        # Abort if Indexer failed or returned no documents
        if indexer_result.get("error") or not indexer_result.get("documents"):
            error_msg = indexer_result.get("error", "Indexer returned no documents")
            raise RuntimeError(f"Indexer failed: {error_msg}")

        # ── Index facts in Azure AI Search (enables focused Analyzer context) ──
        _try_index_facts_in_search(job_id, indexer_result)

        # ── Gap Analysis Rules (pre-Analyzer) ──
        # For compliance_check and document_pack workflows, evaluate YAML DSL rules
        # and inject findings into the Indexer output for the Analyzer to consider.
        if workflow in ("compliance_check", "document_pack"):
            try:
                ruleset_path = os.getenv("GAP_ANALYSIS_RULESET")
                ruleset = load_ruleset(ruleset_path)
                if ruleset.get("rules"):
                    rule_findings = evaluate_rules(ruleset, indexer_result)
                    indexer_result["gap_rule_findings"] = rule_findings
                    pass_count = sum(1 for f in rule_findings if f["status"] == "PASS")
                    fail_count = sum(1 for f in rule_findings if f["status"] == "FAIL")
                    warn_count = sum(1 for f in rule_findings if f["status"] == "WARNING")
                    logger.info(
                        "[%s] Gap rules: %d evaluated — %d pass, %d fail, %d warning",
                        job_id, len(rule_findings), pass_count, fail_count, warn_count,
                    )
            except Exception as exc:
                logger.warning("[%s] Gap rule evaluation failed (non-fatal): %s", job_id, exc)

        # ── Stage 2: Analyzer ──
        job["current_stage"] = "analyzer"
        job["stages"].append({"agent": "Analyzer", "status": "running", "output": None})
        logger.info("[%s] Stage 2: Analyzer starting (workflow=%s)", job_id, workflow)

        # Build focused context from Search index (falls back to full JSON if unavailable)
        search_context = _try_build_analyzer_context(job_id, workflow, indexer_result, custom_instructions)

        analyzer_result = await run_analyzer(
            workflow, indexer_result,
            language=language,
            custom_instructions=custom_instructions,
            search_context=search_context,
        )
        job["stages"][-1]["status"] = "done"
        job["stages"][-1]["output"] = analyzer_result
        logger.info("[%s] Stage 2: Analyzer done", job_id)

        # Abort if Analyzer failed
        if analyzer_result.get("error"):
            raise RuntimeError(f"Analyzer failed: {analyzer_result['error']}")

        # ── Stage 3: Advisor (streaming) ──
        job["current_stage"] = "advisor"
        job["stages"].append({"agent": "Advisor", "status": "running", "output": None})
        logger.info("[%s] Stage 3: Advisor starting (streaming)", job_id)

        job["advisor_streaming"] = True
        loop = asyncio.get_running_loop()
        try:
            full_text = await loop.run_in_executor(
                None,
                _run_advisor_streaming_sync,
                job,
                workflow,
                analyzer_result,
                language,
                custom_instructions,
            )
        except Exception as exc:
            logger.error("[%s] Advisor streaming error: %s", job_id, exc, exc_info=True)
            full_text = f"# Analysis Failed\n\nThe Advisor agent encountered an error: {exc}"

        job["advisor_stream_done"] = True
        job["stages"][-1]["status"] = "done"
        job["stages"][-1]["output"] = full_text
        logger.info("[%s] Stage 3: Advisor done", job_id)

        job["status"] = "done"
        job["current_stage"] = "complete"
        job["result"] = full_text

    except Exception as e:
        logger.error("[%s] Pipeline error: %s", job_id, e, exc_info=True)
        job["status"] = "error"
        job["error"] = str(e)
        if job["stages"] and job["stages"][-1]["status"] == "running":
            job["stages"][-1]["status"] = "error"


def _run_advisor_streaming_sync(job: dict, workflow: str, analyzer_result: dict, language: str, custom_instructions: str) -> str:
    """Run the streaming advisor in a sync context, appending chunks to job['advisor_chunks']."""
    full_text = ""
    try:
        for chunk in run_advisor_streaming(workflow, analyzer_result, language=language, custom_instructions=custom_instructions):
            full_text += chunk
            job["advisor_chunks"].append(chunk)
    except Exception as exc:
        logger.error("Advisor streaming generator error: %s", exc, exc_info=True)
        if not full_text:
            full_text = f"# Analysis Failed\n\nThe Advisor agent encountered an error: {exc}"
    return full_text


def _try_index_chunks_in_search(job_id: str, documents: list[dict]) -> None:
    """Best-effort: index document chunks in Azure AI Search for follow-up chat RAG."""
    try:
        from chunker import chunk_document
        from search_client import ensure_chunks_index, index_document_chunks

        if not ensure_chunks_index():
            return

        for i, doc in enumerate(documents, 1):
            chunks = chunk_document(doc.get("content", ""))
            index_document_chunks(chunks, job_id, f"doc-{i}", doc.get("filename", f"document-{i}"))
    except Exception as exc:
        logger.warning("Chunk indexing in Search skipped: %s", exc)


def _try_index_facts_in_search(job_id: str, indexer_result: dict) -> None:
    """Best-effort: index structured facts from Indexer output into Azure AI Search."""
    try:
        from search_client import ensure_facts_index, index_facts

        if not ensure_facts_index():
            return

        count = index_facts(indexer_result, job_id)
        if count:
            logger.info("[%s] Indexed %d facts/sections in Search", job_id, count)
    except Exception as exc:
        logger.warning("[%s] Facts indexing in Search skipped: %s", job_id, exc)


def _try_build_analyzer_context(job_id: str, workflow: str, indexer_result: dict, custom_instructions: str) -> str:
    """Best-effort: build focused Analyzer context from Search facts index."""
    try:
        from search_client import build_analyzer_context
        context = build_analyzer_context(job_id, workflow, indexer_result, custom_instructions)
        if context:
            logger.info("[%s] Built focused Analyzer context from Search (%d chars)", job_id, len(context))
        return context
    except Exception as exc:
        logger.warning("[%s] Analyzer Search context skipped (using full JSON): %s", job_id, exc)
        return ""


# ─── SSE stream ───────────────────────────────────────────────

async def handle_job_stream(request: web.Request) -> web.StreamResponse:
    """SSE endpoint: streams pipeline stage updates and advisor text chunks."""
    job_id = request.match_info["job_id"]
    if not JOB_ID_PATTERN.match(job_id):
        return web.json_response({"error": "Invalid job ID format"}, status=400)
    job = jobs.get(job_id)
    if not job:
        return web.json_response({"error": "Job not found"}, status=404)

    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)

    last_stage_snapshot = ""
    advisor_chunk_idx = 0

    try:
        while True:
            # Send stage updates when stages change
            stages = job.get("stages", [])
            stage_data = [{"agent": s["agent"], "status": s["status"]} for s in stages]
            current_status = job["status"]
            snapshot = json.dumps(stage_data) + current_status

            if snapshot != last_stage_snapshot:
                msg = json.dumps({"type": "stages", "stages": stage_data, "status": current_status, "current_stage": job["current_stage"]})
                await response.write(f"data: {msg}\n\n".encode())
                last_stage_snapshot = snapshot

            # Stream advisor text chunks
            chunks = job.get("advisor_chunks", [])
            while advisor_chunk_idx < len(chunks):
                chunk = chunks[advisor_chunk_idx]
                advisor_chunk_idx += 1
                msg = json.dumps({"type": "advisor_chunk", "text": chunk})
                await response.write(f"data: {msg}\n\n".encode())

            # Check if done
            if current_status in ("done", "error"):
                # Send final message with full result and stage outputs
                final = {"type": "done", "status": current_status}
                if current_status == "done":
                    final["result"] = job["result"]
                    final["stage_outputs"] = [
                        {"agent": s["agent"], "output": s["output"]}
                        for s in stages
                    ]
                else:
                    final["error"] = job.get("error")
                await response.write(f"data: {json.dumps(final)}\n\n".encode())
                break

            await asyncio.sleep(0.3)
    except (ConnectionResetError, asyncio.CancelledError):
        pass

    return response


# ─── Job status ────────────────────────────────────────────────

async def handle_job_status(request: web.Request) -> web.Response:
    """Get the current status of a job."""
    job_id = request.match_info["job_id"]
    if not JOB_ID_PATTERN.match(job_id):
        return web.json_response({"error": "Invalid job ID format"}, status=400)
    job = jobs.get(job_id)
    if not job:
        return web.json_response({"error": "Job not found"}, status=404)

    # Build safe response (don't send full internal outputs unless done)
    response = {
        "job_id": job_id,
        "status": job["status"],
        "workflow": job["workflow"],
        "current_stage": job["current_stage"],
        "stages": [
            {"agent": s["agent"], "status": s["status"]}
            for s in job["stages"]
        ],
        "error": job["error"],
    }

    if job["status"] == "done":
        response["result"] = job["result"]
        # Include intermediate outputs for transparency
        response["stage_outputs"] = [
            {"agent": s["agent"], "output": s["output"]}
            for s in job["stages"]
        ]

    return web.json_response(response)
