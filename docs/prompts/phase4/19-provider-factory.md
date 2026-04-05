# [Step 19] — Provider Factory & Celery Task Infrastructure

## Context

Steps 01-18 are complete. The following exist:
- `agent/providers/base.py` — `InfrastructureProvider` ABC
- `agent/providers/registry.py` — `register_provider`, `create_provider`
- `agent/providers/docker_compose.py` — `DockerComposeProvider` (auto-registered)
- `agent/tasks/__init__.py` — Celery app (`celery_app`) with `include` list referencing `agent.tasks.remediation_task`, `agent.tasks.verification_task`, `agent.tasks.rollback_task`
- `agent/config.py` — `provider_type`, `provider_project_name`, `provider_compose_file`

## Objective

Produce the provider factory used inside Celery tasks, the three Celery task skeletons (remediation, verification, rollback), and the event publisher. Celery workers are **separate processes** — they cannot use the FastAPI app's in-memory provider instance. The factory is called fresh at the start of every task.

## Files to Create

- `agent/tasks/provider_factory.py` — `get_provider()` factory function.
- `agent/tasks/remediation_task.py` — `execute_remediation` Celery task.
- `agent/tasks/verification_task.py` — `run_verification` Celery task.
- `agent/tasks/rollback_task.py` — `execute_rollback` Celery task.
- `agent/tasks/events.py` — `publish_event()` Redis pub/sub publisher.
- `tests/test_provider_factory.py` — Unit tests for factory.

## Files to Modify

None.

## Key Requirements

**agent/tasks/provider_factory.py:**

```python
from agent.providers.registry import create_provider
from agent.providers.base import InfrastructureProvider
from agent.config import get_settings

def get_provider() -> InfrastructureProvider:
    """
    Instantiate and return the configured InfrastructureProvider.
    Called at the start of every Celery task — workers are separate processes,
    so we cannot share the FastAPI app's in-memory provider instance.
    Reads PROVIDER_TYPE, PROVIDER_PROJECT_NAME, PROVIDER_COMPOSE_FILE from env.
    Returns a fresh provider instance each call (stateless per task).
    """
    settings = get_settings()
    return create_provider(
        settings.provider_type,
        project_name=settings.provider_project_name,
        compose_file=settings.provider_compose_file,
    )
```

`create_provider()` must accept `**kwargs` and pass them to the provider constructor. Update `agent/providers/registry.py` to support this if it doesn't already.

**agent/tasks/events.py:**

```python
import json
import redis
from agent.config import get_settings

REDIS_CHANNEL = "autoops:events"

def publish_event(event_type: str, data: dict) -> None:
    """
    Publish an event to the Redis pub/sub channel consumed by the WebSocket manager.
    Uses a synchronous Redis client (Celery workers are sync by default).
    Safe to call from inside Celery tasks.
    Fails silently on Redis connection error (logs warning, does not crash task).
    """
    settings = get_settings()
    try:
        r = redis.from_url(settings.celery_broker_url, decode_responses=True)
        payload = json.dumps({"type": event_type, "data": data})
        r.publish(REDIS_CHANNEL, payload)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Failed to publish event %s: %s", event_type, exc)
```

Event types to use consistently across tasks:
- `"remediation_started"` — when task begins executing steps
- `"remediation_step_complete"` — after each step
- `"remediation_complete"` — all steps done (success or partial failure)
- `"verification_started"` — verification task begins
- `"verification_passed"` — verification succeeded
- `"verification_failed"` — verification failed, rollback triggered
- `"rollback_started"` — rollback task begins
- `"rollback_complete"` — rollback done
- `"incident_resolved"` — incident status set to resolved
- `"incident_escalated"` — escalated after rollback failure

**agent/tasks/remediation_task.py:**

```python
from celery import shared_task
from agent.tasks.provider_factory import get_provider
from agent.tasks.events import publish_event

@shared_task(
    name="autoops.tasks.execute_remediation",
    bind=True,
    max_retries=0,
    acks_late=True,
    time_limit=300,    # 5-minute hard timeout
    soft_time_limit=240,
)
def execute_remediation(
    self,
    incident_id: str,
    action_type: str,
    action_params: dict,
    playbook_steps: list[dict],
) -> dict:
    """
    Execute remediation steps for an approved incident.

    Flow:
    1. Call get_provider() (fresh instance — Celery process)
    2. Call init_db() to connect to MongoDB inside this worker process
    3. publish_event("remediation_started", ...)
    4. For each step in playbook_steps:
       a. Dispatch to the correct provider method based on step["action"]
       b. Record result in incident timeline (MongoDB)
       c. publish_event("remediation_step_complete", ...)
    5. After all steps: trigger verification_task.delay(incident_id, ...)
    6. Return {"status": "complete", "steps_executed": N, "all_succeeded": bool}

    Action-to-provider mapping (step["action"] values):
    - "restart_service"  → provider.restart_service(step["target"])
    - "exec_command"     → provider.exec_command(step["target"], step["command"])
    - "scale_service"    → provider.scale_service(step["target"], step["replicas"])
    - "collect_logs"     → provider.get_logs(step["target"], lines=step.get("lines", 50))
    - "health_check"     → provider.health_check(step["target"])
    - "wait"             → time.sleep(step.get("seconds", 5))
    - "escalate"         → publish_event("incident_escalated", ...); return early

    Each step result is written to the incident's timeline via MongoDB update.
    If a step fails: log the failure, record in timeline, continue to next step
    (do not abort unless "abort_on_failure": true in step params).
    """
```

