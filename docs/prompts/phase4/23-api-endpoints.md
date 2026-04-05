# [Step 23] — All REST API Endpoints

## Context

Steps 01-22 are complete. The following exist:
- `agent/main.py` — FastAPI app with lifespan; has commented-out router includes for this step
- `agent/store/incidents.py` — `IncidentStore`
- `agent/store/documents.py` — `IncidentDocument`, `ApprovalDocument`, `AuditLogDocument`
- `agent/knowledge/knowledge_base.py` — `KnowledgeBase`
- `agent/api/__init__.py`, `agent/api/routers/__init__.py` — packages exist
- `agent/config.py` — `api_key` field

## Objective

Produce all REST API routers for incidents, agent control, playbooks, metrics, and chat. Wire them into `main.py`. Apply a static `X-API-Key` guard to all state-changing endpoints (POST/PATCH/DELETE/PUT). JWT replaces this in Step 29.

## Files to Create

- `agent/api/routers/incidents.py` — Incidents endpoints.
- `agent/api/routers/agent_control.py` — Agent start/stop/config endpoints.
- `agent/api/routers/playbooks.py` — Playbook CRUD endpoints.
- `agent/api/routers/system.py` — Service metrics detail endpoint.
- `agent/api/routers/chat.py` — Chat/conversation endpoints.
- `agent/api/dependencies.py` — FastAPI dependencies (API key guard, get_engine, get_provider, etc.).
- `tests/test_api_endpoints.py` — Endpoint tests.

## Files to Modify

- `agent/main.py` — Uncomment and add router includes.

## Key Requirements

**agent/api/dependencies.py:**

```python
from fastapi import Request, Header, HTTPException, Depends
from agent.config import get_settings
from agent.engine.engine import AgentEngine
from agent.knowledge.knowledge_base import KnowledgeBase
from agent.providers.base import InfrastructureProvider

def verify_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    """
    Static API key guard for state-changing endpoints.
    Reads API_KEY from settings. If key not set (empty string), allow all.
    Used during Phases 4-5. Replaced by JWT in Phase 6.
    """
    settings = get_settings()
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing X-API-Key header")

def get_engine(request: Request) -> AgentEngine:
    return request.app.state.engine

def get_provider(request: Request) -> InfrastructureProvider:
    return request.app.state.provider

def get_knowledge_base(request: Request) -> KnowledgeBase:
    return request.app.state.knowledge_base
```

**agent/api/routers/incidents.py:**

Prefix: `/api/v1`. All routes return JSON matching api-design.md response shapes.

```python
router = APIRouter(prefix="/api/v1", tags=["incidents"])

@router.get("/incidents")
async def list_incidents(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    service: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """
    List incidents with optional filters.
    Returns: {"incidents": [...], "total": int, "limit": int, "offset": int}
    Each incident: id, title, severity, status, service, detected_at, resolved_at,
    resolution_time_seconds, auto_resolved, playbook_id.
    Sorted by detected_at descending.
    """
    docs, total = await IncidentStore.list(status=status, severity=severity,
                                           service=service, limit=limit, offset=offset)
    return {"incidents": [_serialize_incident(d) for d in docs], "total": total,
            "limit": limit, "offset": offset}

@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str) -> dict:
    """
    Full incident detail: id, title, severity, status, service, timing,
    diagnosis (summary, confidence, llm_reasoning, matched_playbook),
    actions (timeline events), rollback_plan, metrics_at_detection.
    Returns 404 if not found.
    """

@router.post("/incidents/{incident_id}/escalate",
             dependencies=[Depends(verify_api_key)])
async def escalate_incident(incident_id: str, body: dict = Body(...)) -> dict:
    """
    Manually escalate an incident.
    Body: {"reason": "string"} (optional)
    Returns: {"status": "escalated", "incident_id": str}
    Returns 404 if not found, 409 if already resolved/escalated.
    """
```

**agent/api/routers/agent_control.py:**

