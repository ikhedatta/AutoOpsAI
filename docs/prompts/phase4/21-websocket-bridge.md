# [Step 21] — WebSocket Bridge & Redis Pub/Sub

## Context

Steps 01-20 are complete. The following exist:
- `agent/tasks/events.py` — `publish_event()` (synchronous Redis publisher, used inside Celery tasks)
- `agent/ws/__init__.py` — package exists
- `agent/config.py` — `celery_broker_url` (Redis URL, reused as pub/sub URL)

## Objective

Produce the WebSocket connection manager and the Redis pub/sub subscriber that bridges Celery worker events to browser clients. Celery tasks call `publish_event()` → Redis channel → FastAPI subscriber → WebSocket broadcast to all connected browsers.

## Files to Create

- `agent/ws/manager.py` — `WebSocketManager` class.
- `agent/ws/router.py` — FastAPI `APIRouter` with the `WS /api/v1/ws/events` endpoint.
- `tests/test_websocket_bridge.py` — Unit tests for manager.

## Files to Modify

None. (Router is mounted in `main.py` step 22.)

## Key Requirements

**agent/ws/manager.py:**

```python
import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from fastapi import WebSocket
import redis.asyncio as aioredis
from agent.config import get_settings

REDIS_CHANNEL = "autoops:events"

class WebSocketManager:
    """
    Manages all active WebSocket connections.
    Subscribes to a Redis pub/sub channel and broadcasts events to browsers.

    Lifecycle:
    - Created once at FastAPI startup (in main.py lifespan)
    - start_redis_subscriber() runs as a background asyncio task
    - Connections added/removed as clients connect/disconnect
    """

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._redis: Optional[aioredis.Redis] = None
        self._subscriber_task: Optional[asyncio.Task] = None

    async def connect(self, websocket: WebSocket) -> None:
        """Accept the WebSocket connection and add to active set."""
        await websocket.accept()
        self._connections.add(websocket)
        logger.info("WebSocket connected. Active connections: %d", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket from the active set."""
        self._connections.discard(websocket)
        logger.info("WebSocket disconnected. Active connections: %d", len(self._connections))

    async def broadcast(self, event: dict) -> None:
        """
        Send event JSON to all connected WebSocket clients.
        Stale/closed connections are silently removed during broadcast.
        Never raises — failures are logged and the dead connection is removed.
        """
        if not self._connections:
            return
        message = json.dumps(event)
        dead: set[WebSocket] = set()
        for ws in list(self._connections):
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        self._connections -= dead

    async def start_redis_subscriber(self) -> None:
        """
        Background task: subscribe to Redis channel, call broadcast() for each message.
        Runs indefinitely until cancelled (on FastAPI shutdown).
        Reconnects automatically on Redis connection drops (exponential backoff: 1s, 2s, 4s, max 30s).
        """
        settings = get_settings()
        backoff = 1
        while True:
            try:
                self._redis = aioredis.from_url(
                    settings.celery_broker_url, decode_responses=True
                )
                pubsub = self._redis.pubsub()
                await pubsub.subscribe(REDIS_CHANNEL)
                logger.info("Redis pub/sub subscriber connected to channel: %s", REDIS_CHANNEL)
                backoff = 1  # reset on successful connection
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        try:
                            event = json.loads(message["data"])
                            await self.broadcast(event)
                        except json.JSONDecodeError:
                            logger.warning("Received non-JSON message on channel: %s", message["data"])
            except asyncio.CancelledError:
                logger.info("Redis subscriber cancelled — shutting down")
                break
            except Exception as exc:
                logger.warning("Redis subscriber error: %s. Reconnecting in %ds", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
            finally:
                if self._redis:
                    await self._redis.aclose()

    async def stop(self) -> None:
        """Cancel the background subscriber task. Called on FastAPI shutdown."""
        if self._subscriber_task and not self._subscriber_task.done():
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass

    async def send_direct(self, websocket: WebSocket, event: dict) -> None:
        """Send an event to a single WebSocket connection (used for initial state sync)."""
        try:
            await websocket.send_text(json.dumps(event))
        except Exception as exc:
            logger.warning("Failed to send direct WebSocket message: %s", exc)
            self.disconnect(websocket)
```

