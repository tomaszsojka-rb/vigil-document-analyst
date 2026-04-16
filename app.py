"""
Vigil – Document Analyst — Web Server & Orchestrator
Serves the modern UI and orchestrates the 3-agent pipeline.
"""

import logging
import os
from pathlib import Path

from aiohttp import web
from dotenv import load_dotenv

load_dotenv(override=False)

from agents import ensure_agents
from middleware import security_headers_middleware
from routes import MAX_REQUEST_SIZE_BYTES
from routes.upload import handle_upload
from routes.pipeline import handle_run, handle_job_status, handle_job_stream
from routes.chat import handle_chat

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("vigil")

# Suppress verbose Azure SDK HTTP request/response logging
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)

STATIC_DIR = Path(__file__).parent / "static"
PORT = int(os.getenv("VIGIL_PORT", "3000"))


# ─── Static files & SPA ───────────────────────────────────────

async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


# ─── App factory ──────────────────────────────────────────────

async def on_startup(app: web.Application):
    """Register all three agents in Azure AI Foundry on app startup."""
    logger.info("Registering agents in Azure AI Foundry...")
    agent_ids = await ensure_agents()
    app["agent_ids"] = agent_ids
    logger.info("Agents registered: %s", agent_ids)


async def on_shutdown(app: web.Application):
    """App shutdown handler. Agents are kept persistent in Foundry."""
    logger.info("Shutting down — Foundry agents remain registered.")


def create_app() -> web.Application:
    app = web.Application(
        client_max_size=MAX_REQUEST_SIZE_BYTES,
        middlewares=[security_headers_middleware],
    )
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", handle_index)
    app.router.add_post("/api/upload", handle_upload)
    app.router.add_post("/api/run", handle_run)
    app.router.add_get("/api/job/{job_id}", handle_job_status)
    app.router.add_get("/api/job/{job_id}/stream", handle_job_stream)
    app.router.add_post("/api/chat", handle_chat)
    # CORS preflight for cross-origin deployments
    from middleware import handle_cors_preflight
    app.router.add_route("OPTIONS", "/api/{path:.*}", handle_cors_preflight)
    app.router.add_static("/static", STATIC_DIR)
    return app


if __name__ == "__main__":
    logger.info("═" * 50)
    logger.info("  Vigil – Document Analyst")
    logger.info("  http://localhost:%d", PORT)
    logger.info("═" * 50)
    web.run_app(create_app(), host="0.0.0.0", port=PORT, print=None)
