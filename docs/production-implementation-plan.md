# AutoOps AI - Production Implementation Plan

> **Scope:** Full production-grade build. No MVP shortcuts — MongoDB from day one (already deployed), React dashboard as the primary UI, Celery task queue, auth/RBAC, and proper observability. The focus is building the **virtual DevOps engineer** experience — a conversational, dashboard-driven AI agent that monitors, diagnoses, and remediates infrastructure issues with human-in-the-loop approval.
>
> **Assumptions:**
> - Grafana and Prometheus are **already deployed** in the server environment — we integrate with them, not deploy them.
> - Loki + Promtail are available (or will be co-deployed with the agent).
> - **The React dashboard is the primary approval and interaction channel.** MS Teams integration is deferred to a later phase — see Phase 9.
> - All LLM inference is local via Ollama — no cloud API calls.
> - **Two separate MongoDB instances/databases:** the *existing production MongoDB* is the AutoOps data store; a *separate demo MongoDB container* is the monitored target that chaos scripts can kill. These must never be the same instance.
>
> **Decision Log:**
> - *Teams integration deferred (2026-04-05):* MS Teams Adaptive Cards require Azure AD app registration, Bot Service setup, HTTPS tunneling, and Teams admin approval — significant overhead before core agent functionality is proven. The dashboard provides the same approval workflow with faster iteration. Teams will be added as an additional channel in Phase 9 once the core virtual DevOps engineer loop is solid.

---

## Pre-Requisites (Arrange Before Phase 2 Starts)

The following require setup before the agent brain can function.

### Ollama Setup (complete before Phase 2.2)

1. Install Ollama: `curl -fsSL https://ollama.ai/install.sh | sh`
2. Pull the primary model: `ollama pull llama3:8b`
3. Pull fallback model: `ollama pull mistral:7b`
4. Verify: `curl http://localhost:11434/api/tags`
5. For GPU acceleration: ensure CUDA drivers are installed; Ollama auto-detects GPU

---

## Phase 1: Project Foundation & Infrastructure Wiring

> **Goal:** Runnable Python project, provider abstraction, Docker Compose demo stack, and connection to the existing Prometheus/Grafana stack.

### 1.1 Project Scaffolding

- [ ] Initialize Python project with `pyproject.toml`:
  ```
  dependencies:
    fastapi, uvicorn[standard], docker, ollama, pydantic, pydantic-settings,
    httpx, pyyaml, pytest, pytest-asyncio, prometheus-client, celery[redis],
    redis[hiredis], motor, beanie, python-jose[cryptography],
    passlib[bcrypt], websockets, watchfiles
  ```
  Notes:
  - `redis[hiredis]` — C extension for fast Redis pub/sub (used for Celery→WebSocket bridge)
  - `watchfiles` — hot-reload of playbook YAML files without agent restart
  - `botbuilder-core`, `botbuilder-integration-aiohttp` — added in Phase 9 when Teams integration begins
- [ ] Create full directory structure per [architecture.md](architecture.md) (use production layout — no `dashboard/` Streamlit; use `frontend/` for React)
- [ ] Set up `.env` + `agent/config.py` (Pydantic Settings):
  ```
  # LLM
  OLLAMA_HOST=http://localhost:11434
  OLLAMA_MODEL=llama3:8b

  # Infrastructure
  PROVIDER_TYPE=docker_compose
  POLLING_INTERVAL_SECONDS=15

  # Database (existing MongoDB instance)
  MONGODB_URL=mongodb://autoops:secret@localhost:27017/autoops

  # Task Queue
  CELERY_BROKER_URL=redis://localhost:6379/0
  CELERY_RESULT_BACKEND=redis://localhost:6379/1

  # Observability (existing stack)
  PROMETHEUS_URL=http://prometheus:9090
  LOKI_URL=http://loki:3100
  GRAFANA_URL=http://grafana:3000

  # Teams
  # Auth
  JWT_SECRET_KEY=<generate>
  JWT_ALGORITHM=HS256
  JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
  ```
- [ ] Set up `docker-compose.agent.yml` — AutoOps AI services:
  - `autoops-agent` (FastAPI app)
  - `autoops-worker` (Celery worker)
  - `redis` (task broker + result backend)
  - Connects to the existing MongoDB, Prometheus/Grafana network
  - Note: no Teams bot dependencies in this phase — dashboard is the primary UI
- [ ] Set up Beanie ODM (async MongoDB ODM built on Motor) for document models
- [ ] Create initial MongoDB collections: incidents, actions, approvals, users, audit_log
- [ ] Create MongoDB indexes: incidents (status, severity, service, detected_at), users (username unique), audit_log (timestamp, user_id)
- [ ] Configure `prometheus-client` to expose `/metrics` endpoint — register with existing Prometheus via scrape config addition
- [ ] Note: MongoDB is already deployed in the environment — the agent connects to it, does not deploy a new instance

### 1.2 Target Infrastructure (Demo Stack)

> **Important — two separate MongoDB instances:**
> - `mongodb-demo` below is the **monitored target** — the service AutoOps watches and chaos scripts can kill.
> - The `MONGODB_URL` in `.env` points to the **existing production MongoDB** — the AutoOps data store. These are different instances on different Docker networks. Chaos scripts must never reference the production MongoDB.

- [ ] Create `infra/docker-compose/docker-compose.target.yml`:
  - **Nginx** — reverse proxy → FastAPI demo app (port `80` inside network, not exposed to host)
  - **FastAPI demo app** — REST API on port `5000`, with `/health`, `/data` (reads from mongodb-demo), `/cache` (reads from demo-redis)
  - **mongodb-demo** — MongoDB container, service name `mongodb-demo` (distinct name prevents confusion with production MongoDB)
  - **demo-redis** — Redis cache container, service name `demo-redis`
  - All services on Docker network `autoops-demo-net` (isolated from `autoops-agent-net`)
- [ ] Write FastAPI demo app (`infra/demo-app/app.py`):
  - Connects to `mongodb-demo:27017` and `demo-redis:6379` (env-configurable)
  - Endpoints: `GET /health`, `GET /data` (MongoDB read), `GET /cache` (Redis read/write)
  - Structured JSON logging to stdout (Promtail picks this up)
  - Port: `5000`
- [ ] Verify: `docker compose -f docker-compose.target.yml up` brings up all 4 services, health endpoints respond, `/data` returns data from mongodb-demo

### 1.3 Provider Interface & Docker Compose Provider

- [ ] Implement `agent/providers/base.py` — `InfrastructureProvider` ABC (per [provider-interface.md](provider-interface.md))
- [ ] Implement `agent/models.py` — Pydantic models: `ServiceInfo`, `ServiceStatus`, `MetricSnapshot`, `HealthCheckResult`, `CommandResult`, `LogEntry`
- [ ] Implement `agent/providers/docker_compose.py`:
  - `list_services()` — filter by compose project label
  - `get_service_status()` — container state, restart count, uptime
  - `get_metrics()` — parse `container.stats()` for CPU, memory, network, disk
  - `health_check()` — HTTP/TCP/command health checks per service
  - `restart_service()` — `container.restart()`
  - `exec_command()` — `container.exec_run()`
  - `get_logs()` — `container.logs()`
  - `scale_service()` — `docker compose up --scale`
  - `stop_service()` / `start_service()`
