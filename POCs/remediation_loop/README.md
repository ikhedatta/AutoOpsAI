# POC 9: Remediation + Verification Loop

## What this proves

1. **Execute remediation actions** — docker_restart, docker_exec, redis_command, collect_logs
2. **Verification after fix** — health checks confirm the fix actually worked
3. **Retry on failure** — if a step fails, retry once before escalating
4. **Escalation path** — when retries fail, mark as escalated with a message
5. **MTTR tracking** — timing metrics for each step and overall remediation
6. **Playbook integration** — steps come from the same YAML schema as POC 5

## Architecture

```
PlaybookEntry.remediation.steps
        ↓
RemediationExecutor.execute_playbook()
  ├── Step 1: docker_restart → wait → check status
  ├── Step 2: health_check → verify running + exec check command
  ├── Step 3: health_check → verify dependent service
  │     ↓ (any step fails)
  │   Retry once → still fails → ESCALATE
  └── All passed → VERIFIED ✓
        ↓
RemediationResult (steps, verified, escalated, MTTR)
```

## Supported actions

| Action | What it does |
|--------|-------------|
| `docker_restart` | Restart container, wait, verify status=running |
| `health_check` | Check container running + optional exec command |
| `docker_exec` | Run arbitrary command in container |
| `redis_command` | Execute redis-cli command in redis container |
| `collect_logs` | Gather container logs (tail N lines) |
| `collect_diagnostics` | Run diagnostic commands (top, stats) |
| `metric_check` | Verify a metric value (placeholder for Prometheus) |
| `escalate` | Stop remediation and flag for human investigation |

## Prerequisites

- Docker daemon running with at least one container

## Run

```bash
uv run python -m POCs.remediation_loop.demo
```
