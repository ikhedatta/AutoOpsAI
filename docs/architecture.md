# AutoOps AI - System Architecture

## Overview

AutoOps AI is a **virtual DevOps engineer** — an AI-powered agent that monitors infrastructure, diagnoses issues, proposes remediations in plain language, obtains human approval when needed, executes fixes, and verifies outcomes. It works across **any deployment environment** (Docker Compose, Kubernetes, ECS, Nomad, bare-metal) through a pluggable provider abstraction.

> **Note on `image.png`:** The architecture diagram in the repository root shows "Claude / GPT" as the LLM engine. **The actual implementation uses Ollama exclusively** with local open-source models (Llama 3, Mistral, Codellama). All inference runs on-prem — no data leaves the network. The diagram will be updated in a future revision.

---

## Design Principles

1. **Provider-agnostic core** — The agent engine, knowledge base, approval flow, and dashboard never import Docker/K8s/cloud-specific code directly. All infrastructure interaction goes through the `InfrastructureProvider` interface.
2. **Conversational-first** — The agent's reasoning and actions are surfaced as a conversation in the dashboard chat window, not buried in dashboards. The conversation IS the incident response.
3. **Tiered autonomy** — Risk level determines whether the agent auto-executes, requests approval, or escalates. Humans stay in control.
4. **Playbook + LLM hybrid** — Structured playbooks handle known issues fast; the LLM reasons about novel problems. All LLM inference is local via Ollama — no data leaves the network.
5. **Stateless agent, persistent knowledge** — The agent loop is stateless per cycle. State lives in the incident store and knowledge base.

---

## High-Level Architecture

```
+---------------------------------------------------------------------+
|                         AutoOps AI Agent                            |
|                                                                     |
|  +------------------+    +------------------+   +-----------------+ |
|  | Metrics Collector|    |   Agent Engine   |   | Approval Router | |
|  |   (polling loop) |--->| (detect/diagnose |--->| (dashboard chat | |
|  |   + /metrics     |    |  /classify/act)  |   |  window / Teams)|  |
|  +--------+---------+    +--------+---------+   +--------+--------+ |
|           |                       |                      |          |
|           v                       v                      v          |
|  +------------------+    +------------------+   +-----------------+ |
|  | Health Probes    |    |  LLM Client      |   | Remediation     | |
|  | (per-provider)   |    |  (Ollama local)  |   | Executor        | |
|  +------------------+    +------------------+   +-----------------+ |
|                                                          |          |
+----------------------------------------------------------+----------+
          |  /metrics                                      |
          |                                                |
+---------+--------------------------------------------+  |
|              Observability Stack (PLG)               |  |
|                                                      |  |
|  +------------+  +-------+  +---------+  +-------+  |  |
|  | Prometheus |  | Loki  |  | Promtail|  |cAdvisor|  |  |
|  | (metrics)  |  | (logs)|  |(log fwd)|  |(ctr   |  |  |
|  +-----+------+  +---+---+  +----+----+  | stats)|  |  |
|        |              |          |        +---+---+  |  |
|        +------+--------+---------+------------+      |  |
|               v                                      |  |
|          +--------+                                  |  |
|          | Grafana|  (unified metrics + log UI)      |  |
|          +--------+                                  |  |
+------------------------------------------------------+  |
                                                           |
                    +--------------------------------------+----------+
                    |       Infrastructure Provider Interface         |
                    |  (list_services, get_metrics, restart_service,  |
                    |   exec_command, get_logs, scale_service, ...)   |
                    +---+------------------+------------------+------+
                        |                  |                  |
               +--------+------+  +--------+------+  +-------+-------+
               | DockerCompose |  |  Kubernetes   |  |  Future       |
               | Provider      |  |  Provider     |  |  (ECS/Nomad/  |
               |               |  |               |  |   bare-metal) |
               +---------------+  +---------------+  +---------------+
                    |                    |
              Docker API           kubectl / K8s API
```

---

## Component Details

### 1. Metrics Collector

**Responsibility:** Poll infrastructure for health and performance data at a configurable interval (default: 15s) and forward data to the Prometheus/Loki observability stack.

**How it works:**
- Calls `provider.list_services()` to discover what's running
- Calls `provider.get_metrics(service)` for CPU, memory, network, disk per service
- Calls `provider.health_check(service)` for application-level health
- Scrapes the Prometheus endpoint exposed by cAdvisor and other exporters
- Emits `MetricSnapshot` events to the Agent Engine
- Exposes its own `/metrics` endpoint (Prometheus format) for meta-monitoring

**Provider-agnostic:** The collector doesn't know if it's talking to Docker, K8s, or anything else. It calls the provider interface.

### 2. Agent Engine (Core Reasoning Loop)

