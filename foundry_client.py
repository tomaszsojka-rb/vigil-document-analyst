"""
Shared Azure AI Foundry client for Vigil agents.

Provides a singleton AgentsClient authenticated via DefaultAzureCredential.
All three pipeline agents (Indexer, Analyzer, Advisor) share this client
for runtime operations: creating agents, threads, messages, and runs.

Includes retry helpers for rate-limit errors (HTTP 429) so parallel
document processing gracefully handles transient quota exhaustion.
"""

import logging
import os
import time

from azure.ai.agents import AgentsClient
from azure.identity import DefaultAzureCredential

logger = logging.getLogger("vigil.foundry_client")

_agents_client: AgentsClient | None = None

MAX_RETRIES = int(os.getenv("FOUNDRY_MAX_RETRIES", "4"))
INITIAL_BACKOFF = float(os.getenv("FOUNDRY_INITIAL_BACKOFF", "15"))  # seconds


def _get_endpoint() -> str:
    """Return the Foundry project endpoint from environment. Raises if not set."""
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "")
    if not endpoint:
        raise ValueError("FOUNDRY_PROJECT_ENDPOINT must be set to your Foundry project endpoint")
    return endpoint


def get_agents_client() -> AgentsClient:
    """Return a configured AgentsClient (singleton).

    Used for all agent runtime operations: create/list agents, threads,
    messages, and runs via the Azure AI Agent Service SDK.
    """
    global _agents_client
    if _agents_client is not None:
        return _agents_client

    _agents_client = AgentsClient(
        endpoint=_get_endpoint(),
        credential=DefaultAzureCredential(),
    )
    logger.info("AgentsClient initialized for %s", _get_endpoint())
    return _agents_client


def get_model_name() -> str:
    """Return the configured model deployment name (default: gpt-4.1)."""
    return os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4.1")


def get_indexer_model_name() -> str:
    """Return the model for the Indexer agent (default: gpt-4.1-mini for speed)."""
    return os.getenv("FOUNDRY_INDEXER_MODEL", "gpt-4.1-mini")


def get_analyzer_model_name() -> str:
    """Return the model for the Analyzer agent (default: gpt-4.1-mini for speed)."""
    return os.getenv("FOUNDRY_ANALYZER_MODEL", "gpt-4.1-mini")


def get_advisor_model_name() -> str:
    """Return the model for the Advisor agent (default: gpt-4.1 for report quality)."""
    return os.getenv("FOUNDRY_ADVISOR_MODEL", get_model_name())


def _is_rate_limit(exc: Exception) -> bool:
    """Check if an exception (or an agent run error) is a rate-limit error."""
    msg = str(exc).lower()
    return "rate_limit" in msg or "429" in msg or "retry after" in msg


def run_with_retry(fn, *args, **kwargs):
    """Call *fn* with retry-and-backoff on rate-limit errors (synchronous).

    Used for blocking Foundry SDK calls like ``client.runs.create_and_process``.
    """
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = fn(*args, **kwargs)
            # Agent runs return a run object — check if it failed with a rate limit
            if hasattr(result, "status") and result.status == "failed":
                error_str = str(getattr(result, "last_error", ""))
                if _is_rate_limit(Exception(error_str)):
                    backoff = INITIAL_BACKOFF * (2 ** (attempt - 1))
                    logger.warning("Rate limit on attempt %d/%d, retrying in %.0fs …", attempt, MAX_RETRIES, backoff)
                    time.sleep(backoff)
                    last_exc = RuntimeError(f"Rate limited: {error_str}")
                    continue
            return result
        except Exception as exc:
            if _is_rate_limit(exc) and attempt < MAX_RETRIES:
                backoff = INITIAL_BACKOFF * (2 ** (attempt - 1))
                logger.warning("Rate limit on attempt %d/%d, retrying in %.0fs …", attempt, MAX_RETRIES, backoff)
                time.sleep(backoff)
                last_exc = exc
            else:
                raise
    raise last_exc or RuntimeError("Exhausted retries due to rate limiting")
