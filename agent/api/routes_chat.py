"""
Chat endpoints — interactive conversation with the virtual DevOps engineer.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.api.dependencies import verify_api_key
from agent.config import get_settings
from agent.llm.tool_executor import ToolExecutor
from agent.store import incidents as incident_store

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    question: str
    incident_id: str | None = None


GENERAL_CHAT_ID = "_general"


# ── Helpers ────────────────────────────────────────────────────────────────

async def _enrich_with_observability_context(
    system_state: dict, app_state: dict,
) -> dict:
    """Add observability source info to system_state so the LLM knows
    what it can query via tools — even when Docker services are not found."""
    obs: dict = {}
    loki = app_state.get("loki")
    if loki and await loki.is_available():
        containers = await loki.get_label_values("container")
        obs["loki"] = "available"
        obs["loki_containers"] = containers or []
    prom = app_state.get("prometheus")
    if prom and await prom.is_available():
        obs["prometheus"] = "available"
    grafana = app_state.get("grafana")
    if grafana and await grafana.is_available():
        obs["grafana"] = "available"
    if obs:
        system_state["_observability"] = obs
    return system_state


_ROLE_MAP = {"user": "user", "agent": "assistant"}


async def _fetch_recent_history(
    chat_id: str, max_turns: int,
) -> list[dict[str, str]]:
    """Fetch the most recent *max_turns* messages and return as Ollama-
    compatible ``{role, content}`` dicts.

    ``max_turns`` counts individual messages (not pairs), so 10 means
    the last ~5 user+agent exchanges.

    We fetch in descending timestamp order (newest first) and reverse so
    the LLM sees them in chronological order.
    """
    if max_turns <= 0:
        return []
    # get_chat_history sorts ascending — we need the LAST N, so we query
    # descending and reverse.
    from agent.store.models import ChatMessageDoc
    docs = await (
        ChatMessageDoc.find(ChatMessageDoc.incident_id == chat_id)
        .sort("-timestamp")
        .limit(max_turns)
        .to_list()
    )
    docs.reverse()  # back to chronological order
    return [
        {"role": _ROLE_MAP.get(m.role, m.role), "content": m.content}
        for m in docs
    ]


@router.get("/history")
async def get_general_chat_history(limit: int = 200):
    """Get the general (non-incident) chat history."""
    messages = await incident_store.get_chat_history(GENERAL_CHAT_ID, limit=limit)
    return [
        {
            "role": m.role,
            "content": m.content,
            "timestamp": m.timestamp.isoformat(),
            "metadata": m.metadata,
        }
        for m in messages
    ]


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

    # Always include observability source info so the LLM knows what
    # tools are available (even when Docker services are not running).
    system_state = await _enrich_with_observability_context(system_state, app_state)

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

    # Query the LLM (with tools if enabled)
    settings = get_settings()
    chat_id = body.incident_id or GENERAL_CHAT_ID
    history = await _fetch_recent_history(chat_id, settings.chat_history_turns)

    if settings.chat_tool_calling_enabled:
        provider = app_state.get("provider")
        tool_executor = ToolExecutor(
            provider=provider,
            incident_store=incident_store,
            prometheus=app_state.get("prometheus"),
            loki=app_state.get("loki"),
            grafana=app_state.get("grafana"),
        )
        response = await llm.chat_with_tools(
            question=body.question,
            system_state=system_state,
            incident_context=incident_context,
            tool_executor=tool_executor,
            max_iterations=settings.chat_max_tool_iterations,
            history=history,
        )
    else:
        response = await llm.chat(
            question=body.question,
            system_state=system_state,
            incident_context=incident_context,
            history=history,
        )

    # Persist to MongoDB (always — use _general for non-incident chat)
    await incident_store.add_chat_message(chat_id, "user", body.question)
    await incident_store.add_chat_message(chat_id, "agent", response)

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

    system_state = await _enrich_with_observability_context(system_state, app_state)

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
        chat_id = body.incident_id or GENERAL_CHAT_ID
        settings = get_settings()
        history = await _fetch_recent_history(chat_id, settings.chat_history_turns)

        # Use tool-augmented streaming when enabled and the LLM supports it
        if settings.chat_tool_calling_enabled and hasattr(llm, "chat_stream_with_tools"):
            provider = app_state.get("provider")
            tool_executor = ToolExecutor(
                provider=provider,
                incident_store=incident_store,
                prometheus=app_state.get("prometheus"),
                loki=app_state.get("loki"),
                grafana=app_state.get("grafana"),
            )
            token_iter = llm.chat_stream_with_tools(
                question=body.question,
                system_state=system_state,
                incident_context=incident_context,
                tool_executor=tool_executor,
                max_iterations=settings.chat_max_tool_iterations,
                history=history,
            )
        else:
            token_iter = llm.chat_stream(
                question=body.question,
                system_state=system_state,
                incident_context=incident_context,
                history=history,
            )

        async for token in token_iter:
            full_response.append(token)
            yield f"data: {json.dumps({'token': token})}\n\n"

        # Persist to MongoDB before sending the done event
        complete = "".join(full_response)
        await incident_store.add_chat_message(chat_id, "user", body.question)
        await incident_store.add_chat_message(chat_id, "agent", complete)

        # Final event with full response
        yield f"data: {json.dumps({'done': True, 'full_response': complete})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
