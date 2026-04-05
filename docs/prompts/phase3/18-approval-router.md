# [Step 18] — Approval Router

## Context

Steps 01-17 are complete. The following exist:
- `agent/models.py` — `RiskLevel`, `ApprovalStatus`, `IncidentStatus`, `Action`, `ApprovalDecision`
- `agent/store/documents.py` — `IncidentDocument`, `ApprovalDocument`, `TimelineEvent`
- `agent/approval/teams_bot.py` — `TeamsApprovalBot`
- `agent/tasks/__init__.py` — Celery app (`celery_app`)
- `agent/config.py` — `teams_local_emulator`

## Objective

Produce the `ApprovalRouter` that dispatches incident actions by risk level: auto-execute for LOW, Teams card with 5-minute Celery countdown for MEDIUM, Teams card with no timeout for HIGH. Process approve/deny/investigate decisions from any channel.

## Files to Create

- `agent/approval/router.py` — `ApprovalRouter` class.
- `agent/approval/dashboard_approval.py` — FastAPI router for dashboard-side approval endpoints.
- `agent/tasks/approval_timeout.py` — Celery task for MEDIUM risk timeout.
- `tests/test_approval_router.py` — Tests for all routing paths including timeout.

## Files to Modify

None. (Router is wired in step 22 via `main.py`.)

## Key Requirements

**agent/approval/router.py:**

```python
class ApprovalRouter:
    def __init__(
        self,
        teams_bot: TeamsApprovalBot,
        on_execute: Callable[[IncidentDocument, Action], Awaitable[None]],
        teams_channel_id: str = "",
        teams_service_url: str = "",
    ):
        self.teams_bot = teams_bot
        self.on_execute = on_execute
        self.teams_channel_id = teams_channel_id
        self.teams_service_url = teams_service_url

    async def route(self, incident: IncidentDocument, action: Action) -> None:
        """
        Route the action based on action.risk_level:
        - LOW:    call on_execute() directly, send auto-resolved notification
        - MEDIUM: create ApprovalDocument, send Teams card, schedule Celery timeout task
        - HIGH:   create ApprovalDocument, send Teams card, no timeout
        """

    async def process_decision(
        self,
        incident_id: str,
        decision: str,          # "approve", "deny", "investigate"
        user: Optional[str] = None,
    ) -> ApprovalDecision:
        """
        Process a decision from any channel (Teams, dashboard, webhook).
        Idempotent: if already decided, return existing decision without re-executing.
        On approve: cancel pending Celery timeout task, call on_execute()
        On deny: cancel timeout, update incident status to "denied"
        On investigate: update card to investigating state, request LLM reasoning
        Returns ApprovalDecision with final status.
        """

    async def _create_approval_record(
        self, incident: IncidentDocument, action: Action
    ) -> ApprovalDocument:
        """
        Create and save an ApprovalDocument to MongoDB.
        For MEDIUM: timeout_at = now + 300s
        For HIGH: timeout_at = None
        """

    async def _send_approval_card(
        self, incident: IncidentDocument, approval: ApprovalDocument, action: Action
    ) -> None:
        """
        Send Teams card (or emulator card).
        Store returned activity_id in approval.teams_activity_id.
        """

    async def _cancel_timeout_task(self, incident_id: str) -> None:
        """
        Revoke the Celery timeout task for this incident if one exists.
        Task ID stored in ApprovalDocument.metadata or a separate in-memory dict.
        """
```

**Routing logic for MEDIUM:**
```python
# 1. Create ApprovalDocument with timeout_at = now + 300s
# 2. Send Teams card
# 3. Schedule Celery timeout task:
from agent.tasks.approval_timeout import handle_timeout
task = handle_timeout.apply_async(
    args=[incident.incident_id],
    countdown=300,  # 5 minutes
)
# 4. Store task.id for later cancellation
```

**Routing logic for LOW:**
```python
# 1. Call on_execute() immediately
# 2. Build auto-resolved card
# 3. Send notification (non-blocking, ignore failure)
# 4. Update incident status to "resolved"
```

**Idempotency in `process_decision()`:**
```python
existing = await ApprovalDocument.find_one(ApprovalDocument.incident_id == incident_id)
if existing and existing.status not in ("pending", "investigating"):
    # Already decided — return existing state as-is
    return ApprovalDecision(incident_id=incident_id, status=ApprovalStatus(existing.status))
```

