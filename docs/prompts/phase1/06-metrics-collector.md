# [Step 06] — Metrics Collector

## Context

Steps 01-05 are complete. The following exist:
- `agent/providers/base.py` — `InfrastructureProvider` ABC
- `agent/providers/docker_compose.py` — concrete provider
- `agent/models.py` — `MetricSnapshot`, `HealthCheckResult`, `ServiceInfo`
- `agent/config.py` — `AgentSettings` with `polling_interval_seconds`

## Objective

Produce an async polling loop that discovers services via the provider, collects their metrics and health status every N seconds, and delivers them to a caller-supplied async callback — plus a set of pluggable health probe helpers.

## Files to Create

- `agent/collector/collector.py` — `MetricsCollector` class with async polling loop.
- `agent/collector/health_probes.py` — `HttpProbe`, `TcpProbe`, `CommandProbe` classes and a `run_probe()` dispatcher.
- `tests/test_collector.py` — Unit tests using a mock provider.

## Files to Modify

None.

## Key Requirements

**agent/collector/collector.py:**

```python
class MetricsCollector:
    def __init__(
        self,
        provider: InfrastructureProvider,
        on_snapshot: Callable[[list[MetricSnapshot], list[HealthCheckResult]], Awaitable[None]],
        interval_seconds: int = 15,
    ):
        self.provider = provider
        self.on_snapshot = on_snapshot
        self.interval_seconds = interval_seconds
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background polling loop."""
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Gracefully stop the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._collect_once()
            except Exception as exc:
                logger.warning("Collector cycle error: %s", exc)
            await asyncio.sleep(self.interval_seconds)

    async def _collect_once(self) -> None:
        services = await self.provider.list_services()
        snapshots: list[MetricSnapshot] = []
        health_results: list[HealthCheckResult] = []

        for service in services:
            try:
                snapshot = await self.provider.get_metrics(service.name)
                snapshots.append(snapshot)
            except Exception as exc:
                logger.warning("Failed to get metrics for %s: %s", service.name, exc)

            try:
                health = await self.provider.health_check(service.name)
                health_results.append(health)
            except Exception as exc:
                logger.warning("Failed health check for %s: %s", service.name, exc)

        if snapshots or health_results:
            await self.on_snapshot(snapshots, health_results)
```

- Use Python's `logging` module. Logger name: `agent.collector`.
- The `on_snapshot` callback is injected — the collector does NOT import the engine directly. This keeps the modules decoupled.
- Individual service failures must not stop the loop — catch exceptions per-service, log as WARNING, continue.
- Expose a `is_running` property that returns `self._running`.

**agent/collector/health_probes.py:**

```python
class ProbeConfig(BaseModel):
    probe_type: str             # "http", "tcp", "command"
    url: Optional[str] = None   # for http
    host: Optional[str] = None  # for tcp
    port: Optional[int] = None  # for tcp
    command: Optional[str] = None  # for command
    timeout_seconds: float = 5.0
    expected_status: int = 200  # for http

class HttpProbe:
    async def run(self, service_name: str, config: ProbeConfig) -> HealthCheckResult:
        # Use httpx.AsyncClient with timeout=config.timeout_seconds
        # Return HealthCheckResult with response_time_ms measured

class TcpProbe:
    async def run(self, service_name: str, config: ProbeConfig) -> HealthCheckResult:
        # Use asyncio.open_connection(), measure connect time
        # Return healthy=True if connection succeeds

class CommandProbe:
    async def run(self, service_name: str, config: ProbeConfig, provider: InfrastructureProvider) -> HealthCheckResult:
        # Call provider.exec_command(service_name, config.command)
        # Return healthy=(exit_code==0)

async def run_probe(service_name: str, config: ProbeConfig, provider: InfrastructureProvider) -> HealthCheckResult:
    """Dispatch to the correct probe based on config.probe_type."""
    if config.probe_type == "http":
        return await HttpProbe().run(service_name, config)
    elif config.probe_type == "tcp":
        return await TcpProbe().run(service_name, config)
    elif config.probe_type == "command":
        return await CommandProbe().run(service_name, config, provider)
    else:
        return HealthCheckResult(service_name=service_name, healthy=False, message=f"Unknown probe type: {config.probe_type}")
```

All probe failures (connection refused, timeout) must be caught and returned as `healthy=False` with the error message — they must not raise exceptions.

**tests/test_collector.py:**

Use `unittest.mock.AsyncMock` to mock the provider. Tests must be `async` and use `pytest.mark.asyncio`.

Required test cases:
1. `test_collect_once_calls_on_snapshot` — mock provider returns 2 services, verify `on_snapshot` is called once with 2 snapshots.
2. `test_collect_once_handles_metrics_failure` — mock `get_metrics()` raises an exception for one service, verify `on_snapshot` is still called (with the successful service only) and no exception propagates.
3. `test_start_stop` — start collector, wait 0.1s, stop — verify `_task` is cancelled cleanly.
4. `test_http_probe_success` — mock `httpx.AsyncClient.get()` to return status 200, assert `healthy=True`.
5. `test_http_probe_failure` — mock raises `httpx.ConnectError`, assert `healthy=False`.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_collector.py -v
# Expected: all 5 tests pass

# Smoke test: verify imports
python -c "
from agent.collector.collector import MetricsCollector
from agent.collector.health_probes import HttpProbe, TcpProbe, CommandProbe, run_probe, ProbeConfig
print('collector imports OK')
"
```

## Dependencies

- Step 01 (project setup)
- Step 02 (core models — `MetricSnapshot`, `HealthCheckResult`, `ServiceInfo`)
- Step 03 (provider interface — `InfrastructureProvider` ABC)
