# POC 8: Continuous Anomaly Detection Loop

## What this proves

1. **Docker stats polling** — Collects CPU, memory, health, restart count, and status for all containers every N seconds
2. **Threshold-based detection** — Configurable thresholds for CPU%, memory%, restart count
3. **Duration-aware alerts** — CPU/memory anomalies only fire after the condition persists across multiple cycles (not single spikes)
4. **Structured event emission** — Produces `AnomalyEvent` objects compatible with POC 5's playbook matching
5. **Callback system** — Downstream consumers register callbacks that fire on anomaly detection

## Architecture

```
Docker Daemon
      ↓
MetricsCollector.collect()  [every 10-15s]
      ↓
SystemSnapshot (list of ContainerSnapshots)
      ↓
AnomalyDetector.analyze()
  ├── container down/dead/restarting → immediate event
  ├── restart loop (count > threshold) → immediate event
  ├── unhealthy health check → immediate event
  ├── high CPU (duration-aware) → event after N seconds persisting
  └── high memory (duration-aware) → event after N seconds persisting
      ↓
list[AnomalyEvent] → callbacks → (playbook matching / approval / etc.)
```

## Prerequisites

- Docker daemon running with at least 1 container

## Run

```bash
uv run python -m POCs.anomaly_detection.demo
```

## Testing tips

- Stop a container during the poll: `docker stop <name>` → triggers container_health event
- Stress a container's CPU: `docker exec <name> stress --cpu 2 --timeout 60s`
- The demo uses lower thresholds (CPU>80%, Mem>70%) so anomalies are easier to trigger
