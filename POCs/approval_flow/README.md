# POC 7: Interactive Approval Flow

## What this proves

1. **Adaptive Card construction** — Rich cards with severity badges, diagnosis, remediation steps, rollback plans, and interactive buttons
2. **Approve/Deny/Investigate callbacks** — Button actions route back to the approval router
3. **Timeout auto-deny** — Unanswered approvals auto-deny after configurable timeout (severity-dependent)
4. **LOW risk auto-approval** — LOW severity actions skip the approval flow entirely
5. **Outcome cards** — Post-resolution cards show success/failure with timing
6. **Async lifecycle** — Full async flow with concurrent timeout tracking

## Architecture

```
Incident detected
      ↓
ApprovalRouter.submit(request)
  ├── LOW → auto-approve → callback → execute immediately
  ├── MEDIUM → build card → send to Teams → start timeout (5 min)
  └── HIGH → build card → send to Teams → start timeout (10 min)
      ↓
User clicks button → ApprovalRouter.resolve()
  ├── APPROVE → execute remediation → outcome card
  ├── DENY → log for review → outcome card
  └── INVESTIGATE → gather more data → re-present
      ↓
Timeout expires → auto-deny → timeout card
```

## Card types

| Card | When |
|------|------|
| `build_approval_card` | Sent to Teams when approval needed |
| `build_outcome_card` | Sent after remediation completes |
| `build_timeout_card` | Sent when approval times out |

## Prerequisites

- None (local simulation, no Teams/Slack required)
- For real Teams deployment, use with POC 4's `teams_app.py`

## Run

```bash
uv run python -m POCs.approval_flow.demo
```

## Test scenarios

| # | Scenario | Expected |
|---|----------|----------|
| 1 | Redis cache full (LOW) | Auto-approved, no card sent |
| 2 | MongoDB down (MEDIUM) | Card sent, user approves after 2s |
| 3 | Nginx 502 (HIGH) | Card sent, user denies after 3s |
| 4 | CPU spike (MEDIUM) | Card sent, no response, timeout after 3s |
