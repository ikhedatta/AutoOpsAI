# AutoOps AI - Infrastructure Provider Interface

## Why a Provider Abstraction?

AutoOps AI aims to be a **virtual DevOps engineer** that works with whatever infrastructure you run — Docker Compose on a laptop, Kubernetes in the cloud, ECS on AWS, Nomad, or bare-metal servers. The provider interface is the boundary between "what the agent wants to do" and "how it's done on this specific platform."

The agent engine never calls `docker restart` or `kubectl delete pod` directly. It calls `provider.restart_service("mongodb")` and the provider translates that into the right platform-specific command.

---

## Provider Interface (Abstract Base Class)

```python
from abc import ABC, abstractmethod
from typing import Optional
from agent.models import (
    ServiceInfo,
    ServiceStatus,
    MetricSnapshot,
    HealthCheckResult,
    CommandResult,
    LogEntry,
)


class InfrastructureProvider(ABC):
    """
    Abstract interface for infrastructure platforms.
    Implement this to add support for a new deployment environment.
    """

    @abstractmethod
    async def list_services(self) -> list[ServiceInfo]:
        """Discover all running services/containers/pods."""
        ...

    @abstractmethod
    async def get_service_status(self, service_name: str) -> ServiceStatus:
        """Get current status of a specific service (running, stopped, error, etc.)."""
        ...

    @abstractmethod
    async def get_metrics(self, service_name: str) -> MetricSnapshot:
        """
        Get resource metrics for a service.
        Returns: CPU %, memory usage/limit, network I/O, disk I/O.
        """
        ...

    @abstractmethod
    async def health_check(self, service_name: str) -> HealthCheckResult:
        """
        Run an application-level health check.
        Uses the health check config defined per service (HTTP endpoint, TCP, command).
        """
        ...

    @abstractmethod
    async def restart_service(self, service_name: str, timeout_seconds: int = 30) -> CommandResult:
        """Restart a service. Returns success/failure + output."""
        ...

    @abstractmethod
    async def exec_command(self, service_name: str, command: str, timeout_seconds: int = 30) -> CommandResult:
        """Execute a command inside a running service/container/pod."""
        ...

    @abstractmethod
    async def get_logs(self, service_name: str, lines: int = 100, since: Optional[str] = None) -> list[LogEntry]:
        """Retrieve recent logs from a service."""
        ...

    @abstractmethod
    async def scale_service(self, service_name: str, replicas: int) -> CommandResult:
        """Scale a service to the specified number of replicas."""
        ...

    @abstractmethod
    async def stop_service(self, service_name: str) -> CommandResult:
        """Stop a service."""
        ...

    @abstractmethod
    async def start_service(self, service_name: str) -> CommandResult:
        """Start a previously stopped service."""
        ...

    # -- Optional / advanced methods with default no-op implementations --

    async def get_events(self, service_name: str, limit: int = 50) -> list[dict]:
        """Get platform events for a service (K8s events, Docker events, etc.)."""
        return []

    async def get_resource_quotas(self) -> dict:
        """Get resource quotas/limits for the environment."""
        return {}

    async def rollback_service(self, service_name: str, to_version: Optional[str] = None) -> CommandResult:
        """Roll back a service to a previous version/image. Not all providers support this."""
        return CommandResult(success=False, output="Rollback not supported by this provider")

    def provider_name(self) -> str:
        """Human-readable name of this provider."""
        return self.__class__.__name__
```

---

## Data Models

```python
from pydantic import BaseModel
from enum import Enum
from datetime import datetime
from typing import Optional


class ServiceState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    RESTARTING = "restarting"
    ERROR = "error"
    UNKNOWN = "unknown"


class ServiceInfo(BaseModel):
    """A discovered service in the infrastructure."""
    name: str                          # Logical name (e.g., "mongodb", "demo-app")
    platform_id: str                   # Platform-specific ID (container ID, pod name, etc.)
    image: Optional[str] = None        # Container image or binary info
    state: ServiceState
    labels: dict[str, str] = {}        # Platform labels/annotations
    created_at: Optional[datetime] = None


class ServiceStatus(BaseModel):
    """Current status of a service."""
    name: str
    state: ServiceState
    uptime_seconds: Optional[float] = None
    restart_count: int = 0
    last_error: Optional[str] = None


class MetricSnapshot(BaseModel):
    """Resource metrics for a service at a point in time."""
    service_name: str
    timestamp: datetime
    cpu_percent: float                 # 0.0 - 100.0+
    memory_used_bytes: int
    memory_limit_bytes: Optional[int] = None
    memory_percent: Optional[float] = None
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    disk_read_bytes: int = 0
    disk_write_bytes: int = 0
    # Provider-specific extras (e.g., K8s pod restarts, Docker OOM kills)
    extra: dict = {}


class HealthCheckResult(BaseModel):
    """Result of an application-level health check."""
    service_name: str
    healthy: bool
    response_time_ms: Optional[float] = None
    status_code: Optional[int] = None
    message: Optional[str] = None


class CommandResult(BaseModel):
    """Result of a command execution."""
    success: bool
    output: str = ""
    error: str = ""
    exit_code: Optional[int] = None
    duration_seconds: Optional[float] = None


class LogEntry(BaseModel):
    """A single log line from a service."""
    timestamp: Optional[datetime] = None
    message: str
    level: Optional[str] = None        # INFO, WARN, ERROR, etc.
    source: Optional[str] = None       # stdout, stderr, file path
```

