# [Step 12] — Anomaly Detection

## Context

Steps 01-11 are complete. The following exist:
- `agent/models.py` — `Anomaly`, `MetricSnapshot`, `ServiceStatus`, `ServiceState`, `RiskLevel`, `LogEntry`
- `agent/collector/prometheus_client.py` — `PrometheusClient`
- `agent/collector/loki_client.py` — `LokiClient`
- `agent/config.py` — `cpu_high_threshold`, `memory_high_threshold`, `error_rate_high_threshold`
- `agent/engine/__init__.py` — package exists

## Objective

Produce the `AnomalyDetector` class with five detection strategies: threshold-based, duration-based (via Prometheus range queries), rate-based, log-pattern (via Loki), and compound. Returns `list[Anomaly]`.

## Files to Create

- `agent/engine/anomaly.py` — `AnomalyDetector` class.
- `tests/test_anomaly_detection.py` — Unit tests with fixture `MetricSnapshot` data.

## Files to Modify

None.

## Key Requirements

**agent/engine/anomaly.py:**

```python
class AnomalyDetector:
    def __init__(
        self,
        prometheus_client: Optional[PrometheusClient] = None,
        loki_client: Optional[LokiClient] = None,
        cpu_threshold: float = 90.0,
        memory_threshold: float = 85.0,
        error_rate_threshold: float = 50.0,
    ):
        self.prometheus = prometheus_client
        self.loki = loki_client
        self.cpu_threshold = cpu_threshold
        self.memory_threshold = memory_threshold
        self.error_rate_threshold = error_rate_threshold

    async def detect(
        self,
        snapshots: list[MetricSnapshot],
        statuses: list[ServiceStatus],
    ) -> list[Anomaly]:
        """
        Run all detection strategies. Returns deduplicated list of Anomaly.
        Order: threshold → duration → rate → log_pattern → compound
        """

    async def detect_threshold(
        self, snapshots: list[MetricSnapshot], statuses: list[ServiceStatus]
    ) -> list[Anomaly]:
        """
        Check each snapshot against configured thresholds.
        Detects: container_down, high_cpu, high_memory.
        """

    async def detect_duration(self, snapshots: list[MetricSnapshot]) -> list[Anomaly]:
        """
        For each snapshot above threshold, query Prometheus range to verify
        the condition has been sustained for 2 minutes.
        Only fires if prometheus_client is set; returns [] otherwise.
        PromQL: avg_over_time(container_cpu_usage_seconds_total{...}[2m])
        """

    async def detect_rate(self, snapshots: list[MetricSnapshot]) -> list[Anomaly]:
        """
        Detect rapid increase in CPU or memory using Prometheus rate queries.
        Only fires if prometheus_client is set; returns [] otherwise.
        """

    async def detect_log_pattern(self, statuses: list[ServiceStatus]) -> list[Anomaly]:
        """
        Query Loki for error patterns in recent logs.
        Detects: "502 Bad Gateway", "connection refused", "OOM", "panic" patterns.
        Only fires if loki_client is set; returns [] otherwise.
        """

    async def detect_compound(
        self,
        snapshots: list[MetricSnapshot],
        statuses: list[ServiceStatus],
    ) -> list[Anomaly]:
        """
        Detect situations requiring multiple signals:
        e.g., container_down + upstream 5xx errors = cascading failure.
        Currently detects: service_down + dependent_service_high_error_rate.
        """
```

**Threshold detection rules (exact logic):**

- `container_down`: for each `ServiceStatus` with `state in (ServiceState.STOPPED, ServiceState.ERROR)`, create:
  ```python
  Anomaly(
      service_name=status.name,
      anomaly_type="container_down",
      severity=RiskLevel.HIGH,
      message=f"Service '{status.name}' is {status.state.value}",
      evidence=[status.last_error] if status.last_error else [],
  )
  ```

- `high_cpu`: for each `MetricSnapshot` with `cpu_percent >= cpu_threshold`, create:
  ```python
  Anomaly(
      service_name=snapshot.service_name,
      anomaly_type="high_cpu",
      severity=RiskLevel.MEDIUM,
      metric_name="cpu_percent",
      metric_value=snapshot.cpu_percent,
      threshold=cpu_threshold,
      message=f"CPU at {snapshot.cpu_percent:.1f}% (threshold: {cpu_threshold}%)",
  )
  ```

- `high_memory`: for each `MetricSnapshot` with `memory_percent` is not None and `>= memory_threshold`, create similarly.

**Deduplication:** If `detect()` would produce two anomalies of the same `anomaly_type` for the same `service_name`, keep only the one with the higher severity (or the first if equal). Use a `dict` keyed by `(service_name, anomaly_type)`.

**Prometheus range query (detect_duration):** Only emit a duration-based anomaly if the threshold-based detection also fired AND the PromQL range query confirms sustained breach. If Prometheus is unreachable (returns []), do NOT emit the duration anomaly — fall through to threshold-only result.

**Log pattern detection (detect_log_pattern):**

Check for these patterns (use `re.search()`, case-insensitive):
- Pattern `"502 Bad Gateway"` → `anomaly_type="http_502_errors"`, severity `MEDIUM`
- Pattern `"connection refused"` → `anomaly_type="connection_refused"`, severity `MEDIUM`
- Pattern `"out of memory|OOM"` → `anomaly_type="oom_event"`, severity `HIGH`
- Pattern `"panic:|fatal error"` → `anomaly_type="process_panic"`, severity `HIGH`

Query Loki with: `{container=~".+"} |~ "502|connection refused|OOM|panic"` for the last 5 minutes.

**tests/test_anomaly_detection.py:**

All tests `@pytest.mark.asyncio`. Use `datetime.now(timezone.utc)` for snapshot timestamps.

Required test cases:
1. `test_no_anomalies_healthy` — all metrics below thresholds, all services running, assert empty list.
2. `test_container_down_detected` — `ServiceStatus` with `state=STOPPED`, assert one anomaly with `anomaly_type="container_down"`.
3. `test_high_cpu_detected` — `MetricSnapshot` with `cpu_percent=95.0`, assert `anomaly_type="high_cpu"`.
4. `test_high_memory_detected` — snapshot with `memory_percent=90.0`, assert `anomaly_type="high_memory"`.
5. `test_deduplication` — two snapshots for the same service both above CPU threshold, assert only one anomaly returned.
6. `test_log_pattern_no_loki` — loki_client is None, `detect_log_pattern()` returns [].
7. `test_duration_no_prometheus` — prometheus_client is None, `detect_duration()` returns [].
8. `test_multiple_anomalies` — one service down + one service high CPU, assert two distinct anomalies.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_anomaly_detection.py -v
# Expected: all 8 tests pass

# Verify imports
python -c "
from agent.engine.anomaly import AnomalyDetector
from agent.models import Anomaly, MetricSnapshot, ServiceStatus, ServiceState, RiskLevel
print('anomaly detection imports OK')
"
```

## Dependencies

- Step 01 (project setup)
- Step 02 (core models — `Anomaly`, `MetricSnapshot`, `ServiceStatus`, `ServiceState`, `RiskLevel`)
- Step 07 (observability clients — `PrometheusClient`, `LokiClient`)
