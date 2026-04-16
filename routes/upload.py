"""
Upload route — accepts multipart file uploads, parses documents, returns results.
"""

import asyncio
import logging
import time
import uuid

from aiohttp import web

from doc_parser import parse_document
from routes import (
    ALLOWED_EXTENSIONS,
    JOB_ID_PATTERN,
    MAX_FILES_PER_UPLOAD,
    MAX_FILE_SIZE_BYTES,
    MAX_FILE_SIZE_MB,
    cleanup_expired_upload_sessions,
    new_session_id,
    normalize_filename,
    upload_sessions,
)

logger = logging.getLogger("vigil")


async def handle_upload(request: web.Request) -> web.Response:
    """Accept multipart file uploads, parse them concurrently, and store them server-side."""
    reader = await request.multipart()
    raw_files: list[tuple[str, bytes]] = []
    errors = []
    upload_id = ""

    # 1. Read all file parts first (IO-bound, async-safe)
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "upload_id":
            upload_id = (await part.text()).strip()
            continue
        if part.name == "files":
            if len(raw_files) >= MAX_FILES_PER_UPLOAD:
                await part.read(decode=False)
                errors.append({"filename": part.filename or "unknown.txt", "error": f"Too many files in one upload (max {MAX_FILES_PER_UPLOAD})"})
                continue

            filename = normalize_filename(part.filename or "upload.txt")
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext not in ALLOWED_EXTENSIONS:
                await part.read(decode=False)
                errors.append({"filename": filename, "error": f"File type '.{ext}' is not allowed"})
                continue
            try:
                data = await part.read()
                if len(data) > MAX_FILE_SIZE_BYTES:
                    errors.append({"filename": filename, "error": f"File exceeds the {MAX_FILE_SIZE_MB} MB per-file limit"})
                    continue
                raw_files.append((filename, data))
            except Exception as exc:
                logger.error("Failed to read %s: %s", filename, exc, exc_info=True)
                errors.append({"filename": filename, "error": str(exc)})

    if upload_id and not JOB_ID_PATTERN.match(upload_id):
        return web.json_response({"error": "Invalid upload session ID"}, status=400)

    cleanup_expired_upload_sessions()

    session: dict | None = None
    if upload_id:
        session = upload_sessions.get(upload_id)
        if session is None:
            return web.json_response({"error": "Upload session expired. Please upload your files again."}, status=410)

    if not raw_files and not errors:
        return web.json_response({"error": "No files provided"}, status=400)

    # 2. Parse all files concurrently in the thread pool (CPU/IO-bound)
    loop = asyncio.get_running_loop()

    async def _parse_one(filename: str, data: bytes) -> dict | None:
        try:
            text = await loop.run_in_executor(None, parse_document, filename, data)
            word_count = len(text.split())
            logger.info("Uploaded: %s (%d words)", filename, word_count)
            return {
                "id": str(uuid.uuid4())[:8],
                "filename": filename,
                "content": text,
                "word_count": word_count,
                "size_bytes": len(data),
            }
        except Exception as exc:
            logger.error("Failed to parse %s: %s", filename, exc, exc_info=True)
            errors.append({"filename": filename, "error": str(exc)})
            return None

    results = await asyncio.gather(*[_parse_one(fn, data) for fn, data in raw_files])
    documents = [result for result in results if result is not None]

    if session is None:
        upload_id = new_session_id()
        session = {
            "documents": [],
            "_created": time.monotonic(),
            "_updated": time.monotonic(),
        }
        upload_sessions[upload_id] = session

    if documents:
        session["documents"].extend(documents)
    session["_updated"] = time.monotonic()

    response = {
        "status": "ok" if documents else "error",
        "upload_id": upload_id,
        "count": len(documents),
        "total_documents": len(session["documents"]),
        "documents": [
            {"id": d["id"], "filename": d["filename"], "word_count": d["word_count"], "size_bytes": d["size_bytes"]}
            for d in documents
        ],
    }
    if errors:
        response["errors"] = errors

    status = 200 if documents else 400
    return web.json_response(response, status=status)
