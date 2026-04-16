"""
Shared Azure AI Foundry client for Vigil agents.

Provides two client singletons:
- AgentsClient: used at startup for agent registration (create/update/list)
- ChatCompletionsClient (per-model): used at runtime for all LLM calls

Both authenticate via DefaultAzureCredential (Entra ID).
"""

import logging
import os

from azure.ai.agents import AgentsClient
from azure.ai.inference import ChatCompletionsClient
from azure.identity import DefaultAzureCredential

logger = logging.getLogger("vigil.foundry_client")

_agents_client: AgentsClient | None = None
_inference_clients: dict[str, ChatCompletionsClient] = {}


def _get_endpoint() -> str:
    """Return the Foundry project endpoint from environment. Raises if not set."""
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "")
    if not endpoint:
        raise ValueError("FOUNDRY_PROJECT_ENDPOINT must be set to your Foundry project endpoint")
    return endpoint


def get_cognitive_endpoint() -> str:
    """Return the base cognitive endpoint used by inference and OCR clients.

    Checks AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT first (explicit override),
    then derives from FOUNDRY_PROJECT_ENDPOINT by stripping /api/projects/<id>.
    """
    endpoint = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "")
    if endpoint:
        return endpoint.rstrip("/")
    # Derive from Foundry project endpoint
    foundry = _get_endpoint().rstrip("/")
    idx = foundry.find("/api/projects/")
    if idx > 0:
        return foundry[:idx]
    raise ValueError(
        "Cannot determine cognitive services endpoint. Set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT "
        "or ensure FOUNDRY_PROJECT_ENDPOINT contains '/api/projects/'."
    )


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


def get_inference_client(model: str | None = None) -> ChatCompletionsClient:
    """Return a ChatCompletionsClient for a specific model deployment (cached per model).

    The Azure AI Inference SDK requires per-deployment endpoints:
      https://<resource>.cognitiveservices.azure.com/openai/deployments/<model>

    Used by all three agents (Indexer, Analyzer, Advisor) and Chat —
    supports any model via single HTTP call per request.
    """
    if model is None:
        model = get_model_name()
    if model in _inference_clients:
        return _inference_clients[model]

    base = get_cognitive_endpoint()
    endpoint = f"{base}/openai/deployments/{model}"
    client = ChatCompletionsClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
        credential_scopes=["https://cognitiveservices.azure.com/.default"],
    )
    _inference_clients[model] = client
    logger.info("ChatCompletionsClient initialized for model '%s' at %s", model, endpoint)
    return client


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