**agent/tasks/verification_task.py:**

```python
@shared_task(
    name="autoops.tasks.run_verification",
    bind=True,
    max_retries=1,
    acks_late=True,
    time_limit=120,
)
def run_verification(
    self,
    incident_id: str,
    service_name: str,
    verification_steps: list[dict],
) -> dict:
    """
    Run post-remediation verification checks.

    Flow:
    1. get_provider()
    2. init_db() inside worker
    3. publish_event("verification_started", ...)
    4. For each verification step:
       - "health_check": provider.health_check(service_name) → expect healthy=True
       - "metric_check": provider.get_metrics(service_name) → check threshold
       - "exec_command": provider.exec_command(service_name, cmd) → check exit_code=0
    5. If all pass: update incident status → "resolved", publish_event("verification_passed", ...)
                    update MongoDB: incident.resolved_at = now, incident.status = "resolved"
    6. If any fail: publish_event("verification_failed", ...) → trigger rollback_task.delay(...)
    Return {"verified": bool, "checks": list[dict]}
    """
```

**agent/tasks/rollback_task.py:**

```python
@shared_task(
    name="autoops.tasks.execute_rollback",
    bind=True,
    max_retries=0,
    acks_late=True,
    time_limit=300,
)
def execute_rollback(
    self,
    incident_id: str,
    rollback_steps: list[dict],
) -> dict:
    """
    Execute rollback if verification failed after remediation.

    Flow:
    1. get_provider(), init_db()
    2. publish_event("rollback_started", ...)
    3. Execute rollback steps (same action mapping as remediation)
    4. If rollback succeeds: update incident status → "rolled_back"
    5. If rollback also fails: update status → "escalated",
       publish_event("incident_escalated", ...)
    Return {"status": "rolled_back" | "escalated", "steps_executed": N}
    """
```

**MongoDB writes inside Celery tasks:**

All MongoDB writes use Motor + Beanie. Because Celery workers run in a synchronous context by default, use `asyncio.get_event_loop().run_until_complete()` to call async Beanie methods:

```python
import asyncio
from agent.store.database import init_db

# At start of each task (not at module import time):
loop = asyncio.get_event_loop()
loop.run_until_complete(init_db())

# For DB writes:
loop.run_until_complete(
    IncidentDocument.find_one(IncidentDocument.incident_id == incident_id)
)
```

Alternatively, configure Celery to use `gevent` or `eventlet` pool — but the simpler pattern above is sufficient for this use case.

**tests/test_provider_factory.py:**

Required test cases:
1. `test_get_provider_returns_docker_compose` — mock `get_settings()` with `provider_type="docker_compose"`, assert returns `DockerComposeProvider`.
2. `test_get_provider_unknown_type_raises` — mock `provider_type="unknown"`, assert raises `ValueError` or `KeyError`.
3. `test_get_provider_called_fresh_each_time` — call twice, assert two distinct objects (not cached).

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_provider_factory.py -v
# Expected: all 3 tests pass

python -c "
from agent.tasks.provider_factory import get_provider
from agent.tasks.events import publish_event
from agent.tasks.remediation_task import execute_remediation
from agent.tasks.verification_task import run_verification
from agent.tasks.rollback_task import execute_rollback
print('all task imports OK')
"

# Verify task names are registered
python -c "
from agent.tasks import celery_app
names = list(celery_app.tasks.keys())
assert any('remediation' in n for n in names), 'remediation task not registered'
assert any('verification' in n for n in names), 'verification task not registered'
assert any('rollback' in n for n in names), 'rollback task not registered'
print('task names registered OK')
"
```

## Dependencies

- Step 01 (Celery app, project structure)
- Step 03 (provider interface ABC)
- Step 04 (Docker Compose provider, auto-registered)
- Step 08 (MongoDB / Beanie — `init_db`)
