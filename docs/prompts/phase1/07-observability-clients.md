# [Step 07] — Prometheus & Loki Clients

## Context

Steps 01-06 are complete. The following exist:
- `agent/config.py` — `AgentSettings` with `prometheus_url` and `loki_url`
- `agent/models.py` — `LogEntry`
- `agent/collector/__init__.py` — package exists

## Objective

Produce async HTTP clients for querying Prometheus (PromQL) and Loki (LogQL) that are used by the anomaly detector and agent engine for context enrichment. Both clients must degrade gracefully when the observability stack is unreachable.

## Files to Create

- `agent/collector/prometheus_client.py` — `PrometheusClient` class.
- `agent/collector/loki_client.py` — `LokiClient` class.
- `tests/test_observability_clients.py` — Unit tests with mocked `httpx` responses.

## Files to Modify

None.

## Key Requirements

**agent/collector/prometheus_client.py:**

```python
class PrometheusClient:
    def __init__(self, base_url: str, timeout_seconds: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout_seconds)

    async def query(self, promql: str, time: Optional[str] = None) -> list[dict]:
        """
        Execute an instant PromQL query.
        Endpoint: GET /api/v1/query
        Returns the list of result items from the Prometheus JSON response.
        On any error (connection, timeout, non-200 status): logs a WARNING and returns [].
        """

    async def query_range(
        self,
        promql: str,
        start: str,
        end: str,
        step: str = "15s",
    ) -> list[dict]:
        """
        Execute a range PromQL query.
        Endpoint: GET /api/v1/query_range
        Returns the list of result items.
        On any error: logs WARNING, returns [].
        """

    async def check_connection(self) -> bool:
        """
        Returns True if Prometheus is reachable.
        Endpoint: GET /api/v1/status/runtimeinfo
        """
```

- Use `httpx.AsyncClient` with a `with` context manager per request (no persistent connection — the client is called infrequently).
- Parse the standard Prometheus JSON envelope: `{"status": "success", "data": {"result": [...]}}`. Return `response["data"]["result"]`.
- If `status != "success"`, log the error message from `response["error"]` and return `[]`.
- All exceptions (`httpx.RequestError`, `httpx.HTTPStatusError`, `json.JSONDecodeError`) must be caught, logged at WARNING level, and result in returning `[]`.
- Logger name: `agent.collector.prometheus`.

**agent/collector/loki_client.py:**

```python
class LokiClient:
    def __init__(self, base_url: str, timeout_seconds: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout_seconds)

    async def query(
        self,
        logql: str,
        limit: int = 100,
        start: Optional[str] = None,   # Unix nanoseconds as string, or ISO timestamp
        end: Optional[str] = None,
    ) -> list[LogEntry]:
        """
        Execute a LogQL query using the /loki/api/v1/query_range endpoint.
        Returns a list of LogEntry objects.
        On any error: logs WARNING, returns [].
        """

    async def check_connection(self) -> bool:
        """Returns True if Loki is reachable. Endpoint: GET /ready"""
```

- Loki's `query_range` response format:
  ```json
  {
    "status": "success",
    "data": {
      "resultType": "streams",
      "result": [
        {
          "stream": {"container": "demo-app", "level": "error"},
          "values": [["1711900800000000000", "log line text"]]
        }
      ]
    }
  }
  ```
  Each `values` entry is `[nanoseconds_timestamp_string, log_line_string]`. Parse the timestamp as `datetime.fromtimestamp(int(ts_ns) / 1e9, tz=timezone.utc)`. Use the `stream` labels to populate `LogEntry.level` (look for key `"level"` or `"severity"`) and `LogEntry.source` (look for key `"container"` or `"service"`).
- All exceptions caught, logged at WARNING, return `[]`.
- Logger name: `agent.collector.loki`.

**tests/test_observability_clients.py:**

Use `unittest.mock.patch` or `pytest-httpx` (if available) to mock `httpx.AsyncClient`. All tests are `async`.

Required test cases:
1. `test_prometheus_query_success` — mock response returns valid Prometheus envelope, assert result list is returned correctly.
2. `test_prometheus_query_connection_error` — mock raises `httpx.ConnectError`, assert empty list returned and no exception raised.
3. `test_prometheus_query_non_200` — mock response returns HTTP 500, assert empty list returned.
4. `test_loki_query_success` — mock Loki response with one stream and two log lines, assert two `LogEntry` objects returned with correct messages and timestamps.
5. `test_loki_query_connection_error` — mock raises `httpx.ConnectError`, assert empty list returned.
6. `test_prometheus_check_connection_true` — mock returns 200, assert `True`.
7. `test_prometheus_check_connection_false` — mock raises `httpx.ConnectError`, assert `False`.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_observability_clients.py -v
# Expected: all 7 tests pass

# Verify imports
python -c "
from agent.collector.prometheus_client import PrometheusClient
from agent.collector.loki_client import LokiClient
print('observability clients import OK')
"
```

## Dependencies

- Step 01 (project setup, httpx installed)
- Step 02 (core models — `LogEntry`)
- Step 06 (collector package exists — not strictly required but ensures the package structure is in place)
