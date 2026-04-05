"""
Chat endpoints — interactive conversation with the virtual DevOps engineer.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.api.dependencies import verify_api_key
from agent.store import incidents as incident_store

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    question: str
    incident_id: str | None = None


@router.get("/{incident_id}")
async def get_chat(incident_id: str):
    """Get the full conversation log for an incident."""
    messages = await incident_store.get_chat_history(incident_id)
    if not messages:
        raise HTTPException(status_code=404, detail="No conversation found")
    return [
        {
            "role": m.role,
            "content": m.content,
            "timestamp": m.timestamp.isoformat(),
            "metadata": m.metadata,
        }
        for m in messages
    ]


@router.post("", dependencies=[Depends(verify_api_key)])
async def ask_agent(body: ChatMessage):
    """Ask the agent about current system state or an incident."""
    from agent.main import app_state

    llm = app_state.get("llm_client")
    if not llm:
        raise HTTPException(status_code=503, detail="LLM not available")

    # Build system state context
    system_state = {}
    collector = app_state.get("collector")
    if collector:
        system_state = await collector.collect_once()

    # Build incident context if specified
    incident_context = None
    if body.incident_id:
        doc = await incident_store.get_incident(body.incident_id)
        if doc:
            incident_context = {
                "incident_id": doc.incident_id,
                "title": doc.title,
                "status": doc.status,
                "diagnosis_summary": doc.diagnosis_summary,
                "evidence": doc.evidence,
            }

    # Query the LLM
    response = await llm.chat(
        question=body.question,
        system_state=system_state,
        incident_context=incident_context,
    )

    # Save to chat history if tied to an incident
    if body.incident_id:
        await incident_store.add_chat_message(
            body.incident_id, "user", body.question
        )
        await incident_store.add_chat_message(
            body.incident_id, "agent", response
        )

    return {
        "response": response,
        "incident_id": body.incident_id,
    }


@router.post("/stream", dependencies=[Depends(verify_api_key)])
async def stream_chat(body: ChatMessage):
    """SSE streaming chat — tokens arrive as server-sent events."""
    from agent.main import app_state

    llm = app_state.get("llm_client")
    if not llm:
        raise HTTPException(status_code=503, detail="LLM not available")

    system_state = {}
    collector = app_state.get("collector")
    if collector:
        system_state = await collector.collect_once()

    incident_context = None
    if body.incident_id:
        doc = await incident_store.get_incident(body.incident_id)
        if doc:
            incident_context = {
                "incident_id": doc.incident_id,
                "title": doc.title,
                "status": doc.status,
                "diagnosis_summary": doc.diagnosis_summary,
                "evidence": doc.evidence,
            }

    async def event_generator():
        full_response = []
        async for token in llm.chat_stream(
            question=body.question,
            system_state=system_state,
            incident_context=incident_context,
        ):
            full_response.append(token)
            yield f"data: {json.dumps({'token': token})}\n\n"

        # Final event with full response
        complete = "".join(full_response)
        yield f"data: {json.dumps({'done': True, 'full_response': complete})}\n\n"

        # Save to chat history if tied to an incident
        if body.incident_id:
            await incident_store.add_chat_message(
                body.incident_id, "user", body.question
            )
            await incident_store.add_chat_message(
                body.incident_id, "agent", complete
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
