# [Step 14] — Agent Engine (Core Loop)

## Context

Steps 01-13 are complete. The following exist:
- `agent/models.py` — all core models including `Anomaly`, `Diagnosis`, `Action`, `RiskLevel`, `IncidentStatus`
- `agent/knowledge/knowledge_base.py` — `KnowledgeBase`
- `agent/llm/client.py` — `OllamaClient`
- `agent/engine/anomaly.py` — `AnomalyDetector`
- `agent/engine/risk.py` — `RiskClassifier`
- `agent/store/documents.py` — `IncidentDocument`, `TimelineEvent`
- `agent/store/database.py` — `init_db()`

## Objective

Produce the `AgentEngine` class that orchestrates one full reasoning cycle: detect anomalies → match playbooks → LLM diagnose → classify risk → deduplicate → write to MongoDB → invoke approval callback.

## Files to Create

- `agent/engine/engine.py` — `AgentEngine` class.
- `tests/test_engine.py` — Unit tests with all dependencies mocked.

## Files to Modify

None.

## Key Requirements

**agent/engine/engine.py:**

```python
class AgentEngine:
    def __init__(
        self,
        detector: AnomalyDetector,
        knowledge_base: KnowledgeBase,
        llm_client: OllamaClient,
        risk_classifier: RiskClassifier,
        on_action_required: Callable[[IncidentDocument, Action], Awaitable[None]],
    ):
        self.detector = detector
        self.knowledge_base = knowledge_base
        self.llm_client = llm_client
        self.risk_classifier = risk_classifier
        self.on_action_required = on_action_required
        # Cooldown tracking: (service_name, anomaly_type) -> last_alerted_at datetime
        self._cooldown_tracker: dict[tuple[str, str], datetime] = {}

    async def process_cycle(
        self,
        snapshots: list[MetricSnapshot],
        statuses: list[ServiceStatus],
    ) -> None:
        """
        One full reasoning cycle. Steps:
        1. Detect anomalies
        2. Filter by cooldown
        3. For each anomaly:
           a. Match playbooks
           b. Deduplicate against active incidents in MongoDB
           c. LLM diagnosis
           d. Classify risk
           e. Build Action
           f. Write IncidentDocument to MongoDB
           g. Call on_action_required callback
        """

    def _is_in_cooldown(self, service_name: str, anomaly_type: str, cooldown_seconds: int) -> bool:
        """
        Returns True if this (service, anomaly_type) was alerted within cooldown_seconds.
        Uses self._cooldown_tracker (in-memory dict, reset on agent restart).
        """

    def _update_cooldown(self, service_name: str, anomaly_type: str) -> None:
        """Record that this (service, anomaly_type) was just alerted."""

    async def _deduplicate(self, service_name: str, anomaly_type: str) -> Optional[IncidentDocument]:
        """
        Query MongoDB for an active (status != resolved, != escalated, != denied)
        incident for the same service_name with the same anomaly_type embedded
        in the incident's proposed_action or title.
        Returns the existing incident if found, else None.
        """

    def _build_action(
        self,
        anomaly: Anomaly,
        playbook_match: Optional[PlaybookMatch],
        risk_level: RiskLevel,
    ) -> Action:
        """
        Build an Action from the best playbook match.
        action_type = first remediation step's action field
        target = anomaly.service_name
        description = human-readable description for approval card
        rollback_plan = playbook.rollback.description if rollback exists
        """

    def _generate_incident_id(self, service_name: str) -> str:
        """Generate a unique incident ID: 'inc_{date}_{random4hex}'"""
        from datetime import datetime, timezone
        import secrets
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        suffix = secrets.token_hex(2)
        return f"inc_{date_str}_{suffix}"
```

**Cooldown logic:**
- Default cooldown: `get_settings().cooldown_default_seconds` (300s)
- Playbook cooldown override: if a matching playbook has `cooldown_seconds` set, use that value instead
- Cooldown key: `(service_name, anomaly_type)` tuple
- Do NOT persist cooldown to MongoDB — it's in-memory by design (reset on restart is acceptable)

**Deduplication logic:**
- Before creating a new incident, query MongoDB:
  ```python
  existing = await IncidentDocument.find_one(
      IncidentDocument.service == service_name,
      IncidentDocument.status.not_in([IncidentStatus.RESOLVED, IncidentStatus.ESCALATED, IncidentStatus.DENIED]),
  )
  ```
- If an active incident already exists for this service, add a `TimelineEvent` to it (type: "re_detected") and skip creating a new incident.
- If no active incident: create a new `IncidentDocument` and save it.

**IncidentDocument creation:**
```python
incident = IncidentDocument(
    incident_id=self._generate_incident_id(anomaly.service_name),
    title=playbook_match.playbook.name if playbook_match else f"Anomaly on {anomaly.service_name}",
    severity=risk_level.value,
    status=IncidentStatus.ACTIVE.value,
    service=anomaly.service_name,
    playbook_id=playbook_match.playbook.id if playbook_match else None,
    detected_at=anomaly.detected_at,
    diagnosis_summary=diagnosis.summary,
    diagnosis_confidence=diagnosis.confidence,
    llm_reasoning=diagnosis.llm_reasoning,
    proposed_action=action.description,
    rollback_plan=action.rollback_plan,
    metrics_at_detection={s.service_name: s.model_dump() for s in snapshots[:5]},
    timeline=[
        TimelineEvent(
            timestamp=anomaly.detected_at,
            event_type="detected",
            actor="agent",
            detail=anomaly.message,
        )
    ],
)
await incident.insert()
```

**Action routing callback:**
After saving the incident, call `await self.on_action_required(incident, action)`. This callback is injected — the engine does not know about Teams, dashboard, or Celery directly.

**Error handling:** If the LLM call fails, fall back to playbook diagnosis (step 11 already handles this). If MongoDB write fails, log the error but still call the callback with a temporary in-memory incident object. The system must not crash on DB failures.

**tests/test_engine.py:**

Mock all dependencies with `AsyncMock` and `MagicMock`. All tests `@pytest.mark.asyncio`.

Required test cases:
1. `test_no_anomaly_no_action` — empty snapshots/statuses, detector returns [], assert callback never called.
2. `test_anomaly_triggers_cycle` — detector returns one anomaly, assert callback called once with correct incident_id format.
3. `test_cooldown_prevents_duplicate` — run `process_cycle` twice with same anomaly, assert callback called only once.
4. `test_cooldown_expires` — manipulate `_cooldown_tracker` to set timestamp 400s ago, run again, assert callback called again.
5. `test_deduplication_active_incident` — mock `IncidentDocument.find_one` to return an existing incident, assert a new insert is NOT called.
6. `test_llm_failure_falls_back` — `llm_client.diagnose` raises, assert cycle completes and callback is still called.
7. `test_incident_written_to_db` — mock `IncidentDocument.insert`, assert it's called once with correct fields.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_engine.py -v
# Expected: all 7 tests pass

# Verify imports
python -c "
from agent.engine.engine import AgentEngine
print('agent engine imports OK')
"
```

## Dependencies

- Step 02 (core models)
- Step 08 (MongoDB documents — `IncidentDocument`, `TimelineEvent`)
- Step 10 (playbook system — `KnowledgeBase`, `PlaybookMatch`)
- Step 11 (LLM client — `OllamaClient`)
- Step 12 (anomaly detection — `AnomalyDetector`)
- Step 13 (risk classification — `RiskClassifier`)
