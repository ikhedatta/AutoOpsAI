# [Step 13] — Risk Classification

## Context

Steps 01-12 are complete. The following exist:
- `agent/models.py` — `RiskLevel`, `Anomaly`, `Action`
- `agent/knowledge/schemas.py` — `PlaybookEntry`, `PlaybookMatch`
- `agent/engine/__init__.py` — package exists

## Objective

Produce the `RiskClassifier` class that assigns a `RiskLevel` to a proposed action based on service criticality, action type, playbook severity override, and configurable weights.

## Files to Create

- `agent/engine/risk.py` — `RiskClassifier` class.
- `tests/test_risk_classification.py` — Tests covering every path through the classifier.

## Files to Modify

None.

## Key Requirements

**agent/engine/risk.py:**

```python
# Service criticality tiers (higher = more critical)
SERVICE_CRITICALITY: dict[str, int] = {
    # Tier 3 — highest criticality
    "database": 3, "mongodb": 3, "mongodb-demo": 3, "postgres": 3, "mysql": 3,
    # Tier 2
    "app": 2, "api": 2, "demo-app": 2, "backend": 2,
    # Tier 1
    "cache": 1, "redis": 1, "demo-redis": 1, "memcached": 1,
    # Tier 0
    "proxy": 0, "nginx": 0, "autoops-nginx": 0, "haproxy": 0,
}

# Action type weights (higher = riskier)
ACTION_WEIGHTS: dict[str, int] = {
    "collect_logs": 0,
    "collect_diagnostics": 0,
    "health_check": 0,
    "metric_check": 0,
    "wait": 0,
    "exec_command": 1,
    "restart_service": 2,
    "scale_service": 2,
    "stop_service": 3,
    "rollback_service": 3,
    "escalate": 0,
    "provider_command": 2,
}

class RiskClassifier:
    def __init__(
        self,
        service_criticality: dict[str, int] | None = None,
        action_weights: dict[str, int] | None = None,
    ):
        self.service_criticality = service_criticality or SERVICE_CRITICALITY
        self.action_weights = action_weights or ACTION_WEIGHTS

    def classify(
        self,
        action_type: str,
        service_name: str,
        anomaly: Optional[Anomaly] = None,
        playbook_match: Optional[PlaybookMatch] = None,
    ) -> RiskLevel:
        """
        Classify the risk of performing action_type on service_name.

        Priority order (first matching rule wins):
        1. Playbook severity override — if playbook_match is provided,
           use its severity as a floor (minimum risk).
        2. Score-based classification using service_criticality + action_weights.
        3. Anomaly severity hint — if anomaly.severity is HIGH, floor is MEDIUM.

        Score calculation:
            criticality = self.service_criticality.get(service_name, 1)  # default 1
            action_weight = self.action_weights.get(action_type, 1)       # default 1
            score = criticality + action_weight

        Score → RiskLevel:
            score <= 1  → LOW
            score <= 3  → MEDIUM
            score >= 4  → HIGH
        """

    def _service_criticality(self, service_name: str) -> int:
        """
        Look up service criticality. Check exact name, then check if any key
        is a substring of service_name (for partial matches like 'my-mongodb-prod').
        Return 1 (default) if no match.
        """

    def _playbook_severity_to_risk(self, severity_str: str) -> RiskLevel:
        """Convert playbook severity string to RiskLevel."""
```

**Floor logic (playbook severity override):**
If `playbook_match` is provided and its `playbook.severity` is `"HIGH"`, the result must be at least `RiskLevel.HIGH`. If `"MEDIUM"`, at least `RiskLevel.MEDIUM`. This is a floor, not a ceiling — the score can push higher.

**Anomaly severity floor:**
If `anomaly` is not None and `anomaly.severity == RiskLevel.HIGH`, the result floor is `RiskLevel.MEDIUM` (the anomaly being HIGH doesn't automatically make the action HIGH, but it's elevated).

**Service name partial matching:** For a service named `autoops-nginx`, the exact key `"nginx"` should match via substring lookup. Order of preference: exact match first, then substring.

**tests/test_risk_classification.py:**

Required test cases:
1. `test_observe_any_service_is_low` — `collect_logs` on any service = `LOW`.
2. `test_restart_proxy_is_low` — `restart_service` on `nginx` → score = 0+2 = 2 → MEDIUM. (Test that proxy scores lower than DB.)
3. `test_restart_database_is_high` — `restart_service` on `mongodb-demo` → score = 3+2 = 5 → HIGH.
4. `test_restart_app_is_medium` — `restart_service` on `demo-app` → score = 2+2 = 4 → HIGH. (Adjust test to match the score matrix.)
5. `test_stop_database_is_high` — `stop_service` on `mongodb-demo` → score = 3+3 = 6 → HIGH.
6. `test_playbook_severity_floor_medium` — score would be LOW, but playbook says MEDIUM → result is MEDIUM.
7. `test_playbook_severity_floor_high` — score would be MEDIUM, but playbook says HIGH → result is HIGH.
8. `test_unknown_service_defaults_to_one` — service not in map, action weight 2 → score 3 → MEDIUM.
9. `test_partial_service_name_match` — service `"my-mongodb-prod"`, action `restart_service` → matches mongodb tier 3 → HIGH.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_risk_classification.py -v
# Expected: all 9 tests pass

# Spot check
python -c "
from agent.engine.risk import RiskClassifier
from agent.models import RiskLevel

rc = RiskClassifier()

# Database restart must be HIGH
assert rc.classify('restart_service', 'mongodb-demo') == RiskLevel.HIGH, 'DB restart should be HIGH'

# Log collection must be LOW regardless of service
assert rc.classify('collect_logs', 'mongodb-demo') == RiskLevel.LOW, 'Log collect should be LOW'

print('risk classifier spot check passed')
"
```

## Dependencies

- Step 01 (project setup)
- Step 02 (core models — `RiskLevel`, `Anomaly`)
- Step 10 (playbook schemas — `PlaybookMatch`)
