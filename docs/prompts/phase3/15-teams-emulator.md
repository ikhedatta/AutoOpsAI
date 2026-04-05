# [Step 15] — Teams Local Emulator

## Context

Steps 01-14 are complete. The following exist:
- `agent/models.py` — `RiskLevel`, `ApprovalStatus`, `IncidentStatus`
- `agent/store/documents.py` — `IncidentDocument`, `ApprovalDocument`
- `agent/config.py` — `teams_local_emulator: bool`
- `agent/approval/__init__.py` — package exists

## Objective

Produce a local emulator for the Teams approval flow that stores approval cards in memory and exposes a web UI plus REST endpoints for approving/denying in development. Activated only when `TEAMS_LOCAL_EMULATOR=true`.

## Files to Create

- `agent/approval/teams_emulator.py` — In-memory card store, FastAPI router, HTML renderer, state machine.
- `tests/test_teams_emulator.py` — Tests for all card state transitions.

## Files to Modify

None. (The router is mounted in step 22.)

## Key Requirements

**agent/approval/teams_emulator.py:**

The emulator must expose a `FastAPI APIRouter` named `emulator_router` that is mounted **only** when `settings.teams_local_emulator is True`. This check happens in `agent/main.py` (step 22), not here.

**Card data model:**
```python
class EmulatorCard(BaseModel):
    incident_id: str
    title: str
    severity: str               # RiskLevel value
    service: str
    diagnosis: str
    proposed_action: str
    rollback_plan: Optional[str]
    risk_level: str
    requested_at: datetime
    timeout_at: Optional[datetime]      # None for HIGH risk
    status: str = "pending"     # "pending", "approved", "denied", "investigating", "timed_out"
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = None
    investigation_detail: Optional[str] = None
```

**In-memory store:**
```python
# Module-level dict — persists for the lifetime of the process
_card_store: dict[str, EmulatorCard] = {}

def add_card(card: EmulatorCard) -> None:
    _card_store[card.incident_id] = card

def get_card(incident_id: str) -> Optional[EmulatorCard]:
    return _card_store.get(incident_id)

def get_all_cards() -> list[EmulatorCard]:
    return list(_card_store.values())

def update_card_status(incident_id: str, status: str, decided_by: str = "emulator") -> Optional[EmulatorCard]:
    if incident_id not in _card_store:
        return None
    card = _card_store[incident_id]
    card.status = status
    card.decided_at = datetime.now(timezone.utc)
    card.decided_by = decided_by
    return card
```

**FastAPI router endpoints (all prefixed `/dev`):**

```
GET  /dev/teams-cards
    Returns: HTML page listing all cards with their current state.
    HTML must be self-contained (inline CSS, no external dependencies).
    Each card shows: incident_id, title, severity badge, status, diagnosis, proposed_action.
    Pending cards show Approve / Deny / Investigate buttons as HTML forms (POST method).

GET  /dev/teams-cards/{incident_id}
    Returns: JSON representation of a single EmulatorCard.
    404 if not found.

POST /dev/teams-cards/{incident_id}/approve
    Body: {"approved_by": "operator"}  (optional)
    State transition: pending → approved
    Returns: {"status": "approved", "incident_id": incident_id}
    409 if card is not in "pending" or "investigating" state.

POST /dev/teams-cards/{incident_id}/deny
    Body: {"denied_by": "operator", "reason": "optional reason"}
    State transition: pending → denied  (or investigating → denied)
    Returns: {"status": "denied", "incident_id": incident_id}
    409 if already decided.

POST /dev/teams-cards/{incident_id}/investigate
    Body: {}
    State transition: pending → investigating
    Returns: {"status": "investigating", "incident_id": incident_id}
    409 if already in a terminal state (approved/denied/timed_out).
```

**State machine rules:**
- `pending` → can transition to: `approved`, `denied`, `investigating`, `timed_out`
- `investigating` → can transition to: `approved`, `denied`
- `approved`, `denied`, `timed_out` → terminal states, no further transitions allowed (return 409)

**HTML rendering:** The `GET /dev/teams-cards` HTML page must:
- Display a header: "AutoOps AI — Teams Emulator"
- Show each card in a colored block: red border for HIGH, orange for MEDIUM, gray for resolved
- For pending/investigating cards, show inline `<form>` elements with POST buttons
- Show `timeout_at` as a human-readable countdown string if not None
- Status badges: color-coded (pending=amber, approved=green, denied=red, investigating=blue)

**tests/test_teams_emulator.py:**

Use FastAPI `TestClient` (synchronous) or `httpx.AsyncClient` for async. All tests use the emulator router.

Required test cases:
1. `test_add_and_get_card` — add a card via `add_card()`, GET `/dev/teams-cards/{id}` returns it.
2. `test_approve_pending_card` — POST approve on pending card, assert status becomes "approved".
3. `test_deny_pending_card` — POST deny on pending card, assert status becomes "denied".
4. `test_investigate_pending_card` — POST investigate, assert status becomes "investigating".
5. `test_approve_after_investigate` — investigate then approve, assert final status "approved".
6. `test_cannot_approve_already_approved` — approve twice, assert second call returns 409.
7. `test_cannot_transition_from_denied` — deny then approve, assert 409.
8. `test_get_all_cards_html` — GET `/dev/teams-cards`, assert 200 and "AutoOps AI" in body.
9. `test_card_not_found` — GET `/dev/teams-cards/nonexistent`, assert 404.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_teams_emulator.py -v
# Expected: all 9 tests pass

# Verify imports
python -c "
from agent.approval.teams_emulator import emulator_router, add_card, get_card, EmulatorCard
from datetime import datetime, timezone
card = EmulatorCard(
    incident_id='test-001',
    title='Test Incident',
    severity='MEDIUM',
    service='mongodb-demo',
    diagnosis='Test diagnosis',
    proposed_action='Restart service',
    risk_level='MEDIUM',
    requested_at=datetime.now(timezone.utc),
)
add_card(card)
assert get_card('test-001') is not None
print('teams emulator imports and basic operations OK')
"
```

## Dependencies

- Step 01 (project setup, FastAPI installed)
- Step 02 (core models — `RiskLevel`, `ApprovalStatus`)