---

## Provider Implementations

### Docker Compose Provider

The default provider for local development and hackathon demos.

```python
import docker
from agent.providers.base import InfrastructureProvider

class DockerComposeProvider(InfrastructureProvider):
    """
    Provider for Docker Compose environments.
    Uses the Docker SDK for Python to interact with containers.
    """

    def __init__(self, project_name: str = "autoops", compose_file: str = "docker-compose.yml"):
        self.client = docker.from_env()
        self.project_name = project_name
        self.compose_file = compose_file

    async def list_services(self) -> list[ServiceInfo]:
        # Filter containers by com.docker.compose.project label
        containers = self.client.containers.list(
            all=True,
            filters={"label": f"com.docker.compose.project={self.project_name}"}
        )
        return [self._container_to_service_info(c) for c in containers]

    async def get_metrics(self, service_name: str) -> MetricSnapshot:
        container = self._find_container(service_name)
        stats = container.stats(stream=False)
        return self._parse_docker_stats(service_name, stats)

    async def restart_service(self, service_name: str, timeout_seconds: int = 30) -> CommandResult:
        container = self._find_container(service_name)
        container.restart(timeout=timeout_seconds)
        return CommandResult(success=True, output=f"Container {service_name} restarted")

    async def exec_command(self, service_name: str, command: str, timeout_seconds: int = 30) -> CommandResult:
        container = self._find_container(service_name)
        exit_code, output = container.exec_run(command, demux=True)
        stdout = output[0].decode() if output[0] else ""
        stderr = output[1].decode() if output[1] else ""
        return CommandResult(
            success=(exit_code == 0),
            output=stdout,
            error=stderr,
            exit_code=exit_code,
        )

    async def get_logs(self, service_name: str, lines: int = 100, since=None) -> list[LogEntry]:
        container = self._find_container(service_name)
        logs = container.logs(tail=lines, since=since, timestamps=True).decode()
        return [LogEntry(message=line) for line in logs.strip().split("\n") if line]

    async def scale_service(self, service_name: str, replicas: int) -> CommandResult:
        # Docker Compose scale via subprocess (SDK doesn't natively support compose scale)
        import subprocess
        result = subprocess.run(
            ["docker", "compose", "-f", self.compose_file, "up", "-d", "--scale",
             f"{service_name}={replicas}", service_name],
            capture_output=True, text=True,
        )
        return CommandResult(
            success=(result.returncode == 0),
            output=result.stdout,
            error=result.stderr,
            exit_code=result.returncode,
        )

    # ... (helper methods: _find_container, _container_to_service_info, _parse_docker_stats)
```

### Kubernetes Provider

```python
from kubernetes import client, config as k8s_config
from agent.providers.base import InfrastructureProvider

class KubernetesProvider(InfrastructureProvider):
    """
    Provider for Kubernetes environments.
    Uses the official kubernetes Python client.
    """

    def __init__(self, namespace: str = "default", kubeconfig: str | None = None):
        if kubeconfig:
            k8s_config.load_kube_config(config_file=kubeconfig)
        else:
            # In-cluster config when running as a pod, fallback to kubeconfig
            try:
                k8s_config.load_incluster_config()
            except k8s_config.ConfigException:
                k8s_config.load_kube_config()

        self.namespace = namespace
        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

    async def list_services(self) -> list[ServiceInfo]:
        pods = self.core_v1.list_namespaced_pod(self.namespace)
        return [self._pod_to_service_info(pod) for pod in pods.items]

    async def get_metrics(self, service_name: str) -> MetricSnapshot:
        # Use metrics-server API or Prometheus
        # K8s metrics-server: /apis/metrics.k8s.io/v1beta1/namespaces/{ns}/pods/{pod}
        custom_api = client.CustomObjectsApi()
        metrics = custom_api.list_namespaced_custom_object(
            group="metrics.k8s.io", version="v1beta1",
            namespace=self.namespace, plural="pods",
        )
        return self._parse_k8s_metrics(service_name, metrics)

    async def restart_service(self, service_name: str, timeout_seconds: int = 30) -> CommandResult:
        # Restart by doing a rollout restart (patch deployment with annotation)
        deployment = self._find_deployment(service_name)
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "autoops.ai/restartedAt": datetime.utcnow().isoformat()
                        }
                    }
                }
            }
        }
        self.apps_v1.patch_namespaced_deployment(
            name=deployment, namespace=self.namespace, body=patch,
        )
        return CommandResult(success=True, output=f"Deployment {service_name} rollout restart triggered")

    async def exec_command(self, service_name: str, command: str, timeout_seconds: int = 30) -> CommandResult:
        from kubernetes.stream import stream
        pod = self._find_pod(service_name)
        resp = stream(
            self.core_v1.connect_get_namespaced_pod_exec,
            pod, self.namespace,
            command=["/bin/sh", "-c", command],
            stderr=True, stdout=True, stdin=False, tty=False,
        )
        return CommandResult(success=True, output=resp)

    async def scale_service(self, service_name: str, replicas: int) -> CommandResult:
        deployment = self._find_deployment(service_name)
        patch = {"spec": {"replicas": replicas}}
        self.apps_v1.patch_namespaced_deployment_scale(
            name=deployment, namespace=self.namespace, body=patch,
        )
        return CommandResult(success=True, output=f"Scaled {service_name} to {replicas} replicas")

    async def get_events(self, service_name: str, limit: int = 50) -> list[dict]:
        events = self.core_v1.list_namespaced_event(
            self.namespace,
            field_selector=f"involvedObject.name={service_name}",
            limit=limit,
        )
        return [
            {"type": e.type, "reason": e.reason, "message": e.message, "time": str(e.last_timestamp)}
            for e in events.items
        ]

    async def rollback_service(self, service_name: str, to_version=None) -> CommandResult:
        # K8s supports rollback via rollout undo
        import subprocess
        cmd = ["kubectl", "rollout", "undo", f"deployment/{service_name}", "-n", self.namespace]
        if to_version:
            cmd.extend(["--to-revision", str(to_version)])
        result = subprocess.run(cmd, capture_output=True, text=True)
        return CommandResult(
            success=(result.returncode == 0),
            output=result.stdout,
            error=result.stderr,
            exit_code=result.returncode,
        )

    # ... (helper methods: _find_pod, _find_deployment, _pod_to_service_info, _parse_k8s_metrics)
```

