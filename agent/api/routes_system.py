"""
System health & status endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter
from agent.store import database as db

router = APIRouter(tags=["system"])


@router.get("/health")
async def health():
    from agent.main import app_state
    prom = app_state.get("prometheus")
    loki = app_state.get("loki")
    grafana = app_state.get("grafana")
    components = {
        "database": await db.health_check(),
        "collector": app_state.get("collector_running", False),
        "provider": app_state.get("provider_type", "unknown"),
        "ollama": app_state.get("ollama_available", False),
        "websocket_clients": app_state.get("ws_clients", 0),
        "prometheus": await prom.is_available() if prom else False,
        "loki": await loki.is_available() if loki else False,
        "grafana": await grafana.is_available() if grafana else False,
    }
    all_healthy = components["database"]
    return {
        "status": "healthy" if all_healthy else "degraded",
        "components": components,
    }


@router.get("/status")
async def service_status():
    from agent.main import app_state
    collector = app_state.get("collector")
    if not collector:
        return {"services": {}, "message": "Collector not initialized"}
    data = await collector.collect_once()
    return {"services": data}


@router.get("/metrics/{service_name}")
async def service_metrics(service_name: str):
    from agent.main import app_state
    provider = app_state.get("provider")
    if not provider:
        return {"error": "Provider not initialized"}
    try:
        metrics = await provider.get_metrics(service_name)
        return metrics.model_dump()
    except Exception as exc:
        return {"error": str(exc)}