**Responsibility:** The brain. Receives metric snapshots, detects anomalies, diagnoses issues, classifies risk, and decides on actions.

**Pipeline per cycle:**
```
MetricSnapshot
    |
    v
[1. Anomaly Detection] -- threshold rules from config
    |
    v (if anomaly)
[2. Playbook Lookup] -- match symptoms against knowledge base
    |
    v
[3. LLM Diagnosis] -- Ollama (local) for explanation + novel reasoning
    |
    v
[4. Risk Classification] -- LOW / MEDIUM / HIGH
    |
    v
[5. Action Routing]
    |-- LOW  --> auto-execute via Remediation Executor, notify after
    |-- MEDIUM --> send to Approval Router (dashboard chat card, 5-min timeout, deny-by-default)
    |-- HIGH --> send to Approval Router (dashboard chat card, no auto-timeout, explicit approval required)
```

**Key design:** The engine is a pure function of `(metrics, playbooks, config) -> actions`. It holds no mutable state between cycles. Incident state is written to the incident store (MongoDB).

### 3. Knowledge Base

**Responsibility:** Store and retrieve structured playbooks that map symptoms to diagnoses and remediation steps.

**Format:** YAML files in `playbooks/` directory (see [playbook-schema.md](playbook-schema.md)).

**Matching logic:**
- Each playbook entry has `detection.conditions` — a list of predicates
- The matcher evaluates conditions against the current metric snapshot
- Returns ranked matches (best-fit first) to the Agent Engine
- If no match, the LLM reasons from raw metrics (zero-shot diagnosis)

### 4. LLM Client

**Responsibility:** Interface with a locally-hosted LLM via Ollama for natural-language diagnosis, novel issue reasoning, and action plan generation. **No data leaves the network** — all inference runs on-prem.

**Usage points:**
- Diagnosis generation (explain the problem in plain English)
- Novel issue reasoning (no playbook match — figure it out from raw metrics and logs)
- Incident summary generation (for dashboard approval cards and chat log)
- Confidence scoring (how sure is the agent about its diagnosis)

**Model:** Open-source model served by Ollama (e.g., Llama 3 8B/70B, Mistral 7B, Codellama). Uses JSON mode / structured output for reliable parsing. Model is configurable — swap any Ollama-compatible model without code changes.

**No cloud LLM calls.** Infrastructure telemetry, logs, and service names are sensitive operational data. The system never calls the OpenAI API, Anthropic API, or any external LLM service.

### 5. Approval Router

**Responsibility:** Route remediation proposals to humans for approval based on risk level.

**Timeout behavior:**
- **LOW:** No approval needed — auto-execute and notify via dashboard chat
- **MEDIUM:** Approval card appears in dashboard chat, 5-minute timeout, deny-by-default if no response
- **HIGH:** Approval card appears in dashboard chat, no timeout — explicit human approval required before any action is taken

**Approval channels:**

| Phase | Channel | Mechanism |
|---|---|---|
| **MVP (Phases 1-5)** | Dashboard chat window | Inline approval card with Approve / Deny / Investigate buttons |
| **Production (Phase 9+)** | Microsoft Teams | Adaptive Cards sent to a configured Teams channel |
| **Any phase** | Generic webhook | HTTP callback for custom integrations |

**Dashboard approval card design:** When the agent proposes an action, a card appears in the dashboard chat window — similar to how an AI model surfaces a permission request. The card shows: incident title, plain-English diagnosis, proposed action, risk badge (MEDIUM / HIGH), rollback plan, and Approve / Deny / Investigate More buttons. On approval, the card updates in-place to show the execution outcome.

**Why dashboard-first for MVP:** No external service dependencies (no Slack app setup, no bot tokens, no webhook endpoints). The approval card is a first-class UI element, not an afterthought bolted onto a chat platform.

**Why MS Teams for production:** Enterprise customers live in Teams. Teams Adaptive Cards support interactive buttons and are already trusted by IT security. MS Teams is a more impactful enterprise channel than Slack for this use case.

### 6. Remediation Executor

**Responsibility:** Execute approved actions against the infrastructure.

**How it works:**
- Receives an `Action` (type, target, parameters)
- Calls the appropriate provider method (`provider.restart_service()`, `provider.exec_command()`, `provider.scale_service()`, etc.)
- Waits for completion
- Runs verification checks (via provider) to confirm the fix worked
- Reports outcome back to the Agent Engine

**Rollback:** If verification fails, the executor can attempt rollback steps defined in the playbook, or escalate to a human.

### 7. Observability Stack (Prometheus + Loki + Grafana)

**Responsibility:** Collect, store, and visualise all metrics and logs from both the monitored infrastructure and the AutoOps AI agent itself.

**Components:**

