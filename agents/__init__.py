"""
Vigil agents package.

All three agents (Indexer, Analyzer, Advisor) use direct chat completions
via the Azure AI Inference SDK at runtime for lower latency. They are also
registered in Azure AI Foundry so they appear in the Foundry portal for
visibility and management.

"""

import logging

from foundry_client import get_agents_client

logger = logging.getLogger("vigil.agents")

# Agent IDs populated at startup by ensure_agents()
_agent_ids: dict[str, str] = {}

# Cache of agent names → IDs from a single list_agents() call
_agent_name_cache: dict[str, str] | None = None


def find_agent_by_name(name: str) -> str | None:
    """Search Foundry for an existing agent with the given name. Returns agent ID or None.

    Uses a cached agent list to avoid repeated API calls during startup.
    """
    global _agent_name_cache
    if _agent_name_cache is None:
        client = get_agents_client()
        _agent_name_cache = {}
        for agent in client.list_agents():
            if agent.name:
                _agent_name_cache[agent.name] = agent.id
        logger.info("Cached %d existing Foundry agents", len(_agent_name_cache))

    agent_id = _agent_name_cache.get(name)
    if agent_id:
        logger.info("Found existing Foundry agent '%s': %s", name, agent_id)
    return agent_id


async def ensure_agents() -> dict[str, str]:
    """Register all three agents in Foundry for portal visibility.

    All three agents use direct chat completions at runtime.
    Registration here makes them visible in the Foundry portal.
    """
    from agents.indexer import ensure_indexer_agent
    from agents.analyzer import ensure_analyzer_agent
    from agents.advisor import ensure_advisor_agent

    _agent_ids["indexer"] = ensure_indexer_agent()
    _agent_ids["analyzer"] = ensure_analyzer_agent()
    _agent_ids["advisor"] = ensure_advisor_agent()

    logger.info("All Foundry agents ready: %s", _agent_ids)
    return _agent_ids
