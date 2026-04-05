# [Step 04] — Docker Compose Provider

## Context

Steps 01-03 are complete. The following exist:
- `agent/providers/base.py` — `InfrastructureProvider` ABC
- `agent/providers/registry.py` — `register_provider`, `create_provider`
- `agent/models.py` — all shared models
- `agent/config.py` — `AgentSettings`

## Objective

Produce a complete, working `DockerComposeProvider` that implements every method of the `InfrastructureProvider` ABC using the Docker SDK for Python, plus integration tests that run against real Docker.

## Files to Create

- `agent/providers/docker_compose.py` — Full `DockerComposeProvider` implementation.
- `tests/test_providers/test_docker_compose.py` — Integration tests against real Docker daemon.

## Files to Modify

- `agent/providers/registry.py` — Add import and registration of `DockerComposeProvider` at the bottom of the file (after the registry functions, inside a `try/except ImportError` guard so the registry still loads even if docker is not installed).

## Key Requirements

**agent/providers/docker_compose.py:**

Constructor signature:
```python
def __init__(self, project_name: str = "autoops-demo", compose_file: str = "./infra/docker-compose/docker-compose.target.yml"):
    self.client = docker.from_env()
    self.project_name = project_name
    self.compose_file = compose_file
```

Register at the bottom of the module (not in `__init__`):
```python
from agent.providers.registry import register_provider
register_provider("docker_compose", DockerComposeProvider)
```

**Blocking call wrapper:** The Docker SDK is synchronous. All methods that call the Docker SDK must wrap blocking calls using:
```python
import asyncio
loop = asyncio.get_event_loop()
result = await loop.run_in_executor(None, blocking_call)
```

Use `functools.partial` for calls with arguments. Do not use `asyncio.run()`.

**`list_services()`:**
- Filter containers with `self.client.containers.list(all=True, filters={"label": f"com.docker.compose.project={self.project_name}"})`
- Map each container to `ServiceInfo` via `_container_to_service_info(container)`

**`get_service_status(service_name)`:**
- Call `_find_container(service_name)` which raises `ValueError` if not found
- Map container state to `ServiceState`: `"running"` → `RUNNING`, `"exited"` or `"dead"` → `STOPPED`, `"restarting"` → `RESTARTING`, anything else → `UNKNOWN`
- `uptime_seconds`: parse `container.attrs["State"]["StartedAt"]` ISO timestamp and compute delta from now
- `restart_count`: `container.attrs["RestartCount"]`
- `last_error`: `container.attrs["State"]["Error"]` if non-empty

**`get_metrics(service_name)`:**
- Call `container.stats(stream=False)` and parse via `_parse_docker_stats(service_name, stats_dict)`
- CPU percent formula: `((cpu_delta / system_delta) * num_cpus) * 100.0` where:
  - `cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]`
  - `system_delta = stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]`
  - `num_cpus = len(stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [])) or stats["cpu_stats"]["online_cpus"]`
- Memory: `stats["memory_stats"]["usage"]` and `stats["memory_stats"]["limit"]`
- Network: sum all interfaces in `stats["networks"]` for `rx_bytes` and `tx_bytes`
- Disk I/O: sum `blkio_stats["io_service_bytes_recursive"]` for `"read"` and `"write"` ops

**`health_check(service_name)`:**
- Inspect container labels for `autoops.health.type` (values: `http`, `tcp`, `command`)
- If `autoops.health.type=http`: GET the URL in label `autoops.health.url`, return `healthy=(status==200)`
- If `autoops.health.type=command`: exec the command in label `autoops.health.command` inside the container, `healthy=(exit_code==0)`
- If `autoops.health.type=tcp`: attempt socket connect to `autoops.health.host:autoops.health.port`
- If no labels: check if container state is `running`, return `healthy=True` if so

**`restart_service(service_name, timeout_seconds=30)`:**
- `container.restart(timeout=timeout_seconds)`
- Return `CommandResult(success=True, output=f"Restarted {service_name}")`
- Catch `docker.errors.APIError` and return `CommandResult(success=False, error=str(e))`

**`exec_command(service_name, command, timeout_seconds=30)`:**
- `exit_code, output = container.exec_run(command, demux=True, stream=False)`
- `stdout = output[0].decode("utf-8", errors="replace") if output[0] else ""`
- `stderr = output[1].decode("utf-8", errors="replace") if output[1] else ""`

**`get_logs(service_name, lines=100, since=None)`:**
- `raw = container.logs(tail=lines, since=since, timestamps=True).decode("utf-8", errors="replace")`
- Split on `\n`, filter empty, return `list[LogEntry]`
- Attempt to parse timestamp prefix from Docker log format (`2006-01-02T15:04:05.999999999Z`)

**`scale_service(service_name, replicas)`:**
- Use `subprocess.run(["docker", "compose", "-f", self.compose_file, "up", "-d", "--scale", f"{service_name}={replicas}", service_name], capture_output=True, text=True)`

**`stop_service(service_name)`:** `container.stop()`

**`start_service(service_name)`:** `container.start()`

**`_container_to_service_info(container)`:** Helper that maps a `docker.models.containers.Container` to `ServiceInfo`. Use `container.labels.get("com.docker.compose.service", container.name)` for `name`.

**`_find_container(service_name)`:** Filter `self.client.containers.list(all=True)` for containers where label `com.docker.compose.service == service_name` AND label `com.docker.compose.project == self.project_name`. Raise `ValueError(f"Container '{service_name}' not found in project '{self.project_name}'")` if not found.

**tests/test_providers/test_docker_compose.py:**
- Mark all tests with `@pytest.mark.integration` and `@pytest.mark.asyncio`
- Skip if Docker daemon not reachable (use `pytest.importorskip("docker")` and a session fixture that checks `docker.from_env().ping()`)
- Tests do NOT depend on the demo stack being up — they should work against any running container
- Test `list_services()` returns a list (even if empty)
- Test `get_metrics()` on a real running container returns positive CPU/memory values
- Test `restart_service()` returns `CommandResult(success=True)`
- Test `exec_command()` with `echo hello` returns `output` containing `hello`
- Use `conftest.py` with a session-scoped Docker client fixture

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI

# Verify module imports cleanly and registers the provider
python -c "
import agent.providers.docker_compose
from agent.providers.registry import list_providers
assert 'docker_compose' in list_providers(), 'docker_compose not registered'
print('docker_compose provider registered OK')
"

# Run integration tests (requires Docker daemon running)
pytest tests/test_providers/test_docker_compose.py -v -m integration
# Expected: tests pass or skip gracefully if no containers match the project name

# Verify provider can be created via factory
python -c "
from agent.providers.registry import create_provider
p = create_provider('docker_compose', project_name='test', compose_file='docker-compose.yml')
print('provider created:', p.provider_name())
"
```

## Dependencies

- Step 01 (project setup, docker package installed)
- Step 02 (core models)
- Step 03 (provider interface and registry)