| Tool | Role |
|---|---|
| **Prometheus** | Scrapes and stores time-series metrics from cAdvisor (container CPU/memory/network), node-exporter (host metrics), and the AutoOps AI agent's own `/metrics` endpoint |
| **cAdvisor** | Sidecar container that exposes per-container metrics in Prometheus format — the primary source for infrastructure telemetry |
| **Loki** | Log aggregation backend; receives structured log streams from Promtail. Used for log-based anomaly detection and incident enrichment |
| **Promtail** | Log shipping agent; tails Docker container logs and forwards them to Loki with container labels |
| **Grafana** | Unified observability UI — connects to both Prometheus (metrics) and Loki (logs); hosts dashboards for infra health and AutoOps AI performance |

**Agent metrics exposed on `/metrics`:**
- `autoops_incidents_total` — counter by severity and status
- `autoops_resolution_time_seconds` — histogram of MTTR
- `autoops_llm_inference_duration_seconds` — Ollama inference latency
- `autoops_approval_pending_total` — current pending approvals
- `autoops_anomalies_detected_total` — anomaly detection rate

**Log-based anomaly detection:** The Metrics Collector can query Loki for log patterns (e.g., `502 Bad Gateway` rate from Nginx logs) in addition to metric thresholds. This enables the `log_pattern` detection type in playbooks.

**Data flow:**
```
[cAdvisor] ──scrape──> [Prometheus] <──query── [AutoOps Agent Engine]
[Promtail] ──push───> [Loki]       <──query── [AutoOps Agent Engine]
[AutoOps /metrics] ──scrape──> [Prometheus]
[Prometheus + Loki] ──datasource──> [Grafana dashboards]
```

**Why PLG over ELK:** Prometheus + Loki + Grafana is significantly lighter than Elasticsearch + Logstash + Kibana. Loki indexes only log metadata (labels), not full-text, which means it runs comfortably alongside the rest of the stack on modest hardware — important for a self-hosted, air-gapped deployment.

### 8. Dashboard

**Responsibility:** Web UI showing the incident timeline, agent reasoning, approval cards, system health, and playbook management.

**Tech:** Streamlit for MVP, React + Tailwind for production.

**Views:**
- **Incident Timeline** — Chronological list of detected issues, actions taken, outcomes
- **Agent Chat** — Conversational view of the agent's reasoning per incident; inline approval cards for MEDIUM/HIGH risk actions
- **System Health** — Current status of all monitored services
- **Playbook Manager** — View, add, edit playbook entries
- **Metrics** — MTTR, auto-resolved count, approval response times

---

## Data Flow

```
[Infrastructure] --metrics/health--> [Collector] --snapshot--> [Agent Engine]
                                                                     |
                                                        [Knowledge Base] + [LLM (Ollama)]
                                                                     |
                                                              [Risk Classification]
                                                                     |
                                              +----------------------+----------------------+
                                              |                      |                      |
                                           [LOW]                 [MEDIUM]                [HIGH]
                                              |                      |                      |
                                        auto-execute      [Dashboard approval card]  [Dashboard approval card]
                                              |                      |                      |
                                              |               approve/deny           approve/deny
                                              |                      |                      |
                                              +----------+-----------+----------------------+
                                                         |
                                                  [Remediation Executor]
                                                         |
                                                  [Verification Check]
                                                         |
                                                  [Incident Store + Notify]
```

---

## Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| **Language** | Python 3.11+ | Team expertise, rich ecosystem for DevOps tooling |
| **Backend framework** | FastAPI | Async, fast, auto-generated OpenAPI docs |
| **LLM** | Ollama (local) — Llama 3 8B/70B, Mistral 7B, Codellama | Air-gapped — no data leaves the network; structured JSON output |
| **Task execution** | asyncio (MVP), Celery + Redis (production) | Keep it simple first, scale later |
| **Metrics** | Prometheus + cAdvisor | Lightweight, runs in Docker, K8s-native; cAdvisor provides per-container telemetry |
| **Logs** | Loki + Promtail | Lightweight log aggregation (indexes labels only); pairs natively with Grafana |
| **Observability UI** | Grafana | Single pane for metrics (Prometheus) and logs (Loki); prebuilt dashboards |
| **Approval (MVP)** | Dashboard chat window (built-in) | No external dependencies; approval card is first-class UI |
| **Approval (production)** | MS Teams Adaptive Cards | Enterprise teams live in Teams; richer than email |
| **Dashboard** | Streamlit (MVP), React + Tailwind (production) | Speed for MVP, polish for production |
| **Incident store** | MongoDB (existing instance) + Motor + Beanie ODM | Already deployed; document model fits incident/timeline data naturally |
| **Knowledge base** | YAML files in `playbooks/` | Human-readable, version-controllable |
| **Infrastructure providers** | Docker SDK for Python, kubernetes Python client | One provider per environment |

