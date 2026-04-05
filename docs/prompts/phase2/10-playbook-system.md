# [Step 10] — Playbook System & Knowledge Base

## Context

Steps 01-09 are complete. The following exist:
- `agent/models.py` — `RiskLevel`, `Anomaly`, `MetricSnapshot`, `ServiceStatus`
- `agent/knowledge/__init__.py` — package exists
- `agent/config.py` — `AgentSettings` with `provider_type`

## Objective

Produce the playbook Pydantic schema models, the knowledge base loader/matcher with hot-reload, and all 8 starter playbook YAML files.

## Files to Create

- `agent/knowledge/schemas.py` — Pydantic models for playbook structure.
- `agent/knowledge/knowledge_base.py` — `KnowledgeBase` class: loads YAML, matches anomalies, resolves templates.
- `playbooks/docker_compose/mongodb.yaml`
- `playbooks/docker_compose/redis.yaml`
- `playbooks/docker_compose/nginx.yaml`
- `playbooks/docker_compose/container_oom.yaml`
- `playbooks/general/high_cpu.yaml`
- `playbooks/general/high_memory.yaml`
- `playbooks/general/health_check_failed.yaml`
- `playbooks/general/disk_full.yaml`
- `tests/test_knowledge_base.py` — Unit tests for loading and matching.

## Files to Modify

None.

## Key Requirements

**agent/knowledge/schemas.py:**

```python
class DetectionCondition(BaseModel):
    metric: Optional[str] = None        # e.g. "cpu_percent", "memory_percent"
    service_name: Optional[str] = None  # or "{any}" for wildcard
    threshold: Optional[str] = None     # e.g. "> 90", "< 10", "== 0"
    duration: Optional[str] = None      # e.g. "2m" — requires sustained breach
    state: Optional[str] = None         # for container_health checks: "stopped", "error"
    pattern: Optional[str] = None       # regex for log_pattern checks
    rate: Optional[str] = None          # for log_pattern: e.g. "> 10/min"
    expected_status: Optional[int] = None   # for health_endpoint
    actual: Optional[int] = None
    extra: Optional[dict] = None        # for K8s-specific extra fields

class Detection(BaseModel):
    type: str   # "container_health", "metric_threshold", "log_pattern",
                # "health_endpoint", "compound"
    conditions: list[DetectionCondition] = []
    detectors: Optional[list["Detection"]] = None   # for compound type

class RemediationStep(BaseModel):
    action: str     # "restart_service", "exec_command", "scale_service",
                    # "provider_command", "health_check", "metric_check",
                    # "collect_logs", "collect_diagnostics", "wait", "escalate"
    target: Optional[str] = None
    command: Optional[str] = None
    timeout: Optional[int] = None
    seconds: Optional[int] = None       # for wait action
    message: Optional[str] = None       # for escalate action
    replicas: Optional[int] = None      # for scale_service
    check: Optional[str] = None         # for health_check
    metric: Optional[str] = None        # for metric_check
    expected: Optional[str] = None      # for metric_check threshold
    lines: Optional[int] = None         # for collect_logs
    args: Optional[dict] = None         # for provider_command

class Remediation(BaseModel):
    steps: list[RemediationStep]

class Rollback(BaseModel):
    description: str
    steps: list[RemediationStep]

class PlaybookEntry(BaseModel):
    id: str
    name: str
    severity: str               # RiskLevel value
    detection: Detection
    diagnosis: str
    remediation: Remediation
    provider: Optional[str] = None      # None = universal
    tags: list[str] = []
    cooldown_seconds: int = 300
    rollback: Optional[Rollback] = None
    metadata: dict = {}
    source_file: Optional[str] = None   # Set by loader, not in YAML

class PlaybookMatch(BaseModel):
    playbook: PlaybookEntry
    confidence: float           # 0.0 to 1.0, higher = better match
    matched_service: str
    resolved_variables: dict    # {"{service_name}": "mongodb-demo", etc.}
```

**agent/knowledge/knowledge_base.py:**

```python
class KnowledgeBase:
    def __init__(self, playbooks_dir: str = "playbooks", provider_name: str = "docker_compose"):
        self.playbooks_dir = Path(playbooks_dir)
        self.provider_name = provider_name
        self._playbooks: list[PlaybookEntry] = []
        self._watcher_task: asyncio.Task | None = None

    async def load(self) -> None:
        """Load all playbooks from general/ and {provider_name}/ directories."""

    async def start_hot_reload(self) -> None:
        """Watch playbooks_dir for changes using watchfiles.awatch(), reload on change."""

    async def stop_hot_reload(self) -> None:
        """Cancel the watcher task."""

    def match(
        self,
        anomalies: list[Anomaly],
        snapshots: list[MetricSnapshot],
        statuses: list[ServiceStatus],
    ) -> list[PlaybookMatch]:
        """
        Evaluate all loaded playbooks against the current anomalies and metrics.
        Returns list of PlaybookMatch sorted by confidence descending.
        """

    def get_all(self) -> list[PlaybookEntry]:
        """Return all loaded playbooks."""

    def get_by_id(self, playbook_id: str) -> Optional[PlaybookEntry]:
        """Return playbook by id, or None."""

    def _evaluate_detection(
        self,
        detection: Detection,
        anomaly: Anomaly,
        snapshots: list[MetricSnapshot],
        statuses: list[ServiceStatus],
    ) -> tuple[bool, dict]:
        """
        Returns (matches: bool, resolved_variables: dict).
        Evaluates detection.conditions against the anomaly and current metrics.
        """

    def _evaluate_threshold(self, value: float, threshold_str: str) -> bool:
        """Parse and evaluate a threshold string like '> 90', '< 10', '== 0'."""

    def _resolve_template(self, text: str, variables: dict) -> str:
        """Replace {variable} placeholders in text with values from variables dict."""
```

