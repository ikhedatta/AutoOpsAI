# POC 6: Tiered Autonomy & Risk-Based Routing

## What this proves

1. **Risk classification** — Combines playbook severity, action type, container criticality, and confidence to determine risk level
2. **Tiered routing** — LOW→auto-execute, MEDIUM→request approval, HIGH→require explicit approval
3. **Escalation rules** — Destructive actions on critical containers bump risk; low confidence bumps risk
4. **Max-risk aggregation** — Full playbook risk = highest risk across all remediation steps
5. **Playbook integration** — Classifies all POC 5 playbook entries correctly

## Routing rules

| Rule | Effect |
|------|--------|
| `escalate` action | Always HIGH, always escalate |
| `docker_restart` on critical container (mongodb, postgres, nginx...) | At least MEDIUM |
| `docker_restart` on any container | At least MEDIUM (bumps LOW→MEDIUM) |
| Confidence < 50% | Bumps risk one level |
| Safe actions (collect_logs, metric_check, redis_command) | Stays at playbook severity |
| Multi-step playbook | Takes the max risk across all steps |

## Action paths

| Path | Behavior |
|------|----------|
| `auto_execute` | Execute immediately, notify after (LOW only) |
| `request_approval` | Send to Teams, 5-min timeout, auto-deny (MEDIUM) |
| `require_approval` | Send to Teams, 10-min timeout, no auto-execute (HIGH) |
| `escalate` | Cannot auto-fix, needs human investigation |

## Prerequisites

- None (pure logic)

## Run

```bash
uv run python -m POCs.tiered_autonomy.demo
```
