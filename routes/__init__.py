"""
Vigil routes package.

Shared configuration, validation constants, and the in-memory job store
used by all route modules.
"""

import os
import re
import time

# ─── Shared configuration ─────────────────────────────────────

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "xlsx", "xls", "png", "jpg", "jpeg", "tiff", "tif", "bmp"}
JOB_ID_PATTERN = re.compile(r"^[a-f0-9\-]{1,36}$")
SEARCH_CONTEXT_TOP_K = int(os.getenv("SEARCH_CONTEXT_TOP_K", "3"))

VALID_WORKFLOWS = {"version_comparison", "compliance_check", "document_pack", "fact_extraction", "summary"}
VALID_LANGUAGES = {"en", "pl"}
MAX_MESSAGE_LENGTH = 10_000
MAX_CHAT_HISTORY = 30

# ─── In-memory job store with TTL ─────────────────────────────

MAX_JOBS = 100
JOB_TTL_SECONDS = 3600  # 1 hour

jobs: dict[str, dict] = {}


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
