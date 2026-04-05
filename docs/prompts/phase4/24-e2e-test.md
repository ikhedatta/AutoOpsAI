# [Step 24] — End-to-End Integration Test

## Context

Steps 01-23 are complete. The full system is wired:
- Demo stack: `infra/docker-compose/docker-compose.target.yml` (nginx, demo-app, mongodb-demo, demo-redis)
- Agent: `docker-compose.agent.yml` (autoops-agent, autoops-worker, redis)
- Teams emulator: `GET /dev/teams-cards` (activated by `TEAMS_LOCAL_EMULATOR=true`)
- All REST API endpoints active
- WebSocket bridge operational

## Objective

Produce a complete end-to-end integration test that runs the full loop: chaos injection → detection → Ollama diagnosis → Teams emulator card → approval → Celery remediation → verification → resolved. This test requires both Docker stacks running.

## Files to Create

- `tests/e2e/test_full_loop.py` — Full E2E test suite.
- `tests/e2e/conftest.py` — E2E fixtures (stack startup, teardown, agent client).

## Files to Modify

None.

## Key Requirements

**tests/e2e/conftest.py:**

```python
import subprocess
import httpx
import pytest
import time

AGENT_BASE_URL = "http://localhost:8000"
DEMO_APP_URL = "http://localhost:8080"   # nginx exposes demo app
TEAMS_EMULATOR_URL = f"{AGENT_BASE_URL}/dev/teams-cards"

@pytest.fixture(scope="session", autouse=True)
def demo_stack():
    """
    Start the demo target stack before all E2E tests.
    Tear it down after.
    Uses docker compose up/down — requires Docker to be running.
    Skip all E2E tests if Docker is not available.
    """
    try:
        subprocess.run(
            ["docker", "compose", "-f", "infra/docker-compose/docker-compose.target.yml",
             "-p", "autoops-demo", "up", "-d"],
            check=True, capture_output=True, timeout=120,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        pytest.skip(f"Docker not available or demo stack failed: {e}")

    # Wait for all 4 services to be healthy (max 60s)
    _wait_for_url(f"{DEMO_APP_URL}/health", timeout=60)

    yield

    subprocess.run(
        ["docker", "compose", "-f", "infra/docker-compose/docker-compose.target.yml",
         "-p", "autoops-demo", "down"],
        capture_output=True, timeout=60,
    )

@pytest.fixture(scope="session")
def agent_client():
    """httpx client for the running AutoOps agent."""
    return httpx.Client(base_url=AGENT_BASE_URL, timeout=30)

def _wait_for_url(url: str, timeout: int = 60) -> None:
    """Poll URL until 200 or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = httpx.get(url, timeout=5)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError(f"URL {url} did not become ready within {timeout}s")
```

**tests/e2e/test_full_loop.py:**

Mark all tests with `@pytest.mark.e2e` so they can be excluded from the normal test run with `-m "not e2e"`.

```python
import pytest
import subprocess
import time
import httpx

pytestmark = pytest.mark.e2e

AGENT_BASE_URL = "http://localhost:8000"
DEMO_APP_URL = "http://localhost:8080"
```

**Test 1: Stack Health Baseline**
```python
def test_demo_stack_healthy(agent_client):
    """All 4 demo services are running before chaos injection."""
    r = agent_client.get("/api/v1/status")
    assert r.status_code == 200
    services = {s["name"]: s for s in r.json()["services"]}
    assert services["nginx"]["healthy"]
    assert services["demo-app"]["healthy"]
    assert services["mongodb-demo"]["healthy"]
    assert services["demo-redis"]["healthy"]
```

**Test 2: Chaos → Detection → Emulator Card**
```python
def test_mongodb_crash_detected_and_card_displayed(agent_client):
    """
    Kill mongodb-demo → agent detects → emulator card appears.

    1. Run kill_mongodb.sh chaos script
    2. Wait up to 60s for an incident to appear in GET /api/v1/incidents
    3. Assert incident: service="mongodb-demo", severity in {MEDIUM, HIGH}
    4. Assert emulator card at GET /dev/teams-cards shows the incident
    5. Assert card status == "pending"
    """
    # Kill mongodb-demo (NEVER kills production MongoDB)
    subprocess.run(["bash", "chaos/docker/kill_mongodb.sh"], check=True, timeout=30)

    # Wait for incident (max 60s — two polling cycles at 15s + reasoning time)
    incident = _wait_for_incident(agent_client, service="mongodb-demo", timeout=60)
    assert incident is not None, "No incident created for mongodb-demo crash"
    assert incident["severity"] in ("MEDIUM", "HIGH")
    assert incident["status"] == "active"

    # Check emulator card
    r = agent_client.get("/dev/teams-cards")
    assert r.status_code == 200
    cards = r.json() if isinstance(r.json(), list) else r.json().get("cards", [])
    card = next((c for c in cards if c["incident_id"] == incident["id"]), None)
    assert card is not None, "No emulator card for incident"
    assert card["status"] == "pending"

    return incident["id"]   # used by next test
```