```python
router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

@router.post("/start", dependencies=[Depends(verify_api_key)])
async def start_agent(request: Request) -> dict:
    """Start the monitoring collector loop if not already running."""
    collector = request.app.state.collector
    await collector.start()
    settings = request.app.state.settings
    return {"status": "started", "polling_interval_seconds": settings.polling_interval_seconds}

@router.post("/stop", dependencies=[Depends(verify_api_key)])
async def stop_agent(request: Request) -> dict:
    """Stop the monitoring collector loop."""
    await request.app.state.collector.stop()
    return {"status": "stopped"}

@router.get("/config")
async def get_config(request: Request) -> dict:
    """
    Return current agent configuration.
    Shape per api-design.md: provider, polling_interval_seconds, risk_thresholds,
    approval (channel, timeout values), llm (provider=ollama, model, ollama_host).
    """
    s = request.app.state.settings
    return {
        "provider": s.provider_type,
        "polling_interval_seconds": s.polling_interval_seconds,
        "risk_thresholds": {
            "cpu_high": s.cpu_high_threshold,
            "memory_high": s.memory_high_threshold,
            "error_rate_high": s.error_rate_high_threshold,
        },
        "approval": {
            "channel": "teams" if not s.teams_local_emulator else "emulator",
            "timeout_medium_seconds": 300,
            "timeout_medium_default": "deny",
            "timeout_high_seconds": None,
        },
        "llm": {
            "provider": "ollama",
            "model": s.ollama_model,
            "ollama_host": s.ollama_host,
            "temperature": 0.1,
        },
    }

@router.patch("/config", dependencies=[Depends(verify_api_key)])
async def update_config(body: dict = Body(...)) -> dict:
    """
    Update runtime config fields. Only these fields are updatable at runtime:
    - polling_interval_seconds (int)
    - cpu_high_threshold (float)
    - memory_high_threshold (float)
    All other fields are ignored (require restart to change).
    Returns {"updated": list[str]} with the fields that were actually changed.
    """
```

**agent/api/routers/playbooks.py:**

```python
router = APIRouter(prefix="/api/v1/playbooks", tags=["playbooks"])

@router.get("")
async def list_playbooks(
    provider: Optional[str] = None,
    severity: Optional[str] = None,
    kb: KnowledgeBase = Depends(get_knowledge_base),
) -> dict:
    """
    List all loaded playbooks with optional filter by provider scope or severity.
    Returns: {"playbooks": [{id, name, severity, provider, detection_type, file}]}
    """

@router.get("/{playbook_id}")
async def get_playbook(playbook_id: str, kb: KnowledgeBase = Depends(get_knowledge_base)) -> dict:
    """
    Full playbook entry as a dict. 404 if not found.
    """

@router.post("", dependencies=[Depends(verify_api_key)])
async def create_playbook(body: dict = Body(...), kb: KnowledgeBase = Depends(get_knowledge_base)) -> dict:
    """
    Write a new playbook YAML file and reload the knowledge base.
    Body: full PlaybookEntry as dict (validated against PlaybookEntry schema).
    File written to playbooks/general/{id}.yaml.
    Returns: {"id": str, "file": str}
    """

@router.put("/{playbook_id}", dependencies=[Depends(verify_api_key)])
async def update_playbook(playbook_id: str, body: dict = Body(...),
                          kb: KnowledgeBase = Depends(get_knowledge_base)) -> dict:
    """
    Overwrite an existing playbook file and reload.
    404 if playbook_id not found.
    """

@router.delete("/{playbook_id}", dependencies=[Depends(verify_api_key)])
async def delete_playbook(playbook_id: str, kb: KnowledgeBase = Depends(get_knowledge_base)) -> dict:
    """
    Delete the playbook file and reload.
    404 if not found. Returns {"deleted": playbook_id}.
    """
```

**agent/api/routers/system.py:**