---

## Provider Registry

Providers are registered and selected at startup based on configuration.

```python
from agent.providers.base import InfrastructureProvider
from agent.providers.docker_compose import DockerComposeProvider
from agent.providers.kubernetes import KubernetesProvider


_PROVIDERS: dict[str, type[InfrastructureProvider]] = {
    "docker_compose": DockerComposeProvider,
    "kubernetes": KubernetesProvider,
}


def register_provider(name: str, provider_class: type[InfrastructureProvider]):
    """Register a custom provider. Use this to add support for new platforms."""
    _PROVIDERS[name] = provider_class


def create_provider(name: str, **kwargs) -> InfrastructureProvider:
    """Create a provider instance by name."""
    if name not in _PROVIDERS:
        available = ", ".join(_PROVIDERS.keys())
        raise ValueError(f"Unknown provider '{name}'. Available: {available}")
    return _PROVIDERS[name](**kwargs)
```

**Configuration (`config.yaml`):**

```yaml
provider:
  type: docker_compose          # or "kubernetes"
  options:
    # Docker Compose options
    project_name: autoops-demo
    compose_file: ./infra/docker-compose/docker-compose.target.yml

    # Kubernetes options (when type: kubernetes)
    # namespace: autoops
    # kubeconfig: ~/.kube/config
```

---

## Adding a New Provider

To support a new platform (e.g., AWS ECS, HashiCorp Nomad, Podman):

1. **Create a new file** in `agent/providers/` (e.g., `ecs.py`)
2. **Implement `InfrastructureProvider`** — all abstract methods must be implemented
3. **Register it** in `agent/providers/registry.py`
4. **Add playbooks** in `playbooks/<provider_name>/` for platform-specific known issues
5. **Add chaos scripts** in `chaos/<provider_name>/` for testing

The agent engine, approval flow, dashboard, and knowledge base require **zero changes**. This is the power of the abstraction.

### Provider Checklist

| Method | Required | Notes |
|---|---|---|
| `list_services()` | Yes | Discover what's running |
| `get_service_status()` | Yes | Is it up or down? |
| `get_metrics()` | Yes | CPU, memory, etc. |
| `health_check()` | Yes | App-level health |
| `restart_service()` | Yes | Most common remediation |
| `exec_command()` | Yes | Run diagnostics inside a service |
| `get_logs()` | Yes | Needed for log-based detection |
| `scale_service()` | Yes | Horizontal scaling |
| `stop_service()` | Yes | Graceful shutdown |
| `start_service()` | Yes | Start stopped services |
| `get_events()` | Optional | Platform events (very useful for K8s) |
| `get_resource_quotas()` | Optional | Capacity info |
| `rollback_service()` | Optional | Version rollback |

---

## Provider-Aware Playbooks

Playbooks can be scoped to specific providers:

```yaml
# playbooks/kubernetes/pod_crash_loop.yaml
provider: kubernetes          # Only matched when running with K8s provider
id: pod_crash_loop_backoff
name: "Pod CrashLoopBackOff"
severity: MEDIUM
detection:
  type: service_status
  conditions:
    - state: "error"
      extra.restart_count: "> 5"
      extra.reason: "CrashLoopBackOff"
```

Playbooks without a `provider` field are **universal** and matched regardless of platform.

```yaml
# playbooks/general/high_memory.yaml
# No provider field = works with any provider
id: high_memory_usage
name: "Service memory usage critical"
severity: MEDIUM
detection:
  type: metric_threshold
  conditions:
    - metric: memory_percent
      threshold: "> 90%"
      duration: "2m"
```
