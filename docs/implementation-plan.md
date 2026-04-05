# AutoOps AI - Implementation Plan

## Guiding Principle

**Provider abstraction is not a "later" feature.** The `InfrastructureProvider` interface is built in Phase 1, and the Docker Compose provider is the first implementation. This means when we add Kubernetes (or anything else), the agent engine, approval flow, dashboard, and knowledge base require zero changes.

---

## Phase 0: Planning & Business Approval (current)

> **Status: In progress.** All documentation is complete. Implementation has not started. This phase ends when business stakeholders and SMEs sign off on the approach.

**Deliverables for approval:**
- [x] Strategy and competitive landscape (see [AutoOps_AI_Roadmap.md](../AutoOps_AI_Roadmap.md))
- [x] System architecture and design decisions (see [architecture.md](architecture.md))
- [x] Phased implementation plan with scope boundaries (this document)
- [x] API design (see [api-design.md](api-design.md))
- [x] Knowledge base schema and starter playbooks (see [playbook-schema.md](playbook-schema.md))
- [x] Provider abstraction interface (see [provider-interface.md](provider-interface.md))
- [ ] Business stakeholder sign-off
- [ ] SME review of technical approach
- [ ] Resource and timeline confirmation

**What is intentionally deferred to post-approval:**
- Environment setup (Ollama installation, Docker stack)
- Python project scaffolding
- Any code

---

## Phase 1: Foundation

> Goal: Runnable project skeleton with Docker Compose target stack, provider interface, and basic metrics collection.

### 1.1 Project Setup
- [ ] Initialize Python project with `pyproject.toml` (dependencies: fastapi, uvicorn, docker, ollama, pydantic, streamlit, httpx, pyyaml, pytest, prometheus-client)
- [ ] Create directory structure per [architecture.md](architecture.md)
- [ ] Set up `.env` for config:
  ```
  OLLAMA_HOST=http://localhost:11434
  OLLAMA_MODEL=llama3:8b
  PROVIDER_TYPE=docker_compose
  POLLING_INTERVAL_SECONDS=15
  ```
- [ ] Create `agent/config.py` with Pydantic Settings (provider type, polling interval, thresholds, approval channel)

### 1.2 Target Infrastructure (Demo Stack)
- [ ] Create `infra/docker-compose/docker-compose.target.yml`:
  - **Nginx** — Reverse proxy, routes to FastAPI demo app
  - **FastAPI demo app** — REST API with `/health`, `/data` (reads from MongoDB), `/cache` (reads from Redis)
  - **MongoDB** — Primary data store
  - **Redis** — Cache layer
- [ ] Write the FastAPI demo app (`infra/demo-app/app.py`) with health endpoint and deliberate dependency on Mongo/Redis
- [ ] Verify: `docker compose up` brings up all 4 services and they communicate

### 1.3 Provider Interface & Docker Compose Provider
- [ ] Implement `agent/providers/base.py` — the `InfrastructureProvider` ABC (see [provider-interface.md](provider-interface.md))
- [ ] Implement `agent/models.py` — Pydantic models: `ServiceInfo`, `ServiceStatus`, `MetricSnapshot`, `HealthCheckResult`, `CommandResult`, `LogEntry`
- [ ] Implement `agent/providers/docker_compose.py` — Docker Compose provider:
  - `list_services()` — list containers by compose project label
  - `get_service_status()` — container state
  - `get_metrics()` — parse `container.stats()`
  - `health_check()` — hit the service's health endpoint
  - `restart_service()` — `container.restart()`
  - `exec_command()` — `container.exec_run()`
  - `get_logs()` — `container.logs()`
  - `scale_service()` — `docker compose up --scale`
  - `stop_service()` / `start_service()`
- [ ] Implement `agent/providers/registry.py` — provider factory
- [ ] Write tests: `tests/test_providers/test_docker_compose.py` (against real Docker)

### 1.4 Metrics Collector
- [ ] Implement `agent/collector/collector.py`:
  - Async polling loop (configurable interval, default 15s)
  - Calls `provider.list_services()` then `provider.get_metrics()` per service
  - Calls `provider.health_check()` per service
  - Emits `MetricSnapshot` list to a callback (the engine)
