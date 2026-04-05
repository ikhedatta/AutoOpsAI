"""
Agent control endpoints — start/stop collector, view/patch config.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from agent.api.dependencies import verify_api_key

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/start", dependencies=[Depends(verify_api_key)])
async def start_agent():
    from agent.main import app_state
    collector = app_state.get("collector")
    if not collector:
        return {"error": "Collector not initialized"}
    await collector.start()
    app_state["collector_running"] = True
    return {"status": "started"}


@router.post("/stop", dependencies=[Depends(verify_api_key)])
async def stop_agent():
    from agent.main import app_state
    collector = app_state.get("collector")
    if not collector:
        return {"error": "Collector not initialized"}
    await collector.stop()
    app_state["collector_running"] = False
    return {"status": "stopped"}


@router.get("/config")
async def get_config():
    from agent.config import get_settings
    s = get_settings()
    return {
        "provider_type": s.provider_type,
        "polling_interval_seconds": s.polling_interval_seconds,
        "ollama_model": s.ollama_model,
        "cooldown_seconds": s.cooldown_seconds,
        "approval_timeout_medium_seconds": s.approval_timeout_medium_seconds,
        "playbooks_dir": s.playbooks_dir,
    }
