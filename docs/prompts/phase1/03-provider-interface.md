# [Step 03] — Provider Interface (ABC) & Registry

## Context

Steps 01 and 02 are complete. The following exist:
- `agent/config.py` with `AgentSettings`
- `agent/models.py` with all shared models including `ServiceInfo`, `ServiceStatus`, `MetricSnapshot`, `HealthCheckResult`, `CommandResult`, `LogEntry`
- All `__init__.py` package files

## Objective

Produce the `InfrastructureProvider` abstract base class and the provider registry/factory — no concrete implementations yet, just the interface and the registration mechanism.

## Files to Create

- `agent/providers/base.py` — `InfrastructureProvider` ABC with all abstract and optional methods.
- `agent/providers/registry.py` — `_PROVIDERS` dict, `register_provider()`, `create_provider()`, and `get_provider_class()` functions.

## Files to Modify

None.

## Key Requirements

**agent/providers/base.py:**

The class must be named exactly `InfrastructureProvider` and import models from `agent.models`. All abstract methods must match these exact signatures:

```python
@abstractmethod
async def list_services(self) -> list[ServiceInfo]: ...

@abstractmethod
async def get_service_status(self, service_name: str) -> ServiceStatus: ...

@abstractmethod
async def get_metrics(self, service_name: str) -> MetricSnapshot: ...

@abstractmethod
async def health_check(self, service_name: str) -> HealthCheckResult: ...

@abstractmethod
async def restart_service(self, service_name: str, timeout_seconds: int = 30) -> CommandResult: ...

@abstractmethod
async def exec_command(self, service_name: str, command: str, timeout_seconds: int = 30) -> CommandResult: ...

@abstractmethod
async def get_logs(self, service_name: str, lines: int = 100, since: Optional[str] = None) -> list[LogEntry]: ...

@abstractmethod
async def scale_service(self, service_name: str, replicas: int) -> CommandResult: ...

@abstractmethod
async def stop_service(self, service_name: str) -> CommandResult: ...

@abstractmethod
async def start_service(self, service_name: str) -> CommandResult: ...
```

**Optional methods with default implementations (not abstract, concrete defaults):**

```python
async def get_events(self, service_name: str, limit: int = 50) -> list[dict]:
    return []

async def get_resource_quotas(self) -> dict:
    return {}

async def rollback_service(self, service_name: str, to_version: Optional[str] = None) -> CommandResult:
    return CommandResult(success=False, output="Rollback not supported by this provider")

def provider_name(self) -> str:
    return self.__class__.__name__
```

**agent/providers/registry.py:**

```python
_PROVIDERS: dict[str, type[InfrastructureProvider]] = {}

def register_provider(name: str, provider_class: type[InfrastructureProvider]) -> None:
    """Register a provider class by name. Call this at module import time."""
    _PROVIDERS[name] = provider_class

def get_provider_class(name: str) -> type[InfrastructureProvider]:
    """Return the provider class without instantiating it."""
    if name not in _PROVIDERS:
        available = ", ".join(_PROVIDERS.keys())
        raise ValueError(f"Unknown provider '{name}'. Available: {available}")
    return _PROVIDERS[name]

def create_provider(name: str, **kwargs) -> InfrastructureProvider:
    """Instantiate and return a provider by name."""
    return get_provider_class(name)(**kwargs)

def list_providers() -> list[str]:
    return list(_PROVIDERS.keys())
```

The registry starts empty — concrete providers register themselves when their modules are imported (see step 04). Do not import concrete provider modules from `registry.py` — that would create a circular dependency.

**Note on async methods:** All provider methods that interact with the infrastructure are `async`. The Docker SDK is synchronous — wrap blocking Docker SDK calls with `asyncio.get_event_loop().run_in_executor(None, ...)` in the concrete implementation (step 04). Do not use `asyncio.run()` inside async methods.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
python -c "
from agent.providers.base import InfrastructureProvider
from agent.providers.registry import register_provider, create_provider, list_providers
from agent.models import ServiceInfo, ServiceState, ServiceStatus, MetricSnapshot, HealthCheckResult, CommandResult, LogEntry
from datetime import datetime, timezone
import inspect

# Verify ABC cannot be instantiated
try:
    InfrastructureProvider()
    assert False, 'Should have raised TypeError'
except TypeError:
    pass

# Verify all abstract methods are present
abstract_methods = {m for m in dir(InfrastructureProvider) if getattr(getattr(InfrastructureProvider, m, None), '__isabstractmethod__', False)}
required = {'list_services', 'get_service_status', 'get_metrics', 'health_check', 'restart_service', 'exec_command', 'get_logs', 'scale_service', 'stop_service', 'start_service'}
assert required.issubset(abstract_methods), f'Missing abstract methods: {required - abstract_methods}'

# Verify optional methods have defaults
class MinimalProvider(InfrastructureProvider):
    async def list_services(self): return []
    async def get_service_status(self, s): return ServiceStatus(name=s, state=ServiceState.UNKNOWN)
    async def get_metrics(self, s): return MetricSnapshot(service_name=s, timestamp=datetime.now(timezone.utc), cpu_percent=0, memory_used_bytes=0)
    async def health_check(self, s): return HealthCheckResult(service_name=s, healthy=True)
    async def restart_service(self, s, timeout_seconds=30): return CommandResult(success=True)
    async def exec_command(self, s, command, timeout_seconds=30): return CommandResult(success=True)
    async def get_logs(self, s, lines=100, since=None): return []
    async def scale_service(self, s, r): return CommandResult(success=True)
    async def stop_service(self, s): return CommandResult(success=True)
    async def start_service(self, s): return CommandResult(success=True)

p = MinimalProvider()
assert p.provider_name() == 'MinimalProvider'

# Verify registry
register_provider('minimal', MinimalProvider)
assert 'minimal' in list_providers()
p2 = create_provider('minimal')
assert isinstance(p2, MinimalProvider)

# Verify unknown provider raises ValueError
try:
    create_provider('nonexistent')
    assert False
except ValueError:
    pass

print('all provider interface tests passed')
"
```

## Dependencies

- Step 01 (project setup)
- Step 02 (core models — `ServiceInfo`, `ServiceStatus`, `MetricSnapshot`, `HealthCheckResult`, `CommandResult`, `LogEntry` must exist in `agent.models`)
