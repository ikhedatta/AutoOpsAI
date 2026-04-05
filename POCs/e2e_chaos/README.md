# POC 10: Chaos Injection & End-to-End Recovery

## What this proves

This is the **integration test** that wires all previous POCs into a single pipeline:

1. **Chaos injection** (this POC) — Stop a container to simulate a crash
2. **Anomaly detection** (POC 8) — Detect the failure via Docker stats polling
3. **Playbook matching** (POC 5) — Match the anomaly to a known playbook entry
4. **Risk classification** (POC 6) — Classify risk and determine routing
5. **Approval routing** (POC 7) — Auto-approve for demo (simulates user clicking Approve)
6. **Remediation + verification** (POC 9) — Restart container and verify health

## Pipeline flow

```
Chaos Injector → kill container
        ↓
MetricsCollector → SystemSnapshot
        ↓
AnomalyDetector → AnomalyEvent (container_health, status=exited)
        ↓
KnowledgeBase.match() → PlaybookEntry
        ↓
route_incident() → RoutingDecision (risk level + action path)
        ↓
[auto-approve for demo]
        ↓
RemediationExecutor → docker_restart → health_check → verified
        ↓
IncidentRecord (outcome=resolved, MTTR=Xms)
```

## Demo scenarios

| # | Scenario | What happens |
|---|----------|-------------|
| 1 | Kill a container, full pipeline | Stop → detect → match → route → fix → verify |
| 2 | Scan all current anomalies | Detect existing issues and process through pipeline |

## Prerequisites

- Docker daemon running with at least 1 running container

## Run

```bash
uv run python -m POCs.e2e_chaos.demo
```

## Notes

- The demo picks a non-critical container to avoid disrupting databases
- Approval is auto-granted (simulating user interaction from POC 7)
- If no playbook matches the container, the incident is logged as `no_playbook`
- MTTR is tracked from detection to verified recovery