- [ ] Implement `agent/providers/registry.py` — provider factory
- [ ] Write tests: `tests/test_providers/test_docker_compose.py` (integration tests against real Docker)

### 1.4 Metrics Collector

- [ ] Implement `agent/collector/collector.py`:
  - Async polling loop (configurable interval, default 15s)
  - Calls `provider.list_services()` → `provider.get_metrics()` per service
  - Calls `provider.health_check()` per service
  - Queries existing Prometheus for historical data and alert state via PromQL HTTP API (`PROMETHEUS_URL/api/v1/query`)
  - Optionally queries Loki for log-pattern anomalies via LogQL HTTP API (`LOKI_URL/loki/api/v1/query_range`)
  - Emits `MetricSnapshot` list to the engine
- [ ] Implement `agent/collector/health_probes.py` — configurable health check per service (HTTP endpoint, TCP port, exec command)
- [ ] Implement `agent/collector/prometheus_client.py` — PromQL query helper:
  - `query(promql: str) -> list[dict]` — instant query
  - `query_range(promql: str, start, end, step) -> list[dict]` — range query
  - Used by anomaly detection for trend analysis and by the LLM for context enrichment
- [ ] Implement `agent/collector/loki_client.py` — LogQL query helper:
  - `query(logql: str, limit: int) -> list[LogEntry]`
  - Used for log-pattern anomaly detection
- [ ] Verify: collector prints metrics + Prometheus/Loki query results to console every 15s

### 1.5 Integrate with Existing Observability Stack

Since Grafana/Prometheus are already deployed, this phase wires AutoOps into the existing stack rather than deploying a new one.

- [ ] Add AutoOps agent scrape target to existing Prometheus config:
  ```yaml
  # Add to existing prometheus.yml
  - job_name: 'autoops-agent'
    static_configs:
      - targets: ['autoops-agent:8000']
    scrape_interval: 15s
  ```
- [ ] Create and import Grafana dashboards via Grafana HTTP API or provisioning:
  - `autoops-agent-overview.json` — incidents total, MTTR histogram, LLM latency, pending approvals, anomaly detection rate
  - `autoops-incidents.json` — incident timeline, resolution breakdown by severity, auto-resolved vs human-approved ratio
- [ ] If Loki + Promtail are not yet deployed, add them to `docker-compose.agent.yml`:
  - Promtail tails Docker container logs, ships to Loki
  - Loki configured as additional Grafana datasource
- [ ] If cAdvisor is not yet deployed, add it — exposes per-container metrics to existing Prometheus
- [ ] Verify: AutoOps agent metrics appear in existing Grafana, Loki log queries return container logs

### 1.6 Chaos Scripts (Failure Injection)

- [ ] `chaos/docker/kill_mongodb.sh` — `docker stop <mongodb_container>`
- [ ] `chaos/docker/spike_cpu.sh` — `docker exec <container> stress --cpu 2 --timeout 60`
- [ ] `chaos/docker/fill_redis.sh` — fill Redis to 95% memory via `redis-cli DEBUG SET-ACTIVE-EXPIRE 0` + bulk insert
- [ ] `chaos/docker/break_nginx.sh` — corrupt Nginx config and reload
- [ ] `chaos/docker/oom_demo_app.sh` — trigger OOM in demo app container
- [ ] Each script: idempotent, prints what it's doing, can be run from CI

**Phase 1 Exit Criteria:** Docker demo stack running, collector polling metrics, agent `/metrics` visible in existing Grafana, chaos scripts reliably break things, MongoDB collections and indexes created, Celery worker starts.

---

## Phase 2: Agent Brain (Detection, Diagnosis, Classification)

> **Goal:** The agent detects anomalies, matches playbooks, calls local Ollama for diagnosis, classifies risk — full reasoning pipeline.

### 2.1 Knowledge Base

- [ ] Implement `agent/knowledge/schemas.py` — Pydantic models for playbook entries (detection, remediation, rollback, template variables)
- [ ] Implement `agent/knowledge/knowledge_base.py`:
  - Load YAML files from `playbooks/general/` + `playbooks/{provider}/`
  - `match(metrics, statuses) -> list[PlaybookMatch]` — evaluate detection conditions, return ranked matches with confidence
  - Template variable resolution (`{service_name}`, `{metric_value}`, etc.)
  - Hot-reload: watch `playbooks/` directory for changes, reload without restart
- [ ] Create starter playbooks:
  - `playbooks/docker_compose/mongodb.yaml` — container crash
  - `playbooks/docker_compose/redis.yaml` — memory full
  - `playbooks/docker_compose/nginx.yaml` — 502 bad gateway
  - `playbooks/docker_compose/container_oom.yaml` — OOM kill
  - `playbooks/general/high_cpu.yaml` — sustained high CPU
  - `playbooks/general/high_memory.yaml` — sustained high memory
  - `playbooks/general/health_check_failed.yaml` — generic health check failure
  - `playbooks/general/disk_full.yaml` — disk usage critical
- [ ] Write tests: `tests/test_knowledge_base.py`

### 2.2 Ollama LLM Client

- [ ] Implement `agent/llm/client.py`:
  - Ollama Python SDK wrapper (`ollama.chat()` with `format="json"`)
  - Configurable model + host URL
  - `diagnose(anomaly, metrics, playbook_match, logs) -> Diagnosis` — structured JSON
  - `explain_for_human(diagnosis) -> str` — plain-language summary for Teams/dashboard
  - `reason_novel_issue(metrics, logs, prometheus_context) -> Diagnosis` — no playbook match
  - `generate_incident_summary(incident) -> str` — for Teams notification cards
  - Model warm-up on startup
  - Retry with exponential backoff, configurable timeout (default 30s)
  - Fallback: if Ollama is down, use playbook diagnosis directly without LLM enhancement
- [ ] Implement `agent/llm/prompts.py`:
  - System prompt: role definition, output schema, safety guardrails
  - Diagnosis prompt: metrics snapshot + anomaly + playbook context + recent logs
  - Novel issue prompt: raw metrics + logs + Prometheus trend data
  - Summary prompt: incident timeline → one-paragraph summary
  - All prompts: concise (smaller models work better with focused context)
- [ ] Write tests: `tests/test_llm_client.py` (mock Ollama for unit tests; integration test against real Ollama)

### 2.3 Anomaly Detection

- [ ] Implement `agent/engine/anomaly.py`:
  - **Threshold-based:** CPU > 90%, memory > 85%, error rate > 50%, service down (configurable in `config.yaml`)
  - **Duration-based:** sustained high CPU/memory for N minutes (uses Prometheus range query via collector)
  - **Rate-based:** error rate increasing over time (rate of change from Prometheus)
  - **Log-pattern:** regex match in recent logs via Loki query (e.g., `502 Bad Gateway` rate)
  - **Compound:** multiple conditions must be true (AND logic)
  - Returns `list[Anomaly]` with affected service, metric, severity hint, evidence
- [ ] Implement `agent/engine/risk.py`:
  - Classify action risk: LOW / MEDIUM / HIGH
  - Risk factors: service criticality (DB > app > cache > proxy), action type (observe < restart < scale < failover), blast radius (single service < cascading)
  - Override from playbook `severity` field
  - Configurable risk matrix in `config.yaml`
- [ ] Write tests: `tests/test_anomaly.py`, `tests/test_risk.py`

### 2.4 Agent Engine (Core Reasoning Loop)