**Matching logic:**
- For each anomaly, evaluate each playbook's detection against it.
- For `container_health`: match if `anomaly.anomaly_type == "container_down"` and condition's `state` matches.
- For `metric_threshold`: match if `anomaly.metric_name` matches condition's `metric` AND the threshold condition is satisfied.
- For `log_pattern`: match if `anomaly.anomaly_type == "log_pattern"` and service matches.
- For `compound`: all detectors must match (AND logic).
- Provider scoping: only match playbooks with `provider == None` (universal) or `provider == self.provider_name`.
- Confidence: 1.0 for exact service name match, 0.8 for wildcard match (`{any}`).
- Variables dict: always include `{service_name}` → `anomaly.service_name`. Add `{metric_value}` if metric anomaly, `{restart_count}` if in `anomaly.evidence`.

**Hot-reload using watchfiles:**
```python
from watchfiles import awatch
async def _watch_loop(self):
    async for changes in awatch(str(self.playbooks_dir)):
        logger.info("Playbook files changed, reloading...")
        await self.load()
```

**Playbook YAML files (key requirements for each):**

`playbooks/docker_compose/mongodb.yaml`:
- `id: mongodb_container_down`, `severity: MEDIUM`
- Detection: `compound` with `container_health` (service: mongodb-demo, state: stopped) AND `health_endpoint` (demo-app, expected 200, actual 500)
- Remediation: collect_logs → restart_service → wait 5s → health_check (mongosh ping) → health_check (demo-app curl)
- Rollback: collect_logs (200 lines) → collect_diagnostics (df -h) → escalate

`playbooks/docker_compose/redis.yaml`:
- `id: redis_memory_full`, `severity: LOW`
- Detection: `metric_threshold`, memory_percent > 90 on `demo-redis`
- Remediation: exec_command (MEMORY PURGE) → wait 5s → metric_check (memory < 60)

`playbooks/docker_compose/nginx.yaml`:
- `id: nginx_502_errors`, `severity: MEDIUM`
- Detection: `log_pattern`, pattern `"(502|503) "`, service `autoops-nginx`, rate > 5/min
- Remediation: collect_diagnostics (nginx -t) → exec_command (nginx -s reload) → health_check

`playbooks/docker_compose/container_oom.yaml`:
- `id: container_oom_kill`, `severity: HIGH`
- Detection: `container_health`, state error, extra.oom_killed: true
- Remediation: collect_logs → collect_diagnostics (docker inspect) → restart_service → wait 10s → health_check
- Rollback: escalate with full diagnostics

`playbooks/general/high_cpu.yaml`:
- `id: high_cpu_sustained`, `severity: MEDIUM`, provider: null (universal)
- Detection: `metric_threshold`, cpu_percent > 90, service `{any}`, duration: "2m"
- Remediation: collect_diagnostics (top) → collect_logs → restart_service → metric_check (cpu < 50)

`playbooks/general/high_memory.yaml`:
- `id: high_memory_sustained`, `severity: MEDIUM`, provider: null
- Detection: `metric_threshold`, memory_percent > 85, service `{any}`, duration: "5m"
- Remediation: collect_diagnostics (free -m) → collect_logs → restart_service → wait 10s → metric_check (memory < 70)

`playbooks/general/health_check_failed.yaml`:
- `id: health_check_failed`, `severity: HIGH`, provider: null
- Detection: `health_endpoint`, service `{any}`, expected_status: 200
- Remediation: collect_logs → restart_service → wait 10s → health_check
- Rollback: escalate

`playbooks/general/disk_full.yaml`:
- `id: disk_space_critical`, `severity: HIGH`, provider: null
- Detection: `metric_threshold`, disk_usage_percent > 90, service `{any}`
- Remediation: collect_diagnostics (df -h) → collect_diagnostics (du -sh /*) → escalate

**tests/test_knowledge_base.py:**

Required test cases (all sync where possible, async where required):
1. `test_load_playbooks` — create a temp directory with one valid YAML, call `load()`, assert `len(get_all()) == 1`.
2. `test_load_invalid_yaml_skipped` — add an invalid YAML file, assert it doesn't crash and valid ones still load.
3. `test_match_container_down` — create Anomaly with type "container_down", assert mongodb playbook matches.
4. `test_match_metric_threshold` — create Anomaly with type "high_cpu" and cpu_percent 95, assert high_cpu playbook matches.
5. `test_no_match_wrong_provider` — create a K8s-scoped playbook, set provider to "docker_compose", assert it doesn't match.
6. `test_threshold_evaluation` — directly test `_evaluate_threshold` with various inputs.
7. `test_template_resolution` — assert `_resolve_template("Service {service_name} is down", {"{service_name}": "mongodb"}) == "Service mongodb is down"`.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_knowledge_base.py -v
# Expected: all 7 tests pass

# Verify all 8 YAML files load correctly
python -c "
import asyncio
from agent.knowledge.knowledge_base import KnowledgeBase

async def test():
    kb = KnowledgeBase(playbooks_dir='playbooks', provider_name='docker_compose')
    await kb.load()
    all_pb = kb.get_all()
    print(f'Loaded {len(all_pb)} playbooks:')
    for p in all_pb:
        print(f'  - {p.id} ({p.severity}) from {p.source_file}')
    assert len(all_pb) == 8, f'Expected 8, got {len(all_pb)}'
    print('All 8 playbooks loaded OK')

asyncio.run(test())
"
```

## Dependencies

- Step 01 (pyyaml, watchfiles installed)
- Step 02 (core models — `RiskLevel`, `Anomaly`, `MetricSnapshot`, `ServiceStatus`)
