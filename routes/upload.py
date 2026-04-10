"""
Upload route — accepts multipart file uploads, parses documents, returns results.
"""

import asyncio
import logging
import uuid

from aiohttp import web

from doc_parser import parse_document
from routes import ALLOWED_EXTENSIONS

logger = logging.getLogger("vigil")


async def handle_upload(request: web.Request) -> web.Response:
    """Accept multipart file uploads, parse them concurrently, return parsed results."""
    reader = await request.multipart()
    raw_files: list[tuple[str, bytes]] = []
    errors = []

    # 1. Read all file parts first (IO-bound, async-safe)
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "files":
            filename = part.filename or "unknown.txt"
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext not in ALLOWED_EXTENSIONS:
                errors.append({"filename": filename, "error": f"File type '.{ext}' is not allowed"})
                continue
            try:
                data = await part.read()
                raw_files.append((filename, data))
            except Exception as exc:
                logger.error("Failed to read %s: %s", filename, exc, exc_info=True)
                errors.append({"filename": filename, "error": str(exc)})

    # 2. Parse all files concurrently in the thread pool (CPU/IO-bound)
    loop = asyncio.get_event_loop()
    documents = []

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
    documents = [r for r in results if r is not None]

    response = {
        "status": "ok" if documents else "error",
        "count": len(documents),
        "documents": [
            {"id": d["id"], "filename": d["filename"], "word_count": d["word_count"], "size_bytes": d["size_bytes"]}
            for d in documents
        ],
        # Full parsed content for the frontend to send back on /api/run
        "_parsed": [
            {"id": d["id"], "filename": d["filename"], "content": d["content"], "word_count": d["word_count"]}
            for d in documents
        ],
    }
    if errors:
        response["errors"] = errors

    return web.json_response(response)