- [ ] Implement `agent/engine/engine.py`:
  - `async process_cycle(snapshots, statuses)` — single iteration:
    1. Detect anomalies (threshold + Prometheus + Loki)
    2. Match playbooks
    3. LLM diagnosis (Ollama)
    4. Classify risk
    5. Emit actions → Approval Router
  - Cooldown tracking: don't re-alert for same issue within cooldown window (per playbook or global default)
  - Incident creation: write to MongoDB via Beanie ODM
  - Deduplication: if an active incident exists for the same service + issue type, update rather than create
- [ ] Implement `agent/store/incidents.py`:
  - Beanie Document models: `Incident`, `IncidentAction`, `IncidentTimeline`
  - CRUD operations: create, update status, resolve, escalate
  - Query: by status, severity, service, date range (MongoDB queries)
  - Audit log: every state change is recorded with timestamp and actor
  - Embedded documents for timeline events (natural fit for MongoDB's document model)
- [ ] Implement `agent/store/database.py`:
  - Motor async client + Beanie initialization
  - Connection pooling (Motor default pool)
  - Health check: `db.command("ping")`
- [ ] Extend `agent/models.py`: `Incident`, `Anomaly`, `Diagnosis`, `Action`, `ActionResult`, `ApprovalDecision`
- [ ] Write tests: `tests/test_engine.py`

**Phase 2 Exit Criteria:** Kill a demo stack service → agent detects, matches playbook, calls Ollama, classifies risk, creates incident in MongoDB with full diagnosis. Console output shows the complete reasoning chain.

---

## Phase 3: Dashboard Approval Flow

> **Goal:** Dashboard-driven approval workflow — the React dashboard is the primary interface for the virtual DevOps engineer. Approval cards appear in the dashboard, operators approve/deny/investigate directly, and the agent executes approved actions.
>
> **Note:** MS Teams integration is deferred to Phase 9. The dashboard provides the same approval workflow with faster iteration and no external dependencies (no Azure AD, no Bot Service, no HTTPS tunnels).

### 3.1 Approval Card Design

- [ ] Design approval card data model and UI component specs:

  **Approval Request Card (MEDIUM risk):**
  - Header: "AutoOps AI" + severity badge (amber for MEDIUM)
  - Title: incident title (e.g., "MongoDB container down")
  - Diagnosis: LLM-generated plain-language explanation
  - Facts: service name, detected time, proposed action, timeout countdown
  - Rollback plan: collapsible section
  - Action buttons: Approve (green), Deny (red), Investigate More
  - Countdown timer: 5 minutes for MEDIUM risk, deny-by-default on expiry

  **Approval Request Card (HIGH risk):** Same as MEDIUM but:
  - Red severity badge
  - No timeout — explicit approval required
  - Prominent warning: "Explicit approval required — this action will not auto-execute"
  - Rollback plan expanded by default

  **Resolution Card (replaces approval card on resolution):**
  - Green header: "Resolved"
  - Shows: who approved, when, what action was taken, verification result, resolution time
  - No action buttons

  **Auto-Resolved Notification (LOW risk):**
  - Compact notification: "Auto-resolved: {title} — {action taken} — {outcome}"
  - Informational only, no action buttons

  **Investigation Response:**
  - Detailed reasoning: log excerpts, metric trends, LLM analysis
  - Appears as a follow-up in the incident conversation
  - Still shows Approve/Deny buttons

- [ ] Store card templates in `agent/approval/card_templates/` as JSON files
- [ ] Implement `agent/approval/card_builder.py` — render card data from incident

### 3.2 Approval Router

- [ ] Implement `agent/approval/router.py`:
  - Route based on risk level:
    - **LOW** → auto-execute via Celery task, send notification to dashboard (informational only)
    - **MEDIUM** → create approval card in dashboard, start 5-minute timeout timer (Celery countdown task), deny-by-default if no response
    - **HIGH** → create approval card in dashboard, no timeout, explicit approval required
  - `request_approval(incident) -> ApprovalRequest` — creates approval record in DB, emits WebSocket event to dashboard
  - `process_decision(incident_id, decision, user) -> ApprovalDecision` — processes approve/deny/investigate from dashboard
  - Idempotent: if same incident is approved/denied twice, second call is a no-op
  - Concurrent safety: use database row-level locking to prevent race conditions on approval state
- [ ] Implement approval timeout via Celery:
  - `tasks/approval_timeout.py` — Celery task scheduled with `countdown=300` for MEDIUM risk
  - On timeout: update incident status to `denied_timeout`, emit WebSocket event to update dashboard card
  - If approved before timeout, revoke the Celery task
- [ ] Implement `agent/approval/webhook.py`:
  - Generic webhook for external integrations (future Teams, Slack, etc.)
  - `POST /api/v1/webhooks/generic` — accepts `{incident_id, action, user, token}`
  - Token-based auth
- [ ] Write tests: `tests/test_approval_router.py`

### 3.3 Dashboard Approval API

The React dashboard is the **primary** approval channel.

- [ ] Implement `agent/approval/dashboard_approval.py`:
  - API endpoints:
    - `GET /api/v1/approval/pending` — list pending approvals
    - `POST /api/v1/approval/{incident_id}/approve`
    - `POST /api/v1/approval/{incident_id}/deny`
    - `POST /api/v1/approval/{incident_id}/investigate`
  - Real-time sync: all approval state changes broadcast via WebSocket to connected dashboard clients
  - Future-proofed: when Teams is added (Phase 9), approval from either channel updates both in real-time
- [ ] Approval channel config (extensible for future channels):
  ```yaml
  approval:
    primary_channel: dashboard    # "dashboard" | "teams" | "webhook" (teams added in Phase 9)
    timeout_medium_seconds: 300
    timeout_medium_default: deny
  ```

**Phase 3 Exit Criteria:** Kill `mongodb-demo` container → agent detects → approval card data created in MongoDB → WebSocket broadcasts to dashboard → API endpoints functional for approve/deny/investigate → approval state updates correctly with timeouts. Dashboard rendering of these cards is built in Phase 5.

---

## Phase 4: Remediation & Full Loop

> **Goal:** Execute approved actions, verify outcomes, handle rollback, wire the complete detect→diagnose→approve→fix→verify loop.

### 4.1 Remediation Executor

- [ ] Implement `agent/remediation/executor.py`:
  - Receives `Action` from Approval Router (after approval)
  - Dispatches to Celery worker for execution (non-blocking)
  - Action type → provider method mapping:
    - `restart_service` → `provider.restart_service()`
    - `exec_command` → `provider.exec_command()`
    - `scale_service` → `provider.scale_service()`
    - `collect_logs` → `provider.get_logs()`
    - `health_check` → `provider.health_check()` or `provider.exec_command()`
    - `metric_check` → `provider.get_metrics()` + threshold comparison
    - `wait` → `asyncio.sleep()`
    - `escalate` → notify Teams, mark incident as escalated
  - Execute remediation steps sequentially (from playbook `remediation.steps`)
  - After each step: record result in incident timeline (MongoDB)
  - After all steps: run verification checks
  - Report outcome: update incident status, send dashboard notification via WebSocket event
- [ ] Implement `agent/remediation/rollback.py`:
  - Triggered if verification fails after remediation
  - Execute rollback steps from playbook `rollback.steps`
  - If rollback also fails → escalate (notify dashboard, mark incident as `escalated`)
  - Rollback is itself recorded in the incident timeline
- [ ] Implement `agent/tasks/provider_factory.py` — creates a provider instance from env config:
  - Called at the start of each Celery task (workers are separate processes, can't share the FastAPI app's in-memory provider)
  - Reads `PROVIDER_TYPE` from env, instantiates and returns the correct provider
  - Provider is stateless per task — created fresh, used, discarded
  - Example: `get_provider() -> InfrastructureProvider` — `DockerComposeProvider(project_name=..., compose_file=...)`
- [ ] Implement Celery tasks in `agent/tasks/`:
  - `remediation_task.py` — calls `get_provider()`, executes remediation steps, writes each step result to MongoDB
  - `verification_task.py` — calls `get_provider()`, runs post-remediation verification
  - `rollback_task.py` — calls `get_provider()`, executes rollback steps
  - All tasks: idempotent (safe to retry), timeout after configurable max duration, use `task_acks_late=True` so task isn't acknowledged until complete
- [ ] Write tests: `tests/test_remediation.py`, `tests/test_rollback.py`

### 4.2 Wire the Full Loop

- [ ] Implement `agent/ws/manager.py` — WebSocket connection manager:
  - Maintains a set of active WebSocket connections
  - `broadcast(event: dict)` — sends to all connected clients
  - `subscribe_to_redis()` — background task that reads from Redis pub/sub channel `autoops:events` and calls `broadcast()`
  - This is the Celery→WebSocket bridge: Celery workers publish events to Redis; FastAPI subscribes and pushes to browsers

- [ ] Implement `agent/tasks/events.py` — event publisher used by Celery tasks:
  - `publish_event(event_type: str, data: dict)` — pushes to Redis channel `autoops:events`
  - Called at the end of each Celery task (remediation complete, verification passed, incident resolved)
  - Uses synchronous Redis client inside Celery (not async)

- [ ] Implement `agent/main.py` — FastAPI app lifecycle:
  - On startup: create provider, load playbooks, init MongoDB (Beanie), start Redis pub/sub subscriber, warm up Ollama, start collector loop
  - On shutdown: stop collector, stop Redis subscriber, cleanup
  - Health check: `/health` includes component status (provider, DB, Redis, Celery, Ollama)

- [ ] Wire complete pipeline:
  ```
  Collector → Engine → Approval Router → Dashboard (WebSocket)
                                            ↓
                                     User clicks Approve (Dashboard UI)
                                            ↓
                                   Dashboard API → Router
                                            ↓
                              Remediation Executor → Celery task
                                            ↓
                                    Celery worker executes
                                    (provider_factory → Docker/K8s)
                                            ↓
                              Verification → publish_event() → Redis
                                            ↓
                         FastAPI Redis subscriber → WebSocket broadcast
                                            ↓
                            Update: MongoDB + Dashboard UI (real-time)
  ```
- [ ] End-to-end integration test script (`tests/e2e/test_full_loop.py`):
  1. Start demo stack (`docker-compose.target.yml`)
  2. Start AutoOps agent
  3. Run `chaos/docker/kill_mongodb.sh` (kills `mongodb-demo` container — not production MongoDB)
  4. Assert: incident created in AutoOps MongoDB within 30s
  5. Assert: approval card available at `GET /api/v1/approval/pending`
  6. Approve via dashboard API: `POST /api/v1/approval/{incident_id}/approve`
  7. Assert: `mongodb-demo` container restarted
  8. Assert: verification passes (demo app `/health` returns 200)
  9. Assert: incident status = `resolved` in AutoOps MongoDB
  10. Assert: WebSocket event broadcast for resolution

### 4.3 API Endpoints (Complete)

> **Auth note:** Endpoints in this phase are built without JWT auth — full RBAC is added in Phase 6. During Phases 4–5, the API must be on an internal network only (not publicly reachable). Add a static `X-API-Key` header check on all state-changing endpoints (`POST`, `PATCH`, `DELETE`) as a minimal guard: set `API_KEY=<random>` in `.env`, reject requests missing it with `403`. Replace with JWT in Phase 6.

- [ ] **System:**
  - `GET /api/v1/health` — agent health (includes component statuses)
  - `GET /api/v1/status` — all monitored service statuses
  - `GET /api/v1/metrics/{service_name}` — detailed metrics for one service
  - `GET /metrics` — Prometheus scrape endpoint (not under `/api/v1`)
- [ ] **Incidents:**
  - `GET /api/v1/incidents` — list (filter by status, severity, service, date range; paginated)
  - `GET /api/v1/incidents/{id}` — full detail with timeline, actions, diagnosis
  - `POST /api/v1/incidents/{id}/escalate` — manual escalation
- [ ] **Approval:**
  - `GET /api/v1/approval/pending` — pending approvals
  - `POST /api/v1/approval/{id}/approve` — approve (from dashboard)
  - `POST /api/v1/approval/{id}/deny` — deny (from dashboard)
  - `POST /api/v1/approval/{id}/investigate` — request more detail
- [ ] **Agent Control:**
  - `POST /api/v1/agent/start` — start monitoring loop
  - `POST /api/v1/agent/stop` — stop monitoring loop
  - `GET /api/v1/agent/config` — current config
  - `PATCH /api/v1/agent/config` — update config at runtime
- [ ] **Playbooks:**
  - `GET /api/v1/playbooks` — list all
  - `GET /api/v1/playbooks/{id}` — get one
  - `POST /api/v1/playbooks` — create
  - `PUT /api/v1/playbooks/{id}` — update
  - `DELETE /api/v1/playbooks/{id}` — delete
- [ ] **Chat:**
  - `GET /api/v1/chat/{incident_id}` — conversation log for an incident
  - `POST /api/v1/chat` — ask agent about current system state (interactive)
- [ ] **Webhooks:**
  - `POST /api/v1/webhooks/teams/events` — Teams bot callback (Phase 9 — stubbed, returns 501 until Teams is configured)
  - `POST /api/v1/webhooks/generic` — generic webhook
- [ ] **WebSocket:**
  - `WS /api/v1/ws/events` — real-time event stream (metric updates, anomalies, approvals, resolutions)

**Phase 4 Exit Criteria:** Complete loop works end-to-end via dashboard: chaos (`kill mongodb-demo`) → detection → Ollama diagnosis → approval card in dashboard → approve → Celery task restarts container → verification → resolved in MongoDB → WebSocket broadcasts resolution to browser. All API endpoints functional with static API key guard. Celery tasks executing reliably with Redis pub/sub bridge confirmed.

---

## Phase 5: React Dashboard

> **Goal:** Production React + Tailwind dashboard — the primary interface for the virtual DevOps engineer. Incident timeline, real-time health, approval management, agent conversation, playbook editor, analytics. This is where operators interact with the AI agent.

### 5.1 Frontend Scaffolding

- [ ] Initialize React project (Vite + TypeScript + Tailwind CSS):
  ```
  frontend/
  ├── src/
  │   ├── api/                    # API client (axios/fetch wrapper)
  │   ├── components/
  │   │   ├── layout/             # Shell, sidebar, header
  │   │   ├── incidents/          # Incident list, detail, timeline
  │   │   ├── approval/           # Approval cards, pending list
  │   │   ├── health/             # Service health cards
  │   │   ├── chat/               # Agent conversation view
  │   │   ├── playbooks/          # Playbook browser and editor
  │   │   └── analytics/          # MTTR charts, resolution stats
  │   ├── hooks/                  # useWebSocket, useAuth, etc.
  │   ├── pages/                  # Route-level pages
  │   ├── store/                  # State management (Zustand or React Query)
  │   └── types/                  # TypeScript types matching API models
  ├── tailwind.config.js
  ├── vite.config.ts
  └── package.json
  ```
- [ ] Set up API client with JWT auth, auto-refresh tokens, error handling
- [ ] Set up WebSocket client for real-time events (`/api/v1/ws/events`)
- [ ] Set up React Router for navigation

### 5.2 Dashboard Views

- [ ] **System Health** (`/`):
  - Service cards grid: name, state (running/stopped/error), CPU gauge, memory gauge, uptime
  - Color-coded: green (healthy), amber (warning), red (down)
  - Real-time updates via WebSocket
  - Click a service → detail panel with metrics history (embedded Grafana panel or Chart.js)

- [ ] **Incidents** (`/incidents`):
  - Table: title, severity badge, status badge, service, detected time, resolution time
  - Filters: status (active/resolved/escalated), severity (LOW/MEDIUM/HIGH), service, date range
  - Click → incident detail page

- [ ] **Incident Detail** (`/incidents/:id`):
  - Header: title, severity, status, service, timing
  - Diagnosis panel: LLM explanation, confidence score, matched playbook
  - Timeline: chronological events (detected, approval requested, approved by X, remediation started, verification passed, resolved)
  - Agent Chat: conversational view of agent reasoning (same format as [api-design.md](api-design.md) `GET /chat/{incident_id}`)
  - Approval card (if pending): Approve / Deny / Investigate buttons
  - Metrics at detection: snapshot of service metrics when the incident was created

- [ ] **Approval Queue** (`/approvals`):
  - List of pending approval cards
  - Each card: severity badge, title, diagnosis summary, proposed action, rollback plan, timeout countdown (MEDIUM), action buttons
  - Resolved cards: show outcome inline
  - Real-time: new cards appear via WebSocket, cards update when resolved

- [ ] **Agent Chat** (`/chat`):
  - Interactive chat interface: ask the agent about current system state
  - Per-incident chat threads
  - Approval cards render as interactive UI blocks within the chat

- [ ] **Playbook Manager** (`/playbooks`):
  - List all playbooks with search/filter
  - View playbook detail (rendered YAML → structured view)
  - Create/edit playbook (YAML editor with syntax highlighting + live validation)
  - Delete playbook (with confirmation)

- [ ] **Analytics** (`/analytics`):
  - MTTR trend (line chart, last 30 days)
  - Incidents by severity (pie/bar chart)
  - Auto-resolved vs human-approved ratio
  - Top services by incident count
  - Approval response time distribution
  - Embedded Grafana panels (via iframe or Grafana embedding API) for deeper metrics

### 5.3 Authentication UI

- [ ] Login page (username/password → JWT)
- [ ] Token refresh on expiry
- [ ] Protected routes (redirect to login if unauthenticated)
- [ ] User avatar + role display in header

### 5.4 Build & Deploy

- [ ] Dockerize frontend: `frontend/Dockerfile` (multi-stage: build with Node, serve with Nginx)
- [ ] Add to `docker-compose.agent.yml` as `autoops-dashboard` service
- [ ] Nginx config: serve React app, proxy `/api/` to FastAPI backend
- [ ] Environment-based config: API base URL, WebSocket URL

**Phase 5 Exit Criteria:** Fully functional React dashboard with all views, real-time updates via WebSocket, approval actions working end-to-end, playbook CRUD, analytics charts. The dashboard is the complete virtual DevOps engineer interface.

---

## Phase 6: Authentication, RBAC & Security

> **Goal:** Production-grade auth, role-based permissions, audit logging, secure communication.

### 6.1 Authentication

- [ ] Implement `agent/auth/` module:
  - `auth.py` — JWT token creation, validation, refresh
  - `users.py` — user CRUD (MongoDB via Beanie)
  - `passwords.py` — bcrypt hashing
  - `dependencies.py` — FastAPI dependency: `get_current_user`, `require_role`
- [ ] MongoDB collection: `users` (id, username, email, hashed_password, role, created_at, last_login)
- [ ] API endpoints:
  - `POST /api/v1/auth/login` — username + password → JWT access + refresh tokens
  - `POST /api/v1/auth/refresh` — refresh token → new access token
  - `GET /api/v1/auth/me` — current user profile
- [ ] First-run setup: create default admin user (password from env var, must be changed on first login)

### 6.2 Role-Based Access Control

- [ ] Roles: `admin`, `operator`, `viewer`
- [ ] Permission matrix:

  | Action | Admin | Operator | Viewer |
  |---|---|---|---|
  | View incidents | Yes | Yes | Yes |
  | View health/metrics | Yes | Yes | Yes |
  | Approve/deny (MEDIUM) | Yes | Yes | No |
  | Approve/deny (HIGH) | Yes | No | No |
  | Start/stop agent | Yes | No | No |
  | Manage playbooks | Yes | Yes (edit) | No |
  | Manage users | Yes | No | No |
  | Update config | Yes | No | No |

- [ ] Enforce RBAC on all API endpoints via FastAPI dependencies
- [ ] When Teams is added (Phase 9): map Teams user identity (Azure AD UPN) to AutoOps user → apply role permissions

### 6.3 Audit Logging

- [ ] MongoDB collection: `audit_log` (id, timestamp, user_id, action, resource_type, resource_id, detail, ip_address)
- [ ] TTL index on `audit_log.timestamp` for automatic expiry (configurable retention, default 90 days)
- [ ] Log all state-changing actions: approvals, denials, config changes, playbook edits, agent start/stop, user management
- [ ] API endpoint: `GET /api/v1/audit` (admin only) — filterable audit log
- [ ] Dashboard view: audit log table (admin only)

### 6.4 Security Hardening

- [ ] HTTPS termination (TLS) — via reverse proxy (Nginx/Traefik) in front of FastAPI
- [ ] CORS configuration: allow only dashboard origin
- [ ] Rate limiting on auth endpoints (prevent brute force)
- [ ] Generic webhook token-based auth (for future Teams/Slack integration)
- [ ] Input validation on all endpoints (Pydantic handles most of this)
- [ ] No secrets in logs — redact sensitive data in all log output
- [ ] Docker: run containers as non-root user

**Phase 6 Exit Criteria:** JWT auth working, RBAC enforced on all endpoints, audit log captures all actions, HTTPS configured.

---

## Phase 7: Kubernetes Provider

> **Goal:** Full Kubernetes support — provider implementation, K8s-specific playbooks, chaos scripts, tested on real cluster.

### 7.1 Kubernetes Provider Implementation

- [ ] Implement `agent/providers/kubernetes.py` (per [provider-interface.md](provider-interface.md)):
  - `list_services()` — list pods in namespace, group by deployment/statefulset
  - `get_service_status()` — pod phase, restart count, conditions, events
  - `get_metrics()` — query metrics-server API or existing Prometheus (PromQL: `container_cpu_usage_seconds_total`, `container_memory_usage_bytes`)
  - `health_check()` — readiness/liveness probe status, or HTTP check against service ClusterIP
  - `restart_service()` — rollout restart (patch deployment annotation)
  - `exec_command()` — `kubectl exec` via Python kubernetes client stream API
  - `get_logs()` — pod logs via core API
  - `scale_service()` — patch deployment replica count
  - `stop_service()` — scale to 0
  - `start_service()` — scale to previous replica count (stored in annotation)
  - `get_events()` — list namespaced events for the resource
  - `rollback_service()` — rollout undo
- [ ] Handle multi-container pods (select container by name or default to first)
- [ ] Handle StatefulSets vs Deployments vs DaemonSets
- [ ] Write tests: `tests/test_providers/test_kubernetes.py` (use kind/minikube for integration tests)

### 7.2 Kubernetes Playbooks

- [ ] `playbooks/kubernetes/pod_crash_loop.yaml` — CrashLoopBackOff detection and remediation
- [ ] `playbooks/kubernetes/node_pressure.yaml` — node memory/disk pressure
- [ ] `playbooks/kubernetes/service_unreachable.yaml` — service endpoint has no ready pods
- [ ] `playbooks/kubernetes/pvc_pending.yaml` — PersistentVolumeClaim stuck in Pending
- [ ] `playbooks/kubernetes/image_pull_backoff.yaml` — ImagePullBackOff
- [ ] `playbooks/kubernetes/oom_killed.yaml` — OOMKilled pod
- [ ] `playbooks/kubernetes/hpa_maxed.yaml` — HPA at max replicas but still under pressure

### 7.3 Kubernetes Chaos Scripts

- [ ] `chaos/kubernetes/kill_pod.sh` — `kubectl delete pod <name> --grace-period=0`
- [ ] `chaos/kubernetes/drain_node.sh` — `kubectl drain <node> --ignore-daemonsets`
- [ ] `chaos/kubernetes/network_partition.sh` — NetworkPolicy to block traffic
- [ ] `chaos/kubernetes/cpu_stress.sh` — deploy a stress pod
- [ ] `chaos/kubernetes/oom_pod.sh` — deploy a pod that exceeds memory limits

### 7.4 Kubernetes-Specific Metrics Integration

- [ ] Query existing Prometheus for K8s-specific metrics:
  - `kube_pod_status_phase` — pod phase
  - `kube_pod_container_status_restarts_total` — restart count
  - `kube_node_status_condition` — node conditions
  - `kube_deployment_status_replicas_available` — available replicas
  - `container_cpu_usage_seconds_total` — CPU usage (from cAdvisor/kubelet)
  - `container_memory_working_set_bytes` — memory usage
- [ ] Add K8s-specific Grafana dashboards (or verify existing ones cover these metrics)

**Phase 7 Exit Criteria:** Full K8s provider passes all integration tests on kind/minikube. K8s playbooks match and resolve CrashLoopBackOff, OOMKilled, node pressure scenarios. Works with existing Prometheus K8s metrics.

---

## Phase 8: Learning Loop & Predictive Analysis

> **Goal:** Agent learns from resolved incidents, suggests new playbooks, and predicts issues before they occur.

### 8.1 Learning Loop

- [ ] After a novel issue (no playbook match) is resolved, agent generates a playbook suggestion:
  - LLM (Ollama) receives: anomaly data, diagnosis, actions taken, outcome
  - LLM generates: playbook YAML matching the pattern
  - Suggestion posted to Teams as a card: "I resolved a new type of issue. Want to add this to the playbook?" with View / Approve / Edit / Dismiss buttons
  - Approved suggestions are written to `playbooks/generated/` and auto-loaded
- [ ] Dashboard: playbook suggestion review page
  - Show generated YAML with syntax highlighting
  - Edit before saving
  - Approve → saves to `playbooks/generated/{id}.yaml`
  - Dismiss → discarded (but logged in audit)
- [ ] Track playbook effectiveness:
  - `playbook_hits` — how often each playbook matches
  - `playbook_success_rate` — % of times remediation succeeds
  - Surface in analytics dashboard

### 8.2 Predictive Analysis

- [ ] Implement `agent/engine/predictor.py`:
  - Queries Prometheus for metric trends (rate of change over last 1h, 6h, 24h)
  - Linear extrapolation: "at this rate, memory will hit 90% in ~20 minutes"
  - Pattern matching: "CPU spike pattern similar to incident inc_20260401_003 which required a restart"
  - LLM-enhanced: feed trend data to Ollama → natural-language prediction
- [ ] Proactive alerts:
  - Dashboard notification: "Memory trending toward 90% on demo-app, ETA 20 minutes. Scale up now?"
  - Actionable card: Scale Up / Dismiss / Monitor
  - If Scale Up is approved, execute scale immediately
- [ ] Dashboard: prediction panel showing trending metrics and ETA to threshold

**Phase 8 Exit Criteria:** Agent suggests playbooks after novel incidents. Predictive alerts fire for trending metrics. Playbook effectiveness tracking visible in analytics.

---

## Phase 9: MS Teams Integration (Deferred)

> **Goal:** Add MS Teams as an additional approval and notification channel alongside the dashboard. Teams Adaptive Cards for approval flow, interactive buttons, proactive notifications.
>
> **Pre-requisite:** Complete Phases 1–5 first. The core virtual DevOps engineer loop must be working end-to-end via the dashboard before adding Teams.

### 9.1 Azure Bot Registration & Teams App Setup

1. **Azure AD App Registration:**
   - Go to Azure Portal → Azure Active Directory → App Registrations → New Registration
   - Name: `AutoOps AI Bot`, Supported account types: *Single tenant*
   - Note down the `Application (client) ID` → this is `TEAMS_APP_ID`
   - Under Certificates & Secrets → New client secret → note the secret value → this is `TEAMS_APP_PASSWORD`

2. **Azure Bot Service:**
   - Go to Azure Portal → Create Resource → Azure Bot
   - Bot handle: `autoops-ai`, Pricing tier: F0 (free) or S1
   - Use the App ID from step 1
   - Under Channels → Microsoft Teams → Enable

3. **Set Messaging Endpoint:**
   - In Azure Bot Service → Configuration → Messaging endpoint: `https://<your-server-hostname>/api/v1/webhooks/teams/events`
   - The endpoint must be HTTPS — for local dev use `devtunnel` (Microsoft's free tool): `devtunnel host --port 8000`

4. **Teams App Manifest:**
   - Create manifest zip: `teams-app/manifest.json` + two icon files (color 192×192, outline 32×32)
   - Get Teams admin to sideload, or publish to org app catalog via Teams Admin Center
   - Install the bot in the designated ops channel

### 9.2 Teams Adaptive Card Design

- [ ] Convert dashboard approval card data model to Teams Adaptive Card JSON schemas
- [ ] Adaptive Card types: approval request (MEDIUM/HIGH), resolution, auto-resolved notification, investigation response
- [ ] Store card templates in `agent/approval/teams_cards/` as JSON files
- [ ] Implement `agent/approval/teams_card_builder.py` — render Adaptive Card JSON from incident data

### 9.3 Teams Bot Implementation

- [ ] Add dependencies: `botbuilder-core`, `botbuilder-integration-aiohttp`
- [ ] Implement `agent/approval/teams_bot.py`:
  - `TeamsApprovalBot` class using Microsoft Bot Framework SDK
  - `on_invoke_activity()` — handles `Action.Execute` callbacks from Adaptive Card buttons
  - `send_approval_card(channel_id, incident)` — sends Adaptive Card to Teams channel
  - `update_card(activity_id, updated_card)` — replaces approval card with resolution card in-place
  - `send_notification(channel_id, message)` — LOW risk auto-resolved notifications
  - Webhook signature verification (HMAC) on all incoming Teams callbacks
  - Map Teams user identity (Azure AD UPN) to AutoOps user for audit trail and RBAC
- [ ] Implement `agent/approval/teams_webhook.py`:
  - FastAPI route: `POST /api/v1/webhooks/teams/events`
  - Validates authentication token from Teams
  - Routes to `TeamsApprovalBot.on_invoke_activity()`
- [ ] Implement local Teams emulator for development:
  - `agent/approval/teams_emulator.py` — activated by `TEAMS_LOCAL_EMULATOR=true`
  - `GET /dev/teams-cards` — renders pending Adaptive Cards as plain HTML
  - `POST /dev/teams-cards/{incident_id}/approve|deny|investigate` — simulates button click
- [ ] Store Teams conversation references in MongoDB for proactive messaging

### 9.4 Multi-Channel Approval Sync

- [ ] Update `agent/approval/router.py` to support Teams as an approval channel:
  - Route to Teams AND/OR dashboard based on config
  - If approved via dashboard, Teams card updates to “Resolved”; if approved via Teams, dashboard updates in real-time via WebSocket
- [ ] Update approval channel config:
  ```yaml
  approval:
    primary_channel: teams        # "teams" | "dashboard" | "webhook"
    fallback_channel: dashboard   # Used if primary is unreachable
    timeout_medium_seconds: 300
    timeout_medium_default: deny
  ```
- [ ] Add `.env` variables: `TEAMS_APP_ID`, `TEAMS_APP_PASSWORD`, `TEAMS_TENANT_ID`, `TEAMS_WEBHOOK_URL`
- [ ] Write tests: `tests/test_teams_bot.py` (mock Bot Framework adapter)

**Phase 9 Exit Criteria:** Teams Adaptive Cards sent to configured Teams channel, interactive approve/deny/investigate buttons work, approval state syncs between Teams and dashboard in real-time, Teams emulator works for local development.

  > **Why Teams and not Slack:** Enterprise teams overwhelmingly use MS Teams. Teams Adaptive Cards have first-class support for interactive buttons and are already trusted by enterprise IT security departments.

  Post-Teams, additional notification channels can be added:
  - Email (fallback for organisations without Teams)
  - PagerDuty (create/resolve incidents)
  - Slack (Bot with interactive messages)
  - Generic webhook for custom integrations

---

## Phase 10: Production Hardening & Deployment

> **Goal:** Production-ready deployment, resilience, monitoring of the agent itself, and operational runbooks.

### 10.1 Agent Self-Monitoring

- [ ] Prometheus alerting rules (`prometheus/autoops-alerts.yml`):
  - `AutoOpsAgentDown` — agent `/health` endpoint unreachable for > 1 minute
  - `AutoOpsOllamaDown` — Ollama health check failing
  - `AutoOpsHighLLMLatency` — LLM inference p95 > 10s
  - `AutoOpsStuckApprovals` — approvals pending > 30 minutes with no response
  - `AutoOpsCeleryBacklog` — Celery queue depth > 10
  - `AutoOpsDBConnectionPoolExhausted` — all MongoDB connections in use
- [ ] Grafana alert notifications → dashboard (and Teams channel if configured)
- [ ] Agent exposes detailed health: `/health` returns component-level status:
  ```json
  {
    "status": "degraded",
    "components": {
      "database": "healthy",
      "celery": "healthy",
      "ollama": "unhealthy",
      "teams_bot": "healthy",
      "collector": "running",
      "provider": "docker_compose"
    },
    "degraded_reason": "Ollama unreachable — falling back to playbook-only diagnosis"
  }
  ```

### 10.2 Resilience & Graceful Degradation

- [ ] **Ollama down:** Agent continues with playbook-only diagnosis (no LLM enhancement), flags it in dashboard
- [ ] **Teams unreachable (when configured):** Fall back to dashboard-only approval, queue Teams notifications for retry
- [ ] **MongoDB down:** Buffer incidents in memory (bounded queue), flush when DB recovers
- [ ] **Celery/Redis down:** Execute remediation inline (synchronous fallback), log warning
- [ ] **Provider unreachable:** Pause collector, alert in dashboard, resume when provider is back
- [ ] Circuit breaker pattern on all external calls (Ollama, Teams, Prometheus, Loki)
- [ ] Structured logging (JSON) with correlation IDs for tracing

### 10.3 Deployment

- [ ] `docker-compose.agent.yml` — complete production deployment:
  ```yaml
  services:
    autoops-agent:
      image: autoops-ai/agent:latest
      environment: [... from .env]
      depends_on: [redis]
      restart: unless-stopped
      healthcheck:
        test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
        interval: 30s
        timeout: 10s
        retries: 3
      # Connects to existing MongoDB instance via MONGODB_URL env var

    autoops-worker:
      image: autoops-ai/agent:latest
      command: celery -A agent.tasks worker --loglevel=info --concurrency=4
      depends_on: [redis]
      restart: unless-stopped

    autoops-dashboard:
      image: autoops-ai/dashboard:latest
      depends_on: [autoops-agent]
      restart: unless-stopped

    redis:
      image: redis:7-alpine
      restart: unless-stopped
  ```
- [ ] Helm chart for Kubernetes deployment (`deploy/helm/autoops-ai/`):
  - Deployment: agent, worker, dashboard
  - ConfigMap for MongoDB connection string (uses existing MongoDB instance)
  - Service + Ingress for dashboard and API
  - ConfigMap for playbooks
  - Secret for credentials
  - ServiceMonitor for Prometheus Operator integration
- [ ] CI/CD pipeline (GitHub Actions or GitLab CI):
  - Lint + type check (ruff, mypy)
  - Unit tests (pytest)
  - Integration tests (Docker-based)
  - Build Docker images
  - Push to registry
  - Deploy to staging → smoke test → deploy to production

### 10.4 Operational Runbooks

- [ ] `docs/runbook-deployment.md` — how to deploy and upgrade
- [ ] `docs/runbook-teams-setup.md` — Azure Bot registration, Teams app setup, troubleshooting (for Phase 9)
- [ ] `docs/runbook-ollama-setup.md` — Ollama installation, model selection, GPU setup, performance tuning
- [ ] `docs/runbook-troubleshooting.md` — common issues and fixes
- [ ] `docs/runbook-adding-providers.md` — how to implement a new provider
- [ ] `docs/runbook-adding-playbooks.md` — how to write and test playbooks

**Phase 10 Exit Criteria:** Agent runs reliably in production, self-monitoring alerts are firing correctly, graceful degradation works for all failure modes, deployment is automated, runbooks are complete.

---

## Phase 11: Additional Providers & Extensibility

> **Goal:** Support AWS ECS, Nomad, bare-metal, and a provider SDK for community contributions.

### 11.1 AWS ECS Provider

- [ ] `agent/providers/ecs.py`:
  - Uses `boto3` ECS client
  - `list_services()` — list ECS services in cluster
  - `get_metrics()` — CloudWatch metrics (or existing Prometheus with CloudWatch exporter)
  - `restart_service()` — force new deployment
  - `scale_service()` — update desired count
  - `get_logs()` — CloudWatch Logs (or Loki if shipping ECS logs)

### 11.2 HashiCorp Nomad Provider

- [ ] `agent/providers/nomad.py`:
  - Uses Nomad HTTP API
  - `list_services()` — list allocations in namespace
  - `restart_service()` — restart allocation
  - `scale_service()` — update job group count

### 11.3 Provider SDK

- [ ] `docs/provider-sdk.md` — documentation for implementing custom providers
- [ ] `agent/providers/template.py` — starter template with all methods stubbed
- [ ] Provider test harness: `tests/provider_conformance.py` — generic test suite that any provider can run against to verify correctness

**Phase 11 Exit Criteria:** At least one additional provider (ECS or Nomad) working. Provider SDK documented with a usable template and conformance tests.

---

## Dependency Map

```
Phase 1 (Foundation)
  ├── 1.1 Project Setup
  ├── 1.2 Target Stack ──────────────────────────────────────┐
  ├── 1.3 Provider Interface + Docker Provider                │
  ├── 1.4 Metrics Collector (depends on 1.3, 1.5)            │
  ├── 1.5 Integrate with Existing Observability               │
  └── 1.6 Chaos Scripts (depends on 1.2) ───────────────────┐│
                                                              ││
Phase 2 (Agent Brain)                                         ││
  ├── 2.1 Knowledge Base                                      ││
  ├── 2.2 Ollama LLM Client                                  ││
  ├── 2.3 Anomaly Detection + Risk                            ││
  └── 2.4 Engine (depends on 2.1, 2.2, 2.3, 1.4)            ││
                                                              ││
Phase 3 (Dashboard Approval)                                  ││
  ├── 3.1 Approval Card Design                                ││
  ├── 3.2 Approval Router                                     ││
  └── 3.3 Dashboard Approval API                              ││
                                                              ││
Phase 4 (Remediation + Full Loop)                             ││
  ├── 4.1 Remediation Executor (depends on 1.3)               ││
  ├── 4.2 Wire Full Loop (depends on 2.4, 3.2, 4.1) ◄───────┘│
  └── 4.3 API Endpoints                                        │
                                                               │
Phase 5 (React Dashboard — PRIMARY UI)                         │
  ├── 5.1 Frontend Scaffolding                                 │
  ├── 5.2 Dashboard Views (depends on 4.3)                     │
  ├── 5.3 Auth UI (depends on 6.1)                             │
  └── 5.4 Build + Deploy                                       │
                                                               │
Phase 6 (Auth + Security) ─── can start in parallel with 5 ───┤
  ├── 6.1 Authentication                                       │
  ├── 6.2 RBAC                                                 │
  ├── 6.3 Audit Logging                                        │
  └── 6.4 Security Hardening                                   │
                                                               │
Phase 7 (Kubernetes Provider) ─── can start after Phase 4 ────┤
  ├── 7.1 K8s Provider                                         │
  ├── 7.2 K8s Playbooks                                        │
  ├── 7.3 K8s Chaos Scripts                                    │
  └── 7.4 K8s Metrics Integration                              │
                                                               │
Phase 8 (Learning + Prediction) ─── after Phase 4 ────────────┤
  ├── 8.1 Learning Loop                                        │
  └── 8.2 Predictive Analysis                                  │
                                                               │
Phase 9 (MS Teams) ─── after Phase 5 (dashboard working) ─────┤
  ├── 9.1 Azure Bot + Teams App Setup                          │
  ├── 9.2 Adaptive Card Design                                 │
  ├── 9.3 Teams Bot Implementation                             │
  └── 9.4 Multi-Channel Approval Sync                          │
                                                               │
Phase 10 (Production Hardening) ─── after Phase 6 ────────────┘
  ├── 10.1 Self-Monitoring
  ├── 10.2 Resilience
  ├── 10.3 Deployment (Docker Compose + Helm)
  └── 10.4 Runbooks

Phase 11 (Additional Providers) ─── after Phase 10
  ├── 11.1 ECS Provider
  ├── 11.2 Nomad Provider
  └── 11.3 Provider SDK
```

---

## Parallelization Opportunities

| Person | Phase 1-2 | Phase 3-4 | Phase 5-6 | Phase 7+ |
|---|---|---|---|---|
| **Dev A** (Backend/AI) | Provider interface, LLM client, Engine | Wire full loop, Celery tasks | Auth/RBAC backend | Learning loop, predictor |
| **Dev B** (Backend) | Target stack, Knowledge base, Anomaly detection | Remediation executor, API endpoints | Audit logging, security hardening | K8s provider |
| **Dev C** (Infra/DevOps) | Observability integration, chaos scripts | Approval router, webhook implementation | Deployment (Docker + Helm), CI/CD | Teams integration (Phase 9), provider SDK |
| **Dev D** (Frontend) | — | Approval card design, dashboard API | React dashboard (all views) | Dashboard analytics, playbook editor |

---

## Technology Stack (Production)

| Layer | Technology | Rationale |
|---|---|---|
| **Language** | Python 3.11+ | Team expertise, rich DevOps ecosystem |
| **Backend** | FastAPI + Uvicorn | Async, OpenAPI docs, WebSocket support |
| **LLM** | Ollama (local) — Llama 3, Mistral, Qwen 2.5 | Air-gapped, no data leaves the network |
| **Task Queue** | Celery + Redis | Reliable async execution, retries, timeouts |
| **Database** | MongoDB (existing) + Motor (async driver) + Beanie (ODM) | Already deployed; document model fits incident/timeline data naturally; no separate migration tool needed |
| **Metrics** | Existing Prometheus + cAdvisor | Already deployed — agent integrates via PromQL API |
| **Logs** | Existing Loki + Promtail | Already deployed — agent queries via LogQL API |
| **Observability UI** | Existing Grafana | Already deployed — agent adds dashboards and scrape targets |
| **Approval (primary)** | React dashboard | Conversational UI with interactive approval cards; no external dependencies |
| **Approval (future)** | MS Teams Adaptive Cards (Phase 9) | Enterprise channel integration — added after core loop is proven |
| **Dashboard** | React + TypeScript + Tailwind CSS + Vite | Production-grade SPA |
| **Auth** | JWT + bcrypt + RBAC | Standard, no external auth dependency |
| **Infrastructure providers** | Docker SDK, kubernetes Python client, boto3 | One provider per platform |
| **Deployment** | Docker Compose (single-node), Helm (K8s) | Covers both deployment targets |

---

## Key Risk Mitigations

| Risk | Mitigation |
|---|---|
| Ollama inference latency | Pre-warm model on startup; Mistral 7B as fast fallback; playbook-only mode if LLM is down; cache recent diagnoses |
| Teams webhook unreachable | Dashboard is primary — Teams is additive (Phase 9); no impact on core approval loop |
| Teams app approval delays | Deferred to Phase 9; dashboard approval has no such delays |
| Azure Bot registration complexity | Deferred to Phase 9; detailed runbook (`docs/runbook-teams-setup.md`) prepared when needed |
| MongoDB failure | In-memory incident buffer with bounded queue; flush on recovery |
| Provider abstraction over-engineered | Keep it simple — only abstract what Docker + K8s need; add methods when a real provider needs them |
| Security vulnerabilities | RBAC enforced on all endpoints; audit logging; HMAC webhook verification; input validation via Pydantic; no secrets in logs |
| Celery task failures | Idempotent tasks; automatic retries with exponential backoff; dead-letter queue for manual review |