---

## Project Structure

```
autoops-ai/
├── docker-compose.yml              # Target infrastructure (demo stack)
├── docker-compose.agent.yml        # AutoOps AI services
├── pyproject.toml                  # Python project config
│
├── agent/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app, startup, lifecycle
│   ├── config.py                   # Settings (thresholds, intervals, provider selection)
│   ├── models.py                   # Pydantic models (Incident, Action, MetricSnapshot, etc.)
│   │
│   ├── collector/
│   │   ├── __init__.py
│   │   ├── collector.py            # Polling loop, emits MetricSnapshots
│   │   └── health_probes.py        # Application-level health checks
│   │
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── engine.py               # Core reasoning loop
│   │   ├── anomaly.py              # Threshold-based anomaly detection
│   │   └── risk.py                 # Risk classification logic
│   │
│   ├── knowledge/
│   │   ├── __init__.py
│   │   ├── knowledge_base.py       # Playbook loader and symptom matcher
│   │   └── schemas.py              # Playbook Pydantic models
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py               # Ollama local LLM client
│   │   └── prompts.py              # System/user prompt templates
│   │
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py                 # InfrastructureProvider ABC
│   │   ├── docker_compose.py       # Docker Compose provider
│   │   ├── kubernetes.py           # Kubernetes provider
│   │   └── registry.py             # Provider registry and factory
│   │
│   ├── approval/
│   │   ├── __init__.py
│   │   ├── router.py               # Approval routing logic (risk → channel)
│   │   ├── chat_approval.py        # Dashboard chat window approval cards (MVP)
│   │   ├── teams_bot.py            # MS Teams Adaptive Cards (production, Phase 9+)
│   │   └── webhook.py              # Generic webhook approval
│   │
│   ├── remediation/
│   │   ├── __init__.py
│   │   ├── executor.py             # Action execution + verification
│   │   └── rollback.py             # Rollback logic
│   │
│   ├── store/
│   │   ├── __init__.py
│   │   ├── incidents.py            # Incident persistence (MongoDB)
│   │   └── database.py             # Motor client + Beanie init
│   │
│   └── ws/
│       ├── __init__.py
│       └── manager.py              # WebSocket manager + Redis pub/sub subscriber
│
├── playbooks/
│   ├── docker_compose/
│   │   ├── mongodb.yaml
│   │   ├── redis.yaml
│   │   ├── nginx.yaml
│   │   └── general.yaml
│   └── kubernetes/
│       ├── pod_crash_loop.yaml
│       ├── node_pressure.yaml
│       └── service_unreachable.yaml
│
├── dashboard/
│   ├── app.py                      # Streamlit dashboard
│   └── components/
│       ├── timeline.py
│       ├── chat.py                 # Agent chat + inline approval cards
│       ├── health.py
│       └── playbooks.py
│
├── chaos/                          # Failure injection scripts
│   ├── docker/
│   │   ├── kill_mongodb.sh
│   │   ├── spike_cpu.sh
│   │   ├── fill_redis.sh
│   │   └── break_nginx.sh
│   └── kubernetes/
│       ├── kill_pod.sh
│       ├── drain_node.sh
│       └── network_partition.sh
│
├── infra/                          # Demo infrastructure definitions
│   ├── docker-compose/
│   │   └── docker-compose.target.yml
│   ├── kubernetes/
│   │   ├── namespace.yaml
│   │   ├── deployments/
│   │   └── services/
│   └── observability/              # PLG stack configuration
│       ├── docker-compose.observability.yml   # Prometheus, Loki, Grafana, cAdvisor, Promtail
│       ├── prometheus/
│       │   └── prometheus.yml      # Scrape config (cAdvisor, node-exporter, autoops-agent)
│       ├── loki/
│       │   └── loki-config.yaml    # Loki storage + retention config
│       ├── promtail/
│       │   └── promtail-config.yaml # Docker log tailing config
│       └── grafana/
│           ├── provisioning/
│           │   ├── datasources/    # Auto-provision Prometheus + Loki datasources
│           │   └── dashboards/     # Auto-provision dashboard JSON files
│           └── dashboards/
│               ├── infra-health.json      # Container CPU, memory, network
│               └── autoops-agent.json     # MTTR, incidents, LLM latency
│
├── tests/
│   ├── test_engine.py
│   ├── test_collector.py
│   ├── test_knowledge_base.py
│   ├── test_providers/
│   │   ├── test_docker_compose.py
│   │   └── test_kubernetes.py
│   └── test_remediation.py
│
└── docs/
    ├── architecture.md             # This file
    ├── provider-interface.md       # Provider abstraction details
    ├── api-design.md               # API endpoints
    ├── playbook-schema.md          # Playbook format
    └── implementation-plan.md      # Phased build plan
```
