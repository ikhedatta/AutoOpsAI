"""
Playbook management endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agent.api.dependencies import verify_api_key

router = APIRouter(prefix="/playbooks", tags=["playbooks"])


@router.get("")
async def list_playbooks():
    from agent.main import app_state
    kb = app_state.get("knowledge_base")
    if not kb:
        return []
    return [
        {
            "id": pb.id,
            "name": pb.name,
            "severity": pb.severity.value,
            "provider": pb.provider,
            "tags": pb.tags,
            "detection_type": pb.detection.type,
            "cooldown_seconds": pb.cooldown_seconds,
        }
        for pb in kb.playbooks
    ]


@router.get("/{playbook_id}")
async def get_playbook(playbook_id: str):
    from agent.main import app_state
    kb = app_state.get("knowledge_base")
    if not kb:
        raise HTTPException(status_code=503, detail="Knowledge base not initialized")
    pb = kb.get(playbook_id)
    if not pb:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return pb.model_dump()


@router.post("/reload", dependencies=[Depends(verify_api_key)])
async def reload_playbooks():
    from agent.main import app_state
    kb = app_state.get("knowledge_base")
    if not kb:
        raise HTTPException(status_code=503, detail="Knowledge base not initialized")
    count = kb.reload()
    return {"reloaded": count}
