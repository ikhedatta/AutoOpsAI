# [Step 22] — FastAPI App & Lifespan

## Context

Steps 01-21 are complete. The following exist:
- All agent packages and components from steps 01-21
- `agent/approval/teams_webhook.py` — `webhook_router`, `set_bot()`
- `agent/approval/dashboard_approval.py` — FastAPI router with `/api/v1/approval/*`
- `agent/approval/teams_emulator.py` — `emulator_router` (registered only when `TEAMS_LOCAL_EMULATOR=true`)
- `agent/ws/router.py` — `ws_router`, `set_manager()`
- `agent/ws/manager.py` — `WebSocketManager`
- `agent/collector/collector.py` — `MetricsCollector`
- `agent/engine/engine.py` — `AgentEngine`
- `agent/knowledge/knowledge_base.py` — `KnowledgeBase`
- `agent/llm/client.py` — `OllamaClient`
- `agent/store/database.py` — `init_db`, `close_db`

## Objective

Produce `agent/main.py` — the FastAPI application factory with full lifespan management: start/stop the collector loop, init MongoDB, warm up Ollama, start Redis pub/sub, wire all component dependencies, and mount all routers.

## Files to Create

- `agent/main.py` — FastAPI app with lifespan, middleware, and router mounting.
- `tests/test_main.py` — Startup/shutdown and health endpoint tests.

## Files to Modify

None.

## Key Requirements