**agent/ws/router.py:**

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from agent.ws.manager import WebSocketManager

ws_router = APIRouter()
_manager: Optional[WebSocketManager] = None

def set_manager(manager: WebSocketManager) -> None:
    """Called from main.py to inject the manager instance."""
    global _manager
    _manager = manager

@ws_router.websocket("/api/v1/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    """
    Real-time event stream for the dashboard.

    On connect:
    1. Accept connection
    2. Send initial "connected" event with timestamp
    3. Keep connection alive — events are pushed by broadcast()

    On disconnect (client closes tab or network drops):
    1. Remove from active connections
    2. No error — this is normal

    No authentication on WebSocket during Phases 4-5.
    JWT auth added in Step 30.
    """
    if _manager is None:
        await websocket.close(code=1011)  # Internal error
        return
    await _manager.connect(websocket)
    await _manager.send_direct(websocket, {
        "type": "connected",
        "data": {"message": "AutoOps AI event stream connected"}
    })
    try:
        while True:
            # Keep connection alive — wait for client disconnect signal
            await websocket.receive_text()  # blocks until client sends or disconnects
    except WebSocketDisconnect:
        _manager.disconnect(websocket)
```

**Event schema (consistent across all publishers):**

All events must follow this envelope:
```json
{
  "type": "event_type_string",
  "data": { ... },
  "timestamp": "2026-03-31T10:00:00Z"
}
```

`publish_event()` in `agent/tasks/events.py` must be updated to include `"timestamp"` in the payload using `datetime.utcnow().isoformat() + "Z"`.

**Event types (all used by Celery tasks and agent engine):**
| Event type | Triggered by | Key data fields |
|---|---|---|
| `metric_update` | Collector (every poll) | `service`, `cpu_percent`, `memory_percent`, `healthy` |
| `anomaly_detected` | AgentEngine | `incident_id`, `service`, `anomaly_type`, `severity` |
| `approval_requested` | ApprovalRouter | `incident_id`, `severity`, `proposed_action`, `timeout_at` |
| `approval_decision` | ApprovalRouter | `incident_id`, `decision`, `decided_by` |
| `remediation_started` | RemediationExecutor | `incident_id`, `action` |
| `remediation_step_complete` | remediation_task | `incident_id`, `step`, `result` |
| `remediation_complete` | remediation_task | `incident_id`, `all_succeeded` |
| `verification_passed` | verification_task | `incident_id` |
| `verification_failed` | verification_task | `incident_id` |
| `incident_resolved` | verification_task | `incident_id`, `resolution_time_seconds` |
| `incident_escalated` | rollback_task | `incident_id` |

**tests/test_websocket_bridge.py:**

All tests `@pytest.mark.asyncio`. Use `MagicMock` for WebSocket objects.

Required test cases:
1. `test_connect_adds_to_set` — call `manager.connect(mock_ws)`, assert `mock_ws in manager._connections`.
2. `test_disconnect_removes_from_set` — connect then disconnect, assert not in set.
3. `test_broadcast_sends_to_all_connections` — add 3 mock WebSockets, broadcast, assert all 3 called.
4. `test_broadcast_removes_dead_connections` — one WebSocket raises on `send_text`, broadcast again, assert dead one removed, others still present.
5. `test_broadcast_no_connections_noop` — broadcast with empty set, no exceptions raised.
6. `test_send_direct_single_client` — call `send_direct`, assert only that WebSocket called.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_websocket_bridge.py -v
# Expected: all 6 tests pass

python -c "
from agent.ws.manager import WebSocketManager, REDIS_CHANNEL
from agent.ws.router import ws_router, set_manager
print('WebSocket bridge imports OK')
assert REDIS_CHANNEL == 'autoops:events'
print('Redis channel name OK')
"
```

## Dependencies

- Step 01 (project structure, `agent/ws/__init__.py`)
- Step 19 (events.py — `publish_event`, `REDIS_CHANNEL` constant must match)
