"""
Approval endpoints — pending list, approve/deny/investigate.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent.api.dependencies import verify_api_key
from agent.approval.card_builder import build_approval_card
from agent.models import ApprovalDecision, ApprovalDecisionType
from agent.store import incidents as incident_store
from agent.store.models import ApprovalDoc

router = APIRouter(prefix="/approval", tags=["approval"])


class DecisionBody(BaseModel):
    user: str = "operator"
    reason: str = ""


@router.get("/pending")
async def pending_approvals():
    approvals = await ApprovalDoc.find(
        {"decision": None},
    ).sort("-created_at").to_list()

    cards = []
    for appr in approvals:
        doc = await incident_store.get_incident(appr.incident_id)
        if doc:
            cards.append(build_approval_card(doc, appr))
    return cards


@router.post("/{incident_id}/approve", dependencies=[Depends(verify_api_key)])
async def approve(incident_id: str, body: DecisionBody):
    from agent.main import app_state

    approval_router = app_state.get("approval_router")
    if not approval_router:
        raise HTTPException(status_code=503, detail="Approval router not initialized")

    decision = ApprovalDecision(
        incident_id=incident_id,
        decision=ApprovalDecisionType.APPROVE,
        decided_by=body.user,
        reason=body.reason or "Approved",
    )
    doc = await approval_router.process_decision(incident_id, decision)
    if not doc:
        raise HTTPException(status_code=404, detail="Incident not found")

    await incident_store.add_chat_message(
        incident_id, "user",
        f"✅ **Approved** by {body.user}" + (f": {body.reason}" if body.reason else ""),
    )
    return {"status": "approved", "incident_id": incident_id}


@router.post("/{incident_id}/deny", dependencies=[Depends(verify_api_key)])
async def deny(incident_id: str, body: DecisionBody):
    from agent.main import app_state

    approval_router = app_state.get("approval_router")
    if not approval_router:
        raise HTTPException(status_code=503, detail="Approval router not initialized")

    decision = ApprovalDecision(
        incident_id=incident_id,
        decision=ApprovalDecisionType.DENY,
        decided_by=body.user,
        reason=body.reason or "Denied",
    )
    doc = await approval_router.process_decision(incident_id, decision)
    if not doc:
        raise HTTPException(status_code=404, detail="Incident not found")

    await incident_store.add_chat_message(
        incident_id, "user",
        f"❌ **Denied** by {body.user}" + (f": {body.reason}" if body.reason else ""),
    )
    return {"status": "denied", "incident_id": incident_id}


@router.post("/{incident_id}/investigate", dependencies=[Depends(verify_api_key)])
async def investigate(incident_id: str, body: DecisionBody):
    from agent.main import app_state

    approval_router = app_state.get("approval_router")
    if not approval_router:
        raise HTTPException(status_code=503, detail="Approval router not initialized")

    decision = ApprovalDecision(
        incident_id=incident_id,
        decision=ApprovalDecisionType.INVESTIGATE,
        decided_by=body.user,
        reason=body.reason or "Requesting more information",
    )
    doc = await approval_router.process_decision(incident_id, decision)
    if not doc:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Trigger deeper investigation via LLM
    llm = app_state.get("llm_client")
    if llm and doc:
        context = {
            "incident_id": doc.incident_id,
            "title": doc.title,
            "diagnosis_summary": doc.diagnosis_summary,
            "evidence": doc.evidence,
            "status": doc.status,
        }
        system_state = {}
        collector = app_state.get("collector")
        if collector:
            system_state = await collector.collect_once()

        response = await llm.chat(
            f"Investigate incident {doc.incident_id}: {doc.title}. "
            f"Evidence: {doc.evidence}. "
            f"Current diagnosis: {doc.diagnosis_summary}. "
            f"What else should we check?",
            system_state=system_state,
            incident_context=context,
        )
        await incident_store.add_chat_message(
            incident_id, "agent",
            f"🔎 **Investigation results:**\n\n{response}"
        )

    return {"status": "investigating", "incident_id": incident_id}
