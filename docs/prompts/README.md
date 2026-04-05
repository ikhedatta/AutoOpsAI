# AutoOps AI — Implementation Prompts

## What These Files Are

Each file in this directory is a self-contained implementation prompt for a Claude Code agent. Together, they guide the full build of AutoOps AI from an empty repository to a production-grade system with auth, RBAC, audit logging, a React dashboard, MS Teams Adaptive Cards, local Ollama inference, and automated infrastructure remediation.

## How to Use Them

1. Work through the prompts **strictly in order** — each one builds on the output of the previous.
2. **Run the test criteria** before moving on. If the tests fail, fix the issues before starting the next step. Skipping a failing test creates compounding problems.
3. **One prompt per agent session.** Give the agent the full content of the prompt file. The agent should read the referenced source files (listed in "Context"), write or modify the listed files, and verify the result.
4. The prompts assume the working directory is `/Users/dattaikhe/LLM/AutoOpsAI` at the start of every session.
5. Do **not** combine multiple prompts in one session unless you are very confident they are independent (they are generally not — ordering matters).

## Dependency Chain

```
Phase 1 (00-09) — Foundation
  00 Observability stack (OPTIONAL — independent of Python project, run alongside 01-04)
  01 Project setup
  02 Core models
  03 Provider interface (depends on 02)
  04 Docker Compose provider (depends on 03)
  05 Demo target stack (depends on 04, independent infra)
  06 Metrics collector (depends on 03, 04)
  07 Observability clients (depends on 02)
  08 MongoDB setup (depends on 02)
  09 Chaos scripts (depends on 05)

Phase 2 (10-14) — Agent Brain
  10 Playbook system (depends on 02)
  11 LLM client (depends on 02, 08)
  12 Anomaly detection (depends on 02, 07)
  13 Risk classification (depends on 02, 10)
  14 Agent engine (depends on 10, 11, 12, 13, 08)

Phase 3 (15-18) — Teams & Approval
  15 Teams emulator (depends on 02, 08)
  16 Adaptive cards (depends on 02)
  17 Teams bot (depends on 16, 08)
  18 Approval router (depends on 13, 15, 17)

Phase 4 (19-24) — Remediation & Full Loop
  19 Provider factory (depends on 03, 04, 08)
  20 Remediation executor (depends on 02, 08, 10, 18, 19)
  21 WebSocket bridge (depends on 08, 19)
  22 FastAPI main (depends on 06, 08, 10, 11, 18, 20, 21)
  23 API endpoints (depends on 08, 10, 14, 20, 22)
  24 E2E test (depends on 05, 09, 15, 22, 23)

Phase 5 (25-28) — React Dashboard
  25 Frontend scaffolding (depends on 21, 23)
  26 Health and incidents views (depends on 21, 23, 25)
  27 Approval and chat views (depends on 23, 25, 26)
  28 Playbook and analytics views (depends on 23, 25, 26)

Phase 6 (29-31) — Auth & Security
  29 Auth backend (depends on 08, 22)
  30 RBAC enforcement (depends on 20, 23, 29)
  31 Audit and security (depends on 08, 22, 23, 29, 30)
```

## Prompt Index

