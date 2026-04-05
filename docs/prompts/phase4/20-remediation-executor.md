# [Step 20] — Remediation Executor

## Context

Steps 01-19 are complete. The following exist:
- `agent/tasks/remediation_task.py` — `execute_remediation` Celery task
- `agent/tasks/verification_task.py` — `run_verification` Celery task
- `agent/tasks/rollback_task.py` — `execute_rollback` Celery task
- `agent/tasks/events.py` — `publish_event()`
- `agent/approval/router.py` — `ApprovalRouter` with `on_execute` callback
- `agent/models.py` — `Action`, `ActionResult`, `RiskLevel`
- `agent/store/documents.py` — `IncidentDocument`
- `agent/knowledge/schemas.py` — `PlaybookEntry`, `RemediationStep`

## Objective

Produce the `RemediationExecutor` — the component that receives an approved `Action`, dispatches Celery tasks, and wires the callback from `ApprovalRouter.on_execute`. Also produce the `IncidentStore` CRUD layer that both the executor and API endpoints use to read/write incidents.

## Files to Create

- `agent/remediation/executor.py` — `RemediationExecutor` class.
- `agent/remediation/rollback.py` — `RollbackManager` (thin wrapper, delegates to Celery).
- `agent/store/incidents.py` — `IncidentStore` CRUD operations on `IncidentDocument`.
- `tests/test_remediation.py` — Unit tests for executor and incident store.

## Files to Modify

None. (Executor is wired in `main.py` step 22.)

## Key Requirements

**agent/remediation/executor.py:**

```python
from agent.models import Action, RiskLevel
from agent.store.documents import IncidentDocument
from agent.tasks.remediation_task import execute_remediation
from agent.tasks.events import publish_event

class RemediationExecutor:
    """
    Receives approved actions and dispatches them to Celery.
    Never executes provider calls directly — always via Celery tasks
    so execution is non-blocking and isolated in the worker process.
    """

    async def execute(self, incident: IncidentDocument, action: Action) -> None:
        """
        Called by ApprovalRouter.on_execute after an action is approved.

        Steps:
        1. Resolve playbook steps from action.playbook_steps
           (if None, build a single step from action.action_type + action.parameters)
        2. Resolve verification steps from action.verification_steps
           (default: one health_check step on action.target_service)
        3. Resolve rollback steps from action.rollback_steps (may be empty list)
        4. Dispatch: execute_remediation.delay(
               incident_id=incident.incident_id,
               action_type=action.action_type,
               action_params=action.parameters,
               playbook_steps=steps,
           )
        5. Update incident timeline: add "remediation_dispatched" event
        6. publish_event("remediation_started", {"incident_id": ..., "action": ...})
        """

    def _resolve_steps(self, action: Action) -> list[dict]:
        """
        Convert Action into a list of step dicts for the Celery task.
        If action.playbook_steps is populated (from PlaybookEntry.remediation.steps),
        serialize those. Otherwise, build a single-step list from action.action_type.
        Each step dict: {"action": str, "target": str, **params}
        """

    def _default_verification_steps(self, service_name: str) -> list[dict]:
        """Return [{"action": "health_check", "target": service_name}]."""
```

**agent/remediation/rollback.py:**

```python
class RollbackManager:
    """
    Triggered by the verification task when post-remediation checks fail.
    Thin wrapper — actual execution is in the Celery rollback_task.
    """

    @staticmethod
    def trigger(incident_id: str, rollback_steps: list[dict]) -> str:
        """
        Dispatch execute_rollback Celery task.
        Returns the Celery task ID.
        Called from inside verification_task (synchronous context).
        """
        from agent.tasks.rollback_task import execute_rollback
        result = execute_rollback.delay(
            incident_id=incident_id,
            rollback_steps=rollback_steps,
        )
        return result.id
```

**agent/store/incidents.py:**

