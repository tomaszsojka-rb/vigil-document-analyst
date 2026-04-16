"""
Vigil routes package.

Shared configuration, validation constants, and the in-memory job store
used by all route modules.
"""

import os
import re
import time
import uuid
from pathlib import Path

# ─── Shared configuration ─────────────────────────────────────

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "xlsx", "xls", "png", "jpg", "jpeg", "tiff", "tif", "bmp"}
JOB_ID_PATTERN = re.compile(r"^[a-f0-9\-]{1,36}$")
DOCUMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SEARCH_CONTEXT_TOP_K = int(os.getenv("SEARCH_CONTEXT_TOP_K", "3"))

VALID_WORKFLOWS = {"version_comparison", "compliance_check", "document_pack", "fact_extraction", "summary"}
VALID_LANGUAGES = {"en", "pl"}
MAX_MESSAGE_LENGTH = 10_000
MAX_CHAT_HISTORY = 30
MAX_FILES_PER_UPLOAD = int(os.getenv("VIGIL_MAX_FILES", "80"))
MAX_FILE_SIZE_MB = int(os.getenv("VIGIL_MAX_FILE_MB", "50"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_REQUEST_SIZE_MB = int(os.getenv("VIGIL_MAX_REQUEST_MB", "100"))
MAX_REQUEST_SIZE_BYTES = MAX_REQUEST_SIZE_MB * 1024 * 1024

# ─── In-memory job store with TTL ─────────────────────────────

MAX_JOBS = 100
JOB_TTL_SECONDS = 3600  # 1 hour
UPLOAD_SESSION_TTL_SECONDS = int(os.getenv("UPLOAD_SESSION_TTL_SECONDS", "3600"))

jobs: dict[str, dict] = {}
upload_sessions: dict[str, dict] = {}


def new_session_id() -> str:
    """Create a short session identifier that matches our validation pattern."""
    return uuid.uuid4().hex[:12]


def normalize_filename(filename: str) -> str:
    """Return a safe display name without path fragments or control characters."""
    candidate = Path(filename or "upload.txt").name
    candidate = candidate.replace("\x00", "").replace("\r", " ").replace("\n", " ").strip()
    candidate = re.sub(r"\s+", " ", candidate)
    return candidate[:200] or "upload.txt"


def cleanup_expired_jobs() -> None:
    """Remove jobs older than JOB_TTL_SECONDS. Called before creating new jobs."""
    now = time.monotonic()
    expired = [jid for jid, job in jobs.items() if now - job.get("_created", 0) > JOB_TTL_SECONDS]
    for jid in expired:
        del jobs[jid]
    # Also enforce max capacity
    if len(jobs) > MAX_JOBS:
        oldest = sorted(jobs, key=lambda k: jobs[k].get("_created", 0))
        for jid in oldest[: len(jobs) - MAX_JOBS]:
            del jobs[jid]


def cleanup_expired_upload_sessions() -> None:
    """Remove expired upload sessions that are no longer valid for analysis runs."""
    now = time.monotonic()
    expired = [
        session_id
        for session_id, session in upload_sessions.items()
        if now - session.get("_updated", session.get("_created", 0)) > UPLOAD_SESSION_TTL_SECONDS
    ]
    for session_id in expired:
        del upload_sessions[session_id]


def get_upload_documents(upload_id: str, document_ids: list[str] | None = None) -> list[dict] | None:
    """Resolve parsed documents from a server-side upload session."""
    session = upload_sessions.get(upload_id)
    if session is None:
        return None

    session["_updated"] = time.monotonic()
    documents = session.get("documents", [])
    if not document_ids:
        return [dict(document) for document in documents]

    requested_ids = set(document_ids)
    return [dict(document) for document in documents if document.get("id") in requested_ids]