**agent/main.py structure:**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncio
import logging

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.
    All startup code runs before `yield`. All shutdown code runs after.
    """
    settings = get_settings()
    logger.info("AutoOps AI starting up...")

    # 1. Init MongoDB (Beanie ODM)
    await init_db()

    # 2. Init provider
    provider = create_provider(
        settings.provider_type,
        project_name=settings.provider_project_name,
        compose_file=settings.provider_compose_file,
    )

    # 3. Load knowledge base
    kb = KnowledgeBase()
    await kb.load()
    await kb.start_hot_reload()

    # 4. Init Ollama client and warm up
    llm = OllamaClient(
        host=settings.ollama_host,
        model=settings.ollama_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )
    await llm.warm_up()

    # 5. Init WebSocket manager and start Redis subscriber
    ws_manager = WebSocketManager()
    set_ws_manager(ws_manager)   # inject into ws/router.py
    subscriber_task = asyncio.create_task(ws_manager.start_redis_subscriber())
    ws_manager._subscriber_task = subscriber_task

    # 6. Init Teams bot
    from agent.approval.card_builder import CardBuilder
    from agent.approval.teams_bot import TeamsApprovalBot
    from agent.approval.teams_webhook import set_bot
    card_builder = CardBuilder()
    teams_bot = TeamsApprovalBot(card_builder=card_builder, settings=settings)
    set_bot(teams_bot)

    # 7. Init approval router
    from agent.approval.router import ApprovalRouter
    from agent.remediation.executor import RemediationExecutor
    executor = RemediationExecutor()

    async def on_execute(incident, action):
        await executor.execute(incident, action)

    approval_router = ApprovalRouter(
        teams_bot=teams_bot,
        on_execute=on_execute,
        teams_channel_id=settings.teams_webhook_url,
        teams_service_url="",
    )

    # 8. Init agent engine
    from agent.engine.anomaly import AnomalyDetector
    from agent.engine.risk import RiskClassifier
    from agent.collector.prometheus_client import PrometheusClient
    from agent.collector.loki_client import LokiClient

    prom_client = PrometheusClient(base_url=settings.prometheus_url)
    loki_client = LokiClient(base_url=settings.loki_url)

    engine = AgentEngine(
        knowledge_base=kb,
        llm_client=llm,
        anomaly_detector=AnomalyDetector(prom_client, loki_client, settings),
        risk_classifier=RiskClassifier(),
        on_action_required=approval_router.route,
    )

    # 9. Inject engine into state for API access
    app.state.engine = engine
    app.state.provider = provider
    app.state.knowledge_base = kb
    app.state.ws_manager = ws_manager
    app.state.settings = settings

    # 10. Start metrics collector (polling loop)
    async def on_snapshot(snapshots, statuses):
        await engine.process_cycle(snapshots, statuses)
        # Broadcast metric updates to WebSocket clients
        for snap in snapshots:
            await ws_manager.broadcast({
                "type": "metric_update",
                "data": {
                    "service": snap.service_name,
                    "cpu_percent": snap.cpu_percent,
                    "memory_percent": snap.memory_percent,
                },
                "timestamp": snap.timestamp.isoformat() + "Z",
            })

    collector = MetricsCollector(
        provider=provider,
        interval_seconds=settings.polling_interval_seconds,
        on_snapshot=on_snapshot,
    )
    app.state.collector = collector
    await collector.start()

    logger.info("AutoOps AI started. Monitoring %s provider.", settings.provider_type)
    yield

    # Shutdown
    logger.info("AutoOps AI shutting down...")
    await collector.stop()
    await kb.stop_hot_reload()
    await ws_manager.stop()
    await close_db()
    logger.info("AutoOps AI shutdown complete.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="AutoOps AI",
        version="0.1.0",
        description="AI-powered infrastructure remediation agent",
        lifespan=lifespan,
    )

    # CORS — allow dashboard origin (configured via env in production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": str(exc)}},
        )

    # Mount routers (all registered here, not in individual files)
    from agent.approval.teams_webhook import webhook_router
    from agent.approval.dashboard_approval import approval_router as dashboard_approval_router
    from agent.ws.router import ws_router

    app.include_router(webhook_router)
    app.include_router(dashboard_approval_router)
    app.include_router(ws_router)

    # Teams emulator (dev only)
    settings = get_settings()
    if settings.teams_local_emulator:
        from agent.approval.teams_emulator import emulator_router
        app.include_router(emulator_router)

    # API routers (added in step 23)
    # app.include_router(incidents_router, prefix="/api/v1")
    # app.include_router(agent_router, prefix="/api/v1")
    # app.include_router(playbooks_router, prefix="/api/v1")
    # app.include_router(system_router)

    return app

app = create_app()
```

**`GET /health` endpoint (define in main.py directly):**

```python
@app.get("/health")
async def health(request: Request) -> dict:
    """
    Returns component health. Does NOT raise on degraded components —
    always returns 200 with per-component status so the dashboard can display it.
    """
    settings = request.app.state.settings
    from agent.store.database import check_db_health
    from agent.collector.prometheus_client import PrometheusClient

    db_ok = await check_db_health()
    prom_ok = await PrometheusClient(settings.prometheus_url).check_connection()

    return {
        "status": "healthy" if db_ok else "degraded",
        "version": settings.app_version,
        "provider": settings.provider_type,
        "monitoring": True,
        "components": {
            "database": "ok" if db_ok else "error",
            "prometheus": "ok" if prom_ok else "unavailable",
            "ollama": "ok",   # checked at startup; assume warm
        },
    }
```

**`GET /api/v1/status` endpoint (define in main.py directly):**

```python
@app.get("/api/v1/status")
async def status(request: Request) -> dict:
    """All monitored service states — direct provider call."""
    provider = request.app.state.provider
    services = await provider.list_services()
    result = []
    for svc in services:
        s = await provider.get_service_status(svc.name)
        m = await provider.get_metrics(svc.name)
        result.append({
            "name": svc.name,
            "state": s.state.value,
            "cpu_percent": m.cpu_percent if m else 0,
            "memory_percent": m.memory_percent if m else 0,
            "healthy": s.healthy,
            "uptime_seconds": s.uptime_seconds,
            "last_error": s.last_error,
        })
    return {"provider": request.app.state.settings.provider_type, "services": result}
```

**Prometheus `/metrics` endpoint:**

```python
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

@app.get("/metrics")
async def prometheus_metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

Register these Prometheus counters/histograms/gauges at module level (not inside a function):
```python
from prometheus_client import Counter, Histogram, Gauge

incidents_total = Counter("autoops_incidents_total", "Total incidents", ["severity", "status"])
resolution_time = Histogram("autoops_resolution_time_seconds", "Resolution time", buckets=[30, 60, 120, 300, 600])
llm_duration = Histogram("autoops_llm_inference_duration_seconds", "Ollama latency", buckets=[1, 2, 5, 10, 30])
approval_pending = Gauge("autoops_approval_pending_total", "Pending approvals")
anomalies_detected = Counter("autoops_anomalies_detected_total", "Anomalies detected", ["type"])
```

**tests/test_main.py:**

Use `httpx.AsyncClient` with `ASGITransport`. All tests `@pytest.mark.asyncio`.

Required test cases:
1. `test_health_endpoint_returns_200` — `GET /health`, assert status 200 and `"status"` key present.
2. `test_metrics_endpoint_returns_prometheus_format` — `GET /metrics`, assert content-type `text/plain` and body contains `autoops_`.
3. `test_status_endpoint_structure` — `GET /api/v1/status`, assert response has `"provider"` and `"services"` keys.
4. `test_global_exception_handler` — add a test route that raises, assert 500 with `"error"` envelope.
5. `test_websocket_connects` — `WS /api/v1/ws/events`, assert receives `"connected"` event.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_main.py -v
# Expected: all 5 tests pass

# Verify app loads
python -c "from agent.main import app; print('FastAPI app loads OK:', app.title)"
# Expected: FastAPI app loads OK: AutoOps AI
```

## Dependencies

- Steps 01-21 (all prior components)
- Step 06 (MetricsCollector)
- Step 08 (init_db, close_db)
- Step 11 (OllamaClient)
- Step 14 (AgentEngine)
- Step 18 (ApprovalRouter)
- Step 20 (RemediationExecutor)
- Step 21 (WebSocketManager)