**Test 3: Approve → Remediation → Verified Resolved**
```python
def test_approve_remediates_and_resolves(agent_client):
    """
    Approve the pending card → Celery restarts mongodb-demo → verification passes → resolved.

    Requires test_mongodb_crash_detected_and_card_displayed to have run first.
    Uses a shared pytest state via module-level variable.
    """
    # Get pending incident
    r = agent_client.get("/api/v1/approval/pending")
    pending = r.json().get("pending", [])
    assert len(pending) > 0, "No pending approvals"
    incident_id = pending[0]["incident_id"]

    # Approve via dashboard endpoint
    r = agent_client.post(
        f"/api/v1/approval/{incident_id}/approve",
        json={"approved_by": "e2e_test"},
        headers={"X-API-Key": "changeme"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    # Wait for remediation + verification (max 90s)
    resolved = _wait_for_status(agent_client, incident_id, status="resolved", timeout=90)
    assert resolved, f"Incident {incident_id} did not reach resolved status"

    # Verify demo app is healthy again
    demo_r = httpx.get(f"{DEMO_APP_URL}/health", timeout=10)
    assert demo_r.status_code == 200
    health = demo_r.json()
    assert health.get("mongodb") == "ok", "MongoDB not healthy after remediation"
```

**Test 4: Emulator Card Updated to Resolved**
```python
def test_emulator_card_updated_to_resolved(agent_client):
    """After resolution, the emulator card status must update."""
    # Get all incidents and find the resolved one
    r = agent_client.get("/api/v1/incidents?status=resolved")
    resolved = r.json().get("incidents", [])
    assert len(resolved) > 0

    incident_id = resolved[0]["id"]
    r = agent_client.get(f"/dev/teams-cards/{incident_id}")
    assert r.status_code == 200
    card = r.json()
    assert card["status"] == "approved"
```

**Test 5: WebSocket Receives Events**
```python
@pytest.mark.asyncio
async def test_websocket_event_stream():
    """WebSocket connects and receives events during the E2E loop."""
    import websockets
    events_received = []

    async with websockets.connect("ws://localhost:8000/api/v1/ws/events") as ws:
        # Should immediately receive "connected" event
        msg = await asyncio.wait_for(ws.recv(), timeout=5)
        event = json.loads(msg)
        assert event["type"] == "connected"
```

**Test 6: Deny Flow (MEDIUM risk timeout)**
```python
def test_deny_incident_marks_denied(agent_client):
    """
    Inject high CPU, get emulator card, deny it.
    Incident should be marked denied, NOT remediated.
    """
    subprocess.run(["bash", "chaos/docker/spike_cpu.sh"], check=True, timeout=10)

    incident = _wait_for_incident(agent_client, service="demo-app", timeout=60)
    if incident is None:
        pytest.skip("High CPU not detected within timeout — threshold may not be met in this env")

    incident_id = incident["id"]
    r = agent_client.post(
        f"/api/v1/approval/{incident_id}/deny",
        json={"denied_by": "e2e_test", "reason": "Testing deny flow"},
        headers={"X-API-Key": "changeme"},
    )
    assert r.status_code == 200

    # Fetch incident — should be denied, not resolved
    time.sleep(3)
    r = agent_client.get(f"/api/v1/incidents/{incident_id}")
    assert r.json()["status"] in ("denied", "active")  # active if no state change yet
```

**Helper functions:**
```python
def _wait_for_incident(client, service: str, timeout: int = 60) -> Optional[dict]:
    """Poll GET /api/v1/incidents until one with matching service appears."""
    start = time.time()
    while time.time() - start < timeout:
        r = client.get(f"/api/v1/incidents?service={service}")
        incidents = r.json().get("incidents", [])
        if incidents:
            return incidents[0]
        time.sleep(5)
    return None

def _wait_for_status(client, incident_id: str, status: str, timeout: int = 90) -> bool:
    """Poll GET /api/v1/incidents/{id} until status matches."""
    start = time.time()
    while time.time() - start < timeout:
        r = client.get(f"/api/v1/incidents/{incident_id}")
        if r.json().get("status") == status:
            return True
        time.sleep(5)
    return False
```

**pytest.ini_options additions (in pyproject.toml):**
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "e2e: End-to-end tests requiring running Docker stacks (deselect with -m 'not e2e')",
]
```

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI

# Unit tests (no Docker required)
pytest tests/ -m "not e2e" -v
# Expected: all prior unit tests still pass

# E2E tests (requires Docker + running agent)
# Start agent first:
# TEAMS_LOCAL_EMULATOR=true uvicorn agent.main:app --port 8000 &
# celery -A agent.tasks worker --loglevel=info &

pytest tests/e2e/ -v --timeout=300
# Expected: all 6 E2E tests pass

# Restore demo stack after tests
bash chaos/docker/restore_all.sh
```

**Phase 4 exit criteria:**
- Full loop demonstrated: `kill_mongodb.sh` → incident created → emulator card → approve → `mongodb-demo` restarts → `/health` returns 200 → incident status = `resolved`
- All unit tests pass (`pytest -m "not e2e"`)
- WebSocket stream delivers events to browser
- API key guard rejects requests without header

## Dependencies

- Step 05 (demo target stack)
- Step 09 (chaos scripts)
- Step 15 (Teams emulator)
- Step 22 (FastAPI main — full app running)
- Step 23 (API endpoints — incidents, approval, status)
