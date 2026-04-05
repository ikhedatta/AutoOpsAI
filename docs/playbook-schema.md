# AutoOps AI - Playbook Schema

## Overview

Playbooks are the knowledge base of AutoOps AI. Each playbook entry describes a **known issue**: how to detect it, what it means, how to fix it, and how to verify the fix. Playbooks are YAML files stored in `playbooks/` and version-controlled alongside the code.

The agent uses playbooks in two ways:
1. **Pattern matching** — When an anomaly is detected, the agent checks if it matches a known playbook entry
2. **LLM context** — Matched playbook entries are fed to the LLM to generate a natural-language diagnosis and action plan

---

## Schema

```yaml
# Required fields
id: string                    # Unique identifier (snake_case)
name: string                  # Human-readable name
severity: LOW | MEDIUM | HIGH # Risk classification
detection: Detection          # How to detect this issue
diagnosis: string             # Plain-language explanation of the problem
remediation: Remediation      # Steps to fix

# Optional fields
provider: string | null       # Provider scope (null = universal)
tags: list[string]            # Searchable tags
cooldown_seconds: int         # Min seconds between re-triggering (default: 300)
rollback: Rollback            # What to do if the fix fails
metadata: dict                # Arbitrary extra info
```

### Detection

```yaml
detection:
  type: string                # Detection strategy (see types below)
  conditions: list            # All conditions must be true (AND logic)
```

**Detection types:**

| Type | Description | Condition fields |
|---|---|---|
| `container_health` | Service state check | `service_name`, `state` (running/stopped/error) |
| `metric_threshold` | Metric exceeds threshold | `metric`, `threshold`, `duration` (optional) |
| `log_pattern` | Log line pattern match | `service_name`, `pattern` (regex), `rate` (optional) |
| `health_endpoint` | HTTP health check failure | `service_name`, `expected_status`, `timeout` |
| `compound` | Multiple detection types | `detectors` (list of Detection objects, all must match) |

**Condition operators for thresholds:**
- `"> 90"` — greater than
- `"< 10"` — less than
- `">= 50"` — greater than or equal
- `"== 0"` — equals

### Remediation

```yaml
remediation:
  steps: list[RemediationStep]
```

**Remediation step types:**

| Action | Description | Parameters |
|---|---|---|
| `restart_service` | Restart a service | `target`, `timeout` |
| `exec_command` | Run a command inside a service | `target`, `command`, `timeout` |
| `scale_service` | Scale replicas up or down | `target`, `replicas` |
| `provider_command` | Raw command via provider | `command`, `args` |
| `health_check` | Verify a service is healthy | `target`, `check` (command or URL), `timeout` |
| `metric_check` | Verify a metric is in range | `metric`, `expected`, `timeout` |
| `collect_logs` | Gather logs for diagnosis | `target`, `lines` |
| `collect_diagnostics` | Run diagnostic command | `target`, `command` |
| `wait` | Pause between steps | `seconds` |
| `escalate` | Escalate to human | `message` |

### Rollback

```yaml
rollback:
  description: string         # When/why to use this rollback
  steps: list[RemediationStep]  # Same step types as remediation
```

---

## Full Example: MongoDB Container Crash

```yaml
id: mongodb_container_down
name: "MongoDB container crash"
severity: MEDIUM
tags: ["database", "mongodb", "container-health"]
cooldown_seconds: 120

detection:
  type: compound
  conditions:
    - type: container_health
      service_name: mongodb
      state: stopped
    - type: health_endpoint
      service_name: demo-app
      expected_status: 200
      actual: 500

diagnosis: >
  MongoDB container has stopped running. This is causing the FastAPI demo
  application to return 500 errors on all database-dependent endpoints.
  Common causes: OOM kill, disk full, or unclean shutdown.

remediation:
  steps:
    - action: collect_logs
      target: mongodb
      lines: 50

    - action: restart_service
      target: mongodb
      timeout: 30

    - action: wait
      seconds: 5

    - action: health_check
      target: mongodb
      check: "mongosh --eval 'rs.status()'"
      timeout: 15

    - action: health_check
      target: demo-app
      check: "curl -sf http://localhost:5000/health"
      timeout: 10

rollback:
  description: "If MongoDB fails to restart after 2 attempts"
  steps:
    - action: collect_logs
      target: mongodb
      lines: 200
    - action: collect_diagnostics
      target: mongodb
      command: "df -h"
    - action: escalate
      message: "MongoDB failed to restart. Logs and disk usage attached. Manual investigation required."
```

---

## Full Example: Kubernetes Pod CrashLoopBackOff