```python
router = APIRouter(prefix="/api/v1", tags=["system"])

@router.get("/metrics/{service_name}")
async def service_metrics(
    service_name: str,
    provider: InfrastructureProvider = Depends(get_provider),
) -> dict:
    """
    Detailed metrics for one service.
    Calls provider.get_metrics(service_name).
    Returns MetricSnapshot fields as dict per api-design.md.
    404 if service not found in provider.
    """
```

**agent/api/routers/chat.py:**

```python
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

@router.get("/{incident_id}")
async def get_chat_log(incident_id: str) -> dict:
    """
    Return the conversational reasoning log for an incident.
    Derives chat messages from incident.timeline events and diagnosis.

    Message types:
    - role="agent", type="message": status updates from timeline
    - role="agent", type="approval_card": when timeline has "approval_requested" event
      → includes card: {severity, proposed_action, rollback_plan, timeout_at}
    - role="human": when timeline has "approved"/"denied" events (with actor)

    Shape: {"incident_id": str, "messages": [{role, timestamp, content, type?, card?}]}
    """

@router.post("")
async def chat_with_agent(
    body: dict = Body(...),
    engine: AgentEngine = Depends(get_engine),
    provider: InfrastructureProvider = Depends(get_provider),
) -> dict:
    """
    Ask the agent about current system state.
    Body: {"message": "string"}

    Implementation:
    1. Collect current metrics snapshot from provider
    2. Pass to OllamaClient.explain_for_human() with the user's question as context
    3. Return {"response": str, "data": dict | None}

    Falls back to a simple canned response if Ollama is unavailable.
    """
```

**Wire routers in agent/main.py** (modify the commented-out section):

```python
from agent.api.routers.incidents import router as incidents_router
from agent.api.routers.agent_control import router as agent_router
from agent.api.routers.playbooks import router as playbooks_router
from agent.api.routers.system import router as system_router
from agent.api.routers.chat import router as chat_router

app.include_router(incidents_router)
app.include_router(agent_router)
app.include_router(playbooks_router)
app.include_router(system_router)
app.include_router(chat_router)
```

**Error response format (consistent across all endpoints):**

```python
# Use this helper in every router:
def not_found(resource: str, id: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"code": "NOT_FOUND", "message": f"{resource} '{id}' not found"}},
    )
```

**tests/test_api_endpoints.py:**

Use `httpx.AsyncClient` with `ASGITransport`. Mock `IncidentStore`, `KnowledgeBase`, and provider calls. All tests `@pytest.mark.asyncio`.

Required test cases:
1. `test_list_incidents_empty` — `GET /api/v1/incidents`, assert 200 and `"incidents": []`.
2. `test_get_incident_not_found` — `GET /api/v1/incidents/fake_id`, assert 404 with `"error"` envelope.
3. `test_list_incidents_filter_by_status` — insert mock docs, filter by `status=active`, assert only active returned.
4. `test_playbooks_list` — `GET /api/v1/playbooks`, assert 200 and `"playbooks"` key.
5. `test_agent_config` — `GET /api/v1/agent/config`, assert `"llm.provider"` == `"ollama"`.
6. `test_api_key_guard_missing` — `POST /api/v1/agent/stop` with no X-API-Key (when key is set), assert 403.
7. `test_api_key_guard_valid` — same endpoint with correct key, assert 200.
8. `test_service_metrics_not_found` — `GET /api/v1/metrics/nonexistent`, assert 404.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_api_endpoints.py -v
# Expected: all 8 tests pass

python -c "
from agent.api.routers.incidents import router as r1
from agent.api.routers.agent_control import router as r2
from agent.api.routers.playbooks import router as r3
from agent.api.routers.system import router as r4
from agent.api.routers.chat import router as r5
from agent.api.dependencies import verify_api_key, get_engine, get_provider
print('all API router imports OK')
"
```

## Dependencies

- Step 08 (IncidentDocument, ApprovalDocument)
- Step 10 (KnowledgeBase, PlaybookEntry)
- Step 14 (AgentEngine)
- Step 20 (IncidentStore)
- Step 22 (FastAPI app, app.state injection pattern)