**agent/tasks/approval_timeout.py:**
```python
from agent.tasks import celery_app

@celery_app.task(name="autoops.tasks.approval_timeout", bind=True, task_acks_late=True)
def handle_timeout(self, incident_id: str) -> None:
    """
    Called 5 minutes after a MEDIUM risk approval request if no decision was made.
    1. Load ApprovalDocument from MongoDB (using synchronous Motor or pymongo)
    2. If still pending: update status to "timed_out"
    3. Update incident status to "denied" with note "Timed out — denied by default"
    4. Update Teams card to resolved/timed-out state
    """
    import asyncio
    asyncio.get_event_loop().run_until_complete(_handle_timeout_async(incident_id))

async def _handle_timeout_async(incident_id: str) -> None:
    from agent.store.database import init_db
    from agent.store.documents import ApprovalDocument, IncidentDocument
    await init_db()
    # Find approval, if still pending → update to timed_out
```

Note: Celery tasks run in separate worker processes with no shared state. `init_db()` must be called inside the task.

**agent/approval/dashboard_approval.py:**
This provides the REST API for the React dashboard's approval queue. Uses the same `ApprovalRouter.process_decision()` logic.

```python
dashboard_router = APIRouter(prefix="/api/v1/approval", tags=["approval"])

@dashboard_router.get("/pending")
async def list_pending_approvals() -> dict:
    """Return list of ApprovalDocuments with status="pending"."""

@dashboard_router.post("/{incident_id}/approve")
async def approve_incident(incident_id: str, body: ApproveRequest) -> dict:
    """Call ApprovalRouter.process_decision(incident_id, 'approve', body.approved_by)"""

@dashboard_router.post("/{incident_id}/deny")
async def deny_incident(incident_id: str, body: DenyRequest) -> dict:
    """Call ApprovalRouter.process_decision(incident_id, 'deny', body.denied_by)"""

@dashboard_router.post("/{incident_id}/investigate")
async def investigate_incident(incident_id: str) -> dict:
    """Call ApprovalRouter.process_decision(incident_id, 'investigate')"""
```

The `_router_instance: Optional[ApprovalRouter] = None` module-level variable is set via `set_approval_router(router)` called from `main.py`.

**Request models:**
```python
class ApproveRequest(BaseModel):
    approved_by: str = "operator"

class DenyRequest(BaseModel):
    denied_by: str = "operator"
    reason: Optional[str] = None
```

**tests/test_approval_router.py:**

All tests `@pytest.mark.asyncio`. Mock `TeamsApprovalBot`, Celery tasks, and MongoDB operations.

Required test cases:
1. `test_route_low_executes_immediately` — `action.risk_level=LOW`, assert `on_execute` called, no ApprovalDocument created.
2. `test_route_medium_sends_card` — MEDIUM risk, assert `teams_bot.send_approval_card` called, Celery task scheduled.
3. `test_route_high_no_timeout` — HIGH risk, assert card sent and no Celery task scheduled.
4. `test_approve_decision_calls_execute` — create pending approval, call `process_decision("approve")`, assert `on_execute` called.
5. `test_deny_decision_skips_execute` — deny, assert `on_execute` NOT called.
6. `test_idempotent_double_approve` — call process_decision twice with "approve", assert `on_execute` called only once.
7. `test_timeout_task_runs` — directly call `_handle_timeout_async`, assert approval status set to "timed_out".
8. `test_investigate_transitions_state` — call investigate, assert approval status becomes "investigating".

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_approval_router.py -v
# Expected: all 8 tests pass

# Verify imports
python -c "
from agent.approval.router import ApprovalRouter
from agent.approval.dashboard_approval import dashboard_router
from agent.tasks.approval_timeout import handle_timeout
print('approval router imports OK')
"
```

## Dependencies

- Step 01 (Celery installed)
- Step 02 (core models — `RiskLevel`, `ApprovalStatus`, `Action`)
- Step 08 (MongoDB documents — `ApprovalDocument`, `IncidentDocument`)
- Step 15 (teams emulator)
- Step 17 (teams bot — `TeamsApprovalBot`)