- [ ] Implement `agent/collector/health_probes.py` — configurable HTTP/TCP/command health checks per service
- [ ] Verify: collector prints metrics to console every 15s

### 1.5 Observability Stack (PLG)

- [ ] Create `infra/observability/docker-compose.observability.yml`:
  - **Prometheus** — scrapes cAdvisor, node-exporter, and the AutoOps agent's `/metrics` endpoint
  - **cAdvisor** — exposes per-container CPU, memory, network metrics in Prometheus format
  - **Loki** — receives log streams from Promtail; used for log-pattern anomaly detection
  - **Promtail** — tails Docker container logs and ships them to Loki with container labels
  - **Grafana** — connects to Prometheus + Loki; auto-provisions datasources and dashboards
- [ ] Create `infra/observability/prometheus/prometheus.yml` with scrape config for:
  - `cAdvisor` at `cadvisor:8080/metrics`
  - AutoOps agent at `autoops-agent:8000/metrics`
- [ ] Create `infra/observability/loki/loki-config.yaml` (filesystem storage, 30-day retention)
- [ ] Create `infra/observability/promtail/promtail-config.yaml` (tail `/var/lib/docker/containers/**/*.log`)
- [ ] Create `infra/observability/grafana/provisioning/` with auto-provisioned datasources (Prometheus + Loki)
- [ ] Create two starter Grafana dashboards:
  - `infra-health.json` — container CPU, memory, network I/O (sourced from Prometheus/cAdvisor)
  - `autoops-agent.json` — MTTR, incident count, LLM inference latency, pending approvals
- [ ] Expose `GET /metrics` endpoint on the AutoOps agent (Prometheus text format) using `prometheus-client`
- [ ] Verify: `docker compose -f docker-compose.observability.yml up` → Grafana at `localhost:3000` shows live container metrics

### 1.6 Chaos Scripts
- [ ] `chaos/docker/kill_mongodb.sh` — `docker stop <mongodb_container>`
- [ ] `chaos/docker/spike_cpu.sh` — `docker exec <container> stress --cpu 2 --timeout 60`
- [ ] `chaos/docker/fill_redis.sh` — fill Redis to 95% memory
- [ ] `chaos/docker/break_nginx.sh` — corrupt Nginx config and reload

**Phase 1 deliverable:** Running Docker stack, collector printing metrics, PLG observability stack with live Grafana dashboards, chaos scripts that break things reliably.

---

## Phase 2: Agent Brain

> Goal: The agent detects anomalies, matches playbooks, calls the local Ollama model for diagnosis, and classifies risk.

### 2.1 Knowledge Base
- [ ] Implement `agent/knowledge/schemas.py` — Pydantic models for playbook entries (detection, remediation, rollback)
- [ ] Implement `agent/knowledge/knowledge_base.py`:
  - Load YAML files from `playbooks/general/` + `playbooks/{provider}/`
  - `match(metrics: list[MetricSnapshot], statuses: list[ServiceStatus]) -> list[PlaybookMatch]`
  - Evaluate detection conditions against current state
  - Return ranked matches with confidence scores
- [ ] Create starter playbooks (4 entries per [playbook-schema.md](playbook-schema.md)):
  - `playbooks/docker_compose/mongodb.yaml`
  - `playbooks/docker_compose/redis.yaml`
  - `playbooks/docker_compose/nginx.yaml`
  - `playbooks/general/high_cpu.yaml`

### 2.2 Ollama Setup & LLM Client
- [ ] Install Ollama and pull the chosen model(s):
  - Primary: `ollama pull llama3:8b` (good balance of quality and speed)
  - Optional larger: `ollama pull llama3:70b` or `ollama pull qwen2.5:32b` (better reasoning, needs more GPU)
  - Optional faster fallback: `ollama pull mistral:7b` (faster inference, lighter weight)
- [ ] Verify Ollama is running locally: `curl http://localhost:11434/api/tags`
- [ ] Implement `agent/llm/client.py`:
  - Ollama Python SDK client wrapper (`ollama.chat()` with `format="json"` for structured output)
  - Configurable model name + Ollama host URL (default `http://localhost:11434`)
  - `diagnose(anomaly, metrics, playbook_match) -> Diagnosis` — structured JSON output
  - `explain_for_human(diagnosis) -> str` — natural-language summary for dashboard
  - `reason_novel_issue(metrics, logs) -> Diagnosis` — when no playbook matches
  - Retry logic, timeout handling (local models can be slow on first call before GPU warm-up)
  - Model warm-up on startup (`ollama.generate(model, "warmup", keep_alive="10m")`)