```yaml
id: pod_crash_loop_backoff
name: "Pod CrashLoopBackOff"
provider: kubernetes
severity: MEDIUM
tags: ["kubernetes", "pod", "crash-loop"]
cooldown_seconds: 300

detection:
  type: container_health
  conditions:
    - service_name: "{any}"
      state: error
      extra:
        restart_count: "> 5"
        reason: "CrashLoopBackOff"

diagnosis: >
  A pod is in CrashLoopBackOff state with {restart_count} restarts.
  The container is repeatedly crashing shortly after startup. Common causes:
  application bug, missing config/secrets, resource limits too low, or
  dependency service unavailable.

remediation:
  steps:
    - action: collect_logs
      target: "{service_name}"
      lines: 100

    - action: collect_diagnostics
      target: "{service_name}"
      command: "printenv"

    - action: exec_command
      target: "{service_name}"
      command: "cat /proc/1/status | grep -i mem"
      timeout: 5

    # If previous pod version was stable, rollback
    - action: provider_command
      command: "rollback_service"
      args:
        service_name: "{service_name}"

    - action: wait
      seconds: 30

    - action: health_check
      target: "{service_name}"
      check: "curl -sf http://localhost:{port}/health"
      timeout: 15

rollback:
  description: "If rollback also crashes, escalate with full diagnostics"
  steps:
    - action: collect_logs
      target: "{service_name}"
      lines: 500
    - action: escalate
      message: "Pod {service_name} is in CrashLoopBackOff. Rollback also failed. Logs attached."
```

---

## Full Example: Redis Memory Full (LOW risk, auto-execute)

```yaml
id: redis_memory_full
name: "Redis memory at capacity"
severity: LOW
tags: ["cache", "redis", "memory"]
cooldown_seconds: 600

detection:
  type: metric_threshold
  conditions:
    - metric: memory_percent
      service_name: redis
      threshold: "> 90"

diagnosis: >
  Redis memory usage has exceeded 90%. This may cause eviction of cached
  data and increased latency on cache-dependent endpoints.

remediation:
  steps:
    - action: exec_command
      target: redis
      command: "redis-cli MEMORY PURGE"
      timeout: 10

    - action: wait
      seconds: 5

    - action: metric_check
      metric: memory_percent
      service_name: redis
      expected: "< 60"
      timeout: 10
```

---

## Full Example: High CPU (Generic, Any Provider)

```yaml
id: high_cpu_sustained
name: "Sustained high CPU on service"
severity: MEDIUM
tags: ["performance", "cpu"]
cooldown_seconds: 300

detection:
  type: metric_threshold
  conditions:
    - metric: cpu_percent
      service_name: "{any}"
      threshold: "> 90"
      duration: "2m"

diagnosis: >
  Service {service_name} has had CPU usage above 90% for over 2 minutes.
  This may indicate a resource leak, runaway process, infinite loop,
  or insufficient resource allocation.

remediation:
  steps:
    - action: collect_diagnostics
      target: "{service_name}"
      command: "top -bn1 | head -20"

    - action: collect_logs
      target: "{service_name}"
      lines: 50

    - action: restart_service
      target: "{service_name}"
      timeout: 30

    - action: wait
      seconds: 10

    - action: metric_check
      metric: cpu_percent
      service_name: "{service_name}"
      expected: "< 50"
      timeout: 30

rollback:
  description: "If CPU stays high after restart, scale horizontally if supported"
  steps:
    - action: scale_service
      target: "{service_name}"
      replicas: 2
    - action: escalate
      message: "Service {service_name} has sustained high CPU even after restart. Scaled to 2 replicas. Manual investigation recommended."
```

---

## Template Variables

Playbooks support template variables using `{variable}` syntax:

| Variable | Description | Source |
|---|---|---|
| `{service_name}` | Name of the affected service | Detected from anomaly |
| `{any}` | Wildcard — matches any service | Used in detection conditions |
| `{port}` | Service port | From service info / config |
| `{restart_count}` | Number of restarts | From metrics/status |
| `{threshold}` | The threshold that was breached | From detection config |
| `{metric_value}` | Current value of the breached metric | From metric snapshot |

---

## Playbook Directory Structure

```
playbooks/
├── general/                  # Universal playbooks (any provider)
│   ├── high_cpu.yaml
│   ├── high_memory.yaml
│   ├── disk_full.yaml
│   └── health_check_failed.yaml
│
├── docker_compose/           # Docker Compose specific
│   ├── mongodb.yaml
│   ├── redis.yaml
│   ├── nginx.yaml
│   └── container_oom.yaml
│
└── kubernetes/               # Kubernetes specific
    ├── pod_crash_loop.yaml
    ├── node_pressure.yaml
    ├── service_unreachable.yaml
    ├── pvc_pending.yaml
    └── image_pull_backoff.yaml
```

The knowledge base loader reads all YAML files from:
1. `playbooks/general/` — always loaded
2. `playbooks/{active_provider}/` — loaded based on configured provider