```python
from datetime import datetime
from agent.store.documents import IncidentDocument, TimelineEvent

class IncidentStore:
    """
    Async CRUD layer for IncidentDocument. Used by:
    - AgentEngine (create)
    - RemediationExecutor (update timeline)
    - API endpoints (list, get, escalate)
    - Celery tasks (resolve, update timeline) — called via run_until_complete()
    """

    @staticmethod
    async def create(doc: IncidentDocument) -> IncidentDocument:
        """Insert a new incident document. Returns the saved document."""

    @staticmethod
    async def get(incident_id: str) -> Optional[IncidentDocument]:
        """Fetch by incident_id field (not MongoDB _id)."""

    @staticmethod
    async def list(
        status: Optional[str] = None,
        severity: Optional[str] = None,
        service: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[IncidentDocument], int]:
        """Return (docs, total_count) with optional filters. Sorted by detected_at desc."""

    @staticmethod
    async def update_status(incident_id: str, status: str) -> bool:
        """Set incident.status. Return True if found and updated."""

    @staticmethod
    async def resolve(incident_id: str, resolved_by: str = "agent") -> bool:
        """
        Set status="resolved", resolved_at=now.
        Append a "resolved" TimelineEvent.
        """

    @staticmethod
    async def escalate(incident_id: str, reason: str) -> bool:
        """Set status="escalated". Append escalation TimelineEvent."""

    @staticmethod
    async def add_timeline_event(incident_id: str, event: TimelineEvent) -> bool:
        """
        Push a TimelineEvent into incident.timeline array.
        Use MongoDB $push operator via Motor for atomicity.
        """

    @staticmethod
    async def get_active_for_service(service_name: str, anomaly_type: str) -> Optional[IncidentDocument]:
        """
        Find the most recent active incident for the same service + anomaly_type.
        Used by AgentEngine for deduplication.
        Status filter: status not in {"resolved", "denied", "escalated"}.
        """
```

**Action model extensions (add to agent/models.py):**

The `Action` model needs these fields if not already present. Add them if missing:
```python
class Action(BaseModel):
    action_type: str
    target_service: str
    parameters: dict = {}
    risk_level: RiskLevel = RiskLevel.MEDIUM
    playbook_steps: Optional[list[dict]] = None      # serialized RemediationStep list
    verification_steps: Optional[list[dict]] = None  # post-remediation checks
    rollback_steps: Optional[list[dict]] = None      # from PlaybookEntry.rollback.steps
    description: str = ""
```

**tests/test_remediation.py:**

All tests `@pytest.mark.asyncio`. Use `AsyncMock` for Celery task `.delay()`.

Required test cases:
1. `test_execute_dispatches_celery_task` — mock `execute_remediation.delay`, call `executor.execute()`, assert `.delay()` called once with correct `incident_id`.
2. `test_execute_adds_timeline_event` — assert `IncidentStore.add_timeline_event` called with `"remediation_dispatched"` event.
3. `test_resolve_steps_from_action_type` — action with no `playbook_steps`, assert `_resolve_steps` returns single-item list with correct `"action"` key.
4. `test_resolve_steps_from_playbook` — action with `playbook_steps` populated, assert returned list matches.
5. `test_incident_store_create_and_get` — create a document, fetch by incident_id, assert fields match.
6. `test_incident_store_list_filter_by_status` — insert 3 docs with different statuses, list with `status="active"`, assert only active returned.
7. `test_incident_store_resolve` — create doc, call `resolve()`, fetch, assert status and resolved_at set.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_remediation.py -v
# Expected: all 7 tests pass

python -c "
from agent.remediation.executor import RemediationExecutor
from agent.remediation.rollback import RollbackManager
from agent.store.incidents import IncidentStore
print('remediation imports OK')
"
```

## Dependencies

- Step 02 (core models — `Action`, `ActionResult`)
- Step 08 (MongoDB setup — `IncidentDocument`, `TimelineEvent`)
- Step 10 (playbook schemas — `RemediationStep`)
- Step 18 (approval router — `on_execute` callback pattern)
- Step 19 (Celery tasks — `execute_remediation.delay`)