- [ ] Implement `agent/llm/prompts.py`:
  - System prompt template (from roadmap section 7) — tuned for open-source model capabilities
  - User prompt template (metrics snapshot + anomaly + playbook context)
  - Output schema (diagnosis JSON) — use explicit JSON schema in prompt since some open-source models need stricter formatting guidance than commercial APIs
  - Keep prompts concise — smaller models perform better with focused, shorter context

### 2.3 Anomaly Detection & Risk Classification
- [ ] Implement `agent/engine/anomaly.py`:
  - Threshold-based detection from config (CPU > 90%, memory > 85%, error rate > 50%, service down)
  - Duration-based detection (sustained high CPU for 2+ minutes)
  - Rate-based detection (error rate increasing over time)
  - Returns `list[Anomaly]` with affected service, metric, severity hint
- [ ] Implement `agent/engine/risk.py`:
  - Classify action risk: LOW (cache clear, log rotation) / MEDIUM (restart service, scale up) / HIGH (restart DB, failover, scale down)
  - Risk factors: service criticality (DB > app > cache), action type, blast radius
  - Override from playbook `severity` field

### 2.4 Agent Engine (Core Loop)
- [ ] Implement `agent/engine/engine.py`:
  - `async process_cycle(snapshots, statuses)` — single iteration of the reasoning loop
  - Pipeline: detect anomalies → match playbooks → LLM diagnosis → classify risk → emit actions
  - Cooldown tracking (don't re-alert for same issue within cooldown window)
  - Incident creation and state management
- [ ] Implement `agent/store/incidents.py`:
  - MongoDB-backed incident store
  - Create, update, resolve incidents
  - Store diagnosis, actions, timeline events
- [ ] Implement `agent/models.py` additions: `Incident`, `Anomaly`, `Diagnosis`, `Action`, `ActionResult`

**Phase 2 deliverable:** Kill MongoDB → agent detects it, matches playbook, calls local Ollama model, prints diagnosis with risk level to console. No approval yet, no execution yet.

---

## Phase 3: Approval Flow & Remediation

> Goal: Full loop — detect, diagnose, request approval via dashboard chat window, execute fix, verify.

### 3.1 Dashboard Chat Window Approval

The MVP approval mechanism is a chat window in the dashboard. When the agent raises a MEDIUM or HIGH risk incident, an approval card appears in the chat — similar to how an AI assistant surfaces a permission request before taking an action. The card shows the diagnosis, the proposed action, the risk level, and the rollback plan, with Approve / Deny / Investigate More buttons.

- [ ] Implement `agent/approval/chat_approval.py`:
  - `create_approval_card(incident) -> ApprovalCard` — builds the card payload
  - `ApprovalCard` model: `incident_id`, `title`, `diagnosis`, `severity`, `proposed_action`, `rollback_plan`, `timeout_at` (MEDIUM only), `timeout_default`
  - Card state machine: `pending → approved | denied | timed_out`
  - Timeout timer per incident: asyncio task that fires `deny` on expiry for MEDIUM risk
  - HIGH risk: no timeout task is created; card stays pending until explicit action
- [ ] Implement `agent/approval/router.py`:
  - Route based on risk: LOW → auto-execute + notify, MEDIUM → approval card with 5-min timeout (deny-by-default), HIGH → approval card (no timeout)
  - `await_approval(incident_id) -> ApprovalDecision` — suspends until dashboard calls the approval endpoint
  - Callback to Remediation Executor on approval
- [ ] Implement approval API endpoints in `agent/main.py`:
  - `GET /approval/pending`
  - `POST /approval/{incident_id}/approve`
  - `POST /approval/{incident_id}/deny`
  - `POST /approval/{incident_id}/investigate`
  - See [api-design.md](api-design.md) for full spec

### 3.2 Remediation Executor
- [ ] Implement `agent/remediation/executor.py`:
  - Receive `Action` → call appropriate `provider` method
  - Action type mapping:
    - `restart_service` → `provider.restart_service()`
    - `exec_command` → `provider.exec_command()`
    - `scale_service` → `provider.scale_service()`
    - `collect_logs` → `provider.get_logs()`
    - `health_check` → `provider.health_check()` or `provider.exec_command()`
    - `metric_check` → `provider.get_metrics()` + compare
    - `wait` → `asyncio.sleep()`
    - `escalate` → notify dashboard, mark incident as escalated
  - Execute remediation steps sequentially
  - After each step, check success/failure
  - Run verification steps
  - Report outcome to Agent Engine
- [ ] Implement `agent/remediation/rollback.py`:
  - If verification fails, attempt rollback steps from playbook
  - If rollback also fails, escalate

### 3.3 Wire Up the Full Loop
- [ ] Implement `agent/main.py` — FastAPI app with lifecycle:
  - On startup: create provider, load playbooks, start collector, start engine loop
  - On shutdown: stop collector, cleanup
- [ ] Wire: Collector → Engine → Approval Router → Remediation Executor → Verification → WebSocket events
- [ ] End-to-end test: kill MongoDB → agent detects → approval card appears in dashboard chat → click Approve → MongoDB restarts → verification passes → card updates to "Resolved in 47s"

### 3.4 API Endpoints (Core)
- [ ] `GET /health` — agent health
- [ ] `GET /status` — all service statuses
- [ ] `GET /incidents` — list incidents
- [ ] `GET /incidents/{id}` — incident detail
- [ ] `GET /approval/pending` — pending approvals
- [ ] `POST /approval/{id}/approve` — approve from dashboard
- [ ] `POST /approval/{id}/deny` — deny from dashboard
- [ ] `POST /approval/{id}/investigate` — request more detail
- [ ] `WS /ws/events` — live event stream

**Phase 3 deliverable:** Full working demo loop — break something, approval card appears in dashboard chat, click Approve, it's fixed, card shows "Resolved." This is the core demo moment.

---

## Phase 4: Dashboard & Polish

> Goal: Web dashboard showing the agent in action, polished approval cards, and a second demo scenario.

### 4.1 Streamlit Dashboard
- [ ] `dashboard/app.py` — main layout with sidebar nav
- [ ] `dashboard/components/health.py` — live system health (service cards with status, CPU, memory)
- [ ] `dashboard/components/timeline.py` — incident timeline (chronological, color-coded by severity)
- [ ] `dashboard/components/chat.py` — agent conversation view per incident, with inline approval card rendering:
  - Approval cards render as distinct UI blocks (not plain text) with action buttons
  - Resolved cards show the outcome in-place (Approved by operator at 09:45:28, Resolved in 47s)
  - Pending cards show a countdown timer for MEDIUM risk
- [ ] `dashboard/components/playbooks.py` — playbook browser (read-only for MVP)
- [ ] Connect to FastAPI backend via HTTP + WebSocket for live updates

### 4.2 Polish Approval Cards
- [ ] Severity badge: color-coded (MEDIUM = amber, HIGH = red)
- [ ] Code block for technical detail (exact command or API call that will be executed)
- [ ] Rollback plan visible but collapsible by default
- [ ] "Investigate More" button: agent posts detailed reasoning (log excerpts, metric trends) as a follow-up in the chat, without approving or denying
- [ ] Include timing in resolved cards: "Detected 3 seconds ago", "Resolved in 47 seconds"
- [ ] LOW risk auto-execute produces a notification bubble (not a card) in the chat: "Auto-resolved: Redis memory at 95% → purged → now at 42%"

### 4.3 Second Demo Scenario (LOW risk, auto-resolved)
- [ ] Verify Redis memory full scenario works end-to-end
- [ ] Agent auto-executes cache purge (no approval needed — LOW risk)
- [ ] Dashboard chat shows notification: "Auto-resolved: Redis memory at 95% → purged → now at 42%"

### 4.4 Third Demo Scenario (HIGH risk)
- [ ] Nginx 502 Bad Gateway scenario
- [ ] Agent raises HIGH risk approval card (no timeout, explicit approval required)
- [ ] Shows rollback plan prominently in the card
- [ ] Demo: deny first, then re-approve to show both paths
- [ ] Verify the "Investigate More" flow shows LLM reasoning in the chat

**Phase 4 deliverable:** Polished dashboard with chat-window approval cards, three working demo scenarios.

---

## Phase 5: Demo Prep & Hardening

> Goal: Bulletproof demo, backup recordings, pitch deck.

### 5.1 Demo Script
- [ ] Write step-by-step demo script (see roadmap for the 5-minute flow)
- [ ] Practice full demo 5+ times
- [ ] Time each section — aim for 4:30 to leave buffer

### 5.2 Resilience
- [ ] Add fallback behavior if Ollama inference is slow (use playbook diagnosis directly; consider a smaller/faster model like Mistral 7B as fallback)
- [ ] Add fallback if dashboard WebSocket disconnects (HTTP polling fallback for approval card state)
- [ ] Pre-warm all containers before demo (no cold-start delays)

### 5.3 Backup Recordings
- [ ] Record full demo flow as video backup
- [ ] Screenshot key moments for pitch deck

### 5.4 Pitch Deck (5 slides)
- [ ] **Problem** — Incident response is manual, slow, and error-prone
- [ ] **Solution** — AutoOps AI: your virtual DevOps engineer
- [ ] **Demo** — Live demo or video
- [ ] **Architecture** — Provider-agnostic, playbook-driven, human-in-the-loop
- [ ] **Vision** — K8s support, learning loop, MS Teams, multi-cloud

---

## Post-Approval Roadmap (Future Phases)

> **Strategic Decision (2026-04-05):** The dashboard/UI is the primary interface for the virtual DevOps engineer experience. MS Teams integration is deferred — it requires Azure AD app registration, Bot Service, HTTPS tunneling, and Teams admin approval, which is significant overhead before the core agent loop is proven. The dashboard provides the same approval workflow with faster iteration. Teams will be added as an additional channel once the core experience is solid.

### Phase 6: Kubernetes Provider
- [ ] Implement `agent/providers/kubernetes.py` (see [provider-interface.md](provider-interface.md))
- [ ] K8s-specific playbooks: CrashLoopBackOff, node pressure, PVC pending, ImagePullBackOff
- [ ] K8s-specific chaos scripts: kill pod, drain node, network partition
- [ ] K8s-specific metrics: pod restarts, node allocatable, PVC usage
- [ ] Test with Minikube / kind cluster

### Phase 7: Learning Loop
- [ ] When a novel issue is resolved, prompt user in dashboard chat: "Add this to the playbook?"
- [ ] Agent generates playbook YAML from the incident (LLM-assisted, Ollama)
- [ ] Human reviews and approves the new playbook entry via dashboard
- [ ] Playbook grows over time — the agent gets smarter with each resolved incident

### Phase 8: Predictive Analysis
- [ ] Time-series analysis on collected metrics (trend detection)
- [ ] LLM-powered "this metric pattern usually leads to X" predictions using Ollama
- [ ] Proactive alerts in dashboard chat: "Memory is trending toward 90% on demo-app, ETA 20 minutes. Want me to scale up?"

### Phase 9: MS Teams Integration (Deferred)

> **Deferred — focus on dashboard UI first.** Teams integration adds enterprise notification capabilities but requires significant external setup (Azure AD, Bot Service, HTTPS tunnels, Teams admin). The dashboard approval flow covers 100% of the functionality. Teams will be added once the complete virtual DevOps engineer loop is working end-to-end in the dashboard.

- [ ] MS Teams Adaptive Cards for approval flow — cards sent to a configured Teams channel
- [ ] Handle Teams interactive callback (`POST /webhooks/teams/events`)
- [ ] Verify Teams webhook signature (HMAC)
- [ ] Teams-specific card formatting (Adaptive Card schema)
- [ ] Agent config: `approval.channel: "teams"` routes MEDIUM/HIGH approvals to Teams instead of dashboard
- [ ] Dashboard still shows the approval state (real-time sync via WebSocket)

  > **Why Teams and not Slack:** Enterprise teams overwhelmingly use MS Teams. Teams Adaptive Cards have first-class support for interactive buttons and are already trusted by enterprise IT security departments. This is the correct target for an enterprise-facing product.

  Post-Teams, additional notification channels can be added via the webhook abstraction:
  - Email (fallback for organisations without Teams)
  - PagerDuty (create/resolve incidents)
  - Generic webhook for custom integrations

### Phase 10: Production Hardening
- [ ] Authentication and RBAC (API keys, JWT, role-based approval permissions)
- [ ] MongoDB incident store (using existing MongoDB instance)
- [ ] Celery + Redis for async task execution (replace asyncio for production scale)
- [ ] Additional Grafana dashboards: playbook hit-rate, per-service incident frequency, Ollama model comparison
- [ ] Prometheus alerting rules (`prometheus/alerts.yml`) — alert on agent itself going down, LLM latency spikes, stuck pending approvals
- [ ] Helm chart for deploying AutoOps AI on Kubernetes (includes PLG stack as optional subchart)
- [ ] Docker Compose file for deploying AutoOps AI + PLG alongside target stack (production single-file deploy)

### Phase 11: Additional Providers
- [ ] AWS ECS provider
- [ ] HashiCorp Nomad provider
- [ ] Podman / bare-metal provider
- [ ] Custom provider SDK (documentation + template for community providers)

---

## Dependency Map

```
Phase 0 (Planning — current)
  └── Business approval → unlocks Phase 1

Phase 1 (Foundation)
  ├── 1.1 Project Setup
  ├── 1.2 Target Stack ──────────────────────────────────┐
  ├── 1.3 Provider Interface + Docker Provider           │
  ├── 1.4 Metrics Collector (depends on 1.3)             │
  ├── 1.5 Observability Stack (PLG) (depends on 1.2)     │
  └── 1.6 Chaos Scripts (depends on 1.2) ───────────────┐│
                                                         ││
Phase 2 (Agent Brain)                                    ││
  ├── 2.1 Knowledge Base                                 ││
  ├── 2.2 Ollama Setup + LLM Client                      ││
  ├── 2.3 Anomaly Detection + Risk                       ││
  └── 2.4 Engine (depends on 2.1, 2.2, 2.3, 1.4)       ││
                                                         ││
Phase 3 (Approval + Remediation)                         ││
  ├── 3.1 Dashboard Chat Approval                        ││
  ├── 3.2 Remediation Executor (depends on 1.3)          ││
  ├── 3.3 Full Loop (depends on 2.4, 3.1, 3.2) ◄────────┘│
  └── 3.4 API Endpoints                                   │
                                                           │
Phase 4 (Dashboard + Polish)                               │
  ├── 4.1 Streamlit Dashboard (depends on 3.4)             │
  ├── 4.2 Polish Approval Cards                            │
  ├── 4.3 Demo Scenario 2 (depends on 3.3) ◄──────────────┘
  └── 4.4 Demo Scenario 3 (depends on 3.3)

Phase 5 (Demo Prep)
  └── Depends on all above
```

---

## Parallelization Opportunities

Within a team, these workstreams can run in parallel:

| Person | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|---|---|---|---|---|
| **Dev A** (Backend/AI) | Provider interface + Docker provider | Ollama LLM client + Engine | Wire full loop | Polish + edge cases |
| **Dev B** (Backend) | Target stack + demo app | Knowledge base + anomaly detection | Remediation executor | Dashboard backend |
| **Dev C** (DevOps/Infra) | Chaos scripts + Docker setup | Playbook YAML files | Approval router + API | Demo prep + pitch |
| **Dev D** (Frontend) | — | — | API endpoints | Streamlit dashboard + approval cards |

---

## Key Risk Mitigations

| Risk | Mitigation |
|---|---|
| Ollama inference latency in live demo | Pre-load model into GPU memory before demo; cache recent diagnoses; use Mistral 7B (faster) if hardware is limited; fall back to playbook-only diagnosis |
| Ollama unavailable | Graceful degradation: use playbook diagnosis directly without LLM, flag that LLM is offline in the dashboard |
| Docker restart takes too long | Pre-pull all images; set container restart timeouts |
| Demo stack not starting | Pre-built images pushed to registry; `docker compose pull` before demo |
| Playbook doesn't match | LLM fallback for novel issues; have all demo scenarios pre-tested |
| Provider abstraction over-engineered | Keep it simple — only abstract what both Docker + K8s need. Add methods when a real provider needs them, not speculatively |
| MS Teams webhook setup complexity (Phase 9) | Deferred — dashboard is the primary UI; Teams is additive, not a dependency. Added when core loop is proven |