| # | File | Title | Phase |
|---|------|--------|-------|
| 00 | phase1/00-observability-stack.md | Observability Stack (Loki + Promtail + cAdvisor) | 1 — Foundation (optional) |
| 01 | phase1/01-project-setup.md | Project Setup & Scaffolding | 1 — Foundation |
| 02 | phase1/02-core-models.md | Core Pydantic Models | 1 — Foundation |
| 03 | phase1/03-provider-interface.md | Provider Interface (ABC) | 1 — Foundation |
| 04 | phase1/04-docker-compose-provider.md | Docker Compose Provider | 1 — Foundation |
| 05 | phase1/05-demo-target-stack.md | Demo Target Stack | 1 — Foundation |
| 06 | phase1/06-metrics-collector.md | Metrics Collector | 1 — Foundation |
| 07 | phase1/07-observability-clients.md | Prometheus & Loki Clients | 1 — Foundation |
| 08 | phase1/08-mongodb-setup.md | MongoDB Setup & Beanie Documents | 1 — Foundation |
| 09 | phase1/09-chaos-scripts.md | Chaos Injection Scripts | 1 — Foundation |
| 10 | phase2/10-playbook-system.md | Playbook System & Knowledge Base | 2 — Agent Brain |
| 11 | phase2/11-llm-client.md | Ollama LLM Client | 2 — Agent Brain |
| 12 | phase2/12-anomaly-detection.md | Anomaly Detection | 2 — Agent Brain |
| 13 | phase2/13-risk-classification.md | Risk Classification | 2 — Agent Brain |
| 14 | phase2/14-agent-engine.md | Agent Engine (Core Loop) | 2 — Agent Brain |
| 15 | phase3/15-teams-emulator.md | Teams Local Emulator | 3 — Approval |
| 16 | phase3/16-adaptive-cards.md | Adaptive Card Builder | 3 — Approval |
| 17 | phase3/17-teams-bot.md | Teams Bot Implementation | 3 — Approval |
| 18 | phase3/18-approval-router.md | Approval Router | 3 — Approval |
| 19 | phase4/19-provider-factory.md | Provider Factory & Celery Tasks | 4 — Remediation |
| 20 | phase4/20-remediation-executor.md | Remediation Executor | 4 — Remediation |
| 21 | phase4/21-websocket-bridge.md | WebSocket & Redis Bridge | 4 — Remediation |
| 22 | phase4/22-fastapi-main.md | FastAPI App & Lifespan | 4 — Remediation |
| 23 | phase4/23-api-endpoints.md | All REST API Endpoints | 4 — Remediation |
| 24 | phase4/24-e2e-test.md | End-to-End Integration Test | 4 — Remediation |
| 25 | phase5/25-frontend-scaffolding.md | React Frontend Scaffolding | 5 — Dashboard |
| 26 | phase5/26-health-and-incidents-views.md | Health & Incidents Views | 5 — Dashboard |
| 27 | phase5/27-approval-and-chat-views.md | Approval & Chat Views | 5 — Dashboard |
| 28 | phase5/28-playbook-and-analytics-views.md | Playbook & Analytics Views | 5 — Dashboard |
| 29 | phase6/29-auth-backend.md | Auth Backend (JWT + bcrypt) | 6 — Security |
| 30 | phase6/30-rbac-enforcement.md | RBAC Enforcement | 6 — Security |
| 31 | phase6/31-audit-and-security.md | Audit Logging & Security Hardening | 6 — Security |

## Key Design Decisions (Carry Through All Steps)

- **All LLM inference is local via Ollama.** No calls to OpenAI, Anthropic, or any external LLM API. This is a hard constraint.
- **Two separate MongoDB instances:** `MONGODB_URL` in `.env` is the AutoOps data store (existing production MongoDB). `mongodb-demo` is the monitored target that chaos scripts can kill. They must never be the same instance.
- **No `adaptivecards` Python library.** Adaptive Card JSON is built from templates in `agent/approval/teams_cards/`.
- **`TEAMS_LOCAL_EMULATOR=true`** routes all card sends to `GET /dev/teams-cards` instead of real Teams. This must be disabled in production.
- **MS Teams is the primary external approval channel.** There is no Slack integration.
- **Static `X-API-Key` header guard** on all POST/PATCH/DELETE endpoints during Phases 4-5. JWT replaces this in Phase 6 (Step 30).
- **Celery workers are separate processes** — they cannot share in-memory state with the FastAPI app. The provider factory (`get_provider()`) is called fresh at the start of every Celery task.
- **Approval cards in the dashboard are rendered in the chat window** — the `GET /chat/{incident_id}` response includes `type="approval_card"` messages with interactive Approve/Deny/Investigate buttons. This is the primary dashboard approval channel.
- **WebSocket events follow the envelope:** `{"type": str, "data": dict, "timestamp": ISO8601}`. The `REDIS_CHANNEL` constant must be `"autoops:events"` in both `agent/tasks/events.py` and `agent/ws/manager.py`.
- **Frontend auth tokens stored in memory (not localStorage)** to avoid XSS risk. Refresh tokens stored in `sessionStorage` only.
