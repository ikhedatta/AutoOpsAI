"""
AutoOps AI — FastAPI application entry-point.

Wires together: provider, collector, engine, knowledge base, LLM client,
approval router, remediation executor, WebSocket manager, and all API routes.

Run with:  uvicorn agent.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import pathlib

from agent.config import get_settings

logger = logging.getLogger(__name__)

# Global state dict — components register themselves here on startup.
# API routes import this to access the collector, LLM client, etc.
app_state: dict = {}


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()

    # Logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )

    # 1. Database
    from agent.store.database import init_db, close_db
    await init_db(settings)
    logger.info("Database initialized")

    # 2. Provider
    from agent.providers.registry import get_provider
    try:
        provider = get_provider(settings)
        app_state["provider"] = provider
        app_state["provider_type"] = settings.provider_type
        avail = getattr(provider, "available", True)
        logger.info("Provider: %s (available=%s)", provider.provider_name(), avail)
    except Exception:
        logger.warning("Provider creation failed — running in degraded mode", exc_info=True)
        provider = None
        app_state["provider"] = None
        app_state["provider_type"] = settings.provider_type

    # 3. Knowledge base
    from agent.knowledge.knowledge_base import KnowledgeBase
    kb = KnowledgeBase(settings.playbooks_dir)
    app_state["knowledge_base"] = kb
    logger.info("Knowledge base: %d playbooks", len(kb.playbooks))

    # 4. LLM client
    from agent.llm.client import LLMClient
    llm = LLMClient(settings)
    app_state["llm_client"] = llm
    ollama_ok = await llm.is_available()
    app_state["ollama_available"] = ollama_ok
    if ollama_ok:
        await llm.warm_up()
        logger.info("Ollama available: model=%s", settings.ollama_model)
    else:
        logger.warning("Ollama not available — running in playbook-only mode")

    # 5. Engine
    from agent.engine.engine import AgentEngine
    engine = AgentEngine(settings, kb, llm)
    app_state["engine"] = engine

    # 6. WebSocket manager
    from agent.ws.manager import ConnectionManager
    ws_manager = ConnectionManager()
    app_state["ws_manager"] = ws_manager

    # 7. Approval router
    from agent.approval.router import ApprovalRouter
    approval_router = ApprovalRouter(settings)
    approval_router.set_on_event(
        lambda event_type, data: ws_manager.broadcast(event_type, data)
    )
    app_state["approval_router"] = approval_router

    # 8. Remediation executor
    from agent.remediation.executor import RemediationExecutor
    executor = None
    if provider:
        executor = RemediationExecutor(provider)
    app_state["executor"] = executor

    # Wire approval → executor
    async def on_approved(incident_id: str):
        if not executor:
            logger.warning("Executor not available — cannot remediate %s", incident_id)
            await ws_manager.broadcast("incident_failed", {"incident_id": incident_id, "reason": "no_executor"})
            return
        success = await executor.execute(incident_id)
        event = "incident_resolved" if success else "incident_failed"
        await ws_manager.broadcast(event, {"incident_id": incident_id})

    approval_router.set_on_approved(on_approved)

    # 9. Collector
    from agent.collector.collector import MetricsCollector
    collector = None
    if provider:
        collector = MetricsCollector(settings, provider, engine)
        app_state["collector"] = collector
        app_state["collector_running"] = False

        # Auto-start collector
        try:
            await collector.start()
            app_state["collector_running"] = True
        except Exception:
            logger.warning("Collector failed to auto-start (provider may be unavailable)", exc_info=True)
    else:
        app_state["collector"] = None
        app_state["collector_running"] = False
        logger.info("Collector skipped — no provider available")

    logger.info("=== AutoOps AI agent ready ===")

    yield  # App is running

    # Shutdown
    if collector and collector.is_running:
        await collector.stop()
    await close_db()
    logger.info("AutoOps AI agent shut down")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AutoOps AI",
    description="Virtual DevOps Engineer — AI-powered infrastructure agent",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS — allow dashboard origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production (Phase 6)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

from agent.api.routes_system import router as system_router  # noqa: E402
from agent.api.routes_incidents import router as incidents_router  # noqa: E402
from agent.api.routes_approval import router as approval_router  # noqa: E402
from agent.api.routes_playbooks import router as playbooks_router  # noqa: E402
from agent.api.routes_agent import router as agent_router  # noqa: E402
from agent.api.routes_chat import router as chat_router  # noqa: E402

app.include_router(system_router, prefix="/api/v1")
app.include_router(incidents_router, prefix="/api/v1")
app.include_router(approval_router, prefix="/api/v1")
app.include_router(playbooks_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/api/v1/ws/events")
async def websocket_endpoint(ws: WebSocket):
    manager = app_state.get("ws_manager")
    if not manager:
        await ws.close()
        return
    await manager.connect(ws)
    app_state["ws_clients"] = manager.client_count
    try:
        while True:
            # Keep connection alive; client can also send messages
            await ws.receive_text()
            # Could handle client-initiated messages here
    except WebSocketDisconnect:
        manager.disconnect(ws)
        app_state["ws_clients"] = manager.client_count


# ---------------------------------------------------------------------------
# Prometheus metrics endpoint
# ---------------------------------------------------------------------------

@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus scrape endpoint for agent self-monitoring."""
    from agent.store.models import IncidentDoc
    # Simple text-format metrics
    incidents_total = await IncidentDoc.find().count()
    resolved = await IncidentDoc.find({"status": "resolved"}).count()
    pending = await IncidentDoc.find({"status": "awaiting_approval"}).count()

    lines = [
        "# HELP autoops_incidents_total Total incidents created",
        "# TYPE autoops_incidents_total counter",
        f"autoops_incidents_total {incidents_total}",
        "# HELP autoops_incidents_resolved_total Total resolved incidents",
        "# TYPE autoops_incidents_resolved_total counter",
        f"autoops_incidents_resolved_total {resolved}",
        "# HELP autoops_approval_pending_total Currently pending approvals",
        "# TYPE autoops_approval_pending_total gauge",
        f"autoops_approval_pending_total {pending}",
        "# HELP autoops_ws_clients Connected WebSocket clients",
        "# TYPE autoops_ws_clients gauge",
        f"autoops_ws_clients {app_state.get('ws_clients', 0)}",
    ]
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Dashboard static files (served at root)
# ---------------------------------------------------------------------------

_FRONTEND_DIR = pathlib.Path(__file__).parent.parent / "frontend" / "dist"

if _FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """Serve the React SPA for any non-API route."""
        file_path = _FRONTEND_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_FRONTEND_DIR / "index.html")
