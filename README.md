# AutoOps AI

**A virtual DevOps engineer.** AutoOps AI monitors your infrastructure in real-time, diagnoses issues using a combination of structured playbooks and local LLM reasoning, explains what's wrong in plain English, requests human approval for risky actions through a dashboard chat interface, executes fixes, and verifies outcomes — all with full audit trails and without sending any data outside your network.

---

## The Problem

When something breaks in production, engineers are paged at 2am. They then:
1. Dig through dashboards and logs to figure out what broke
2. Cross-reference runbooks or past incidents to find the fix
3. Get approval from another engineer before touching production
4. Execute the fix manually
5. Verify it worked

This process is slow, error-prone, and burns engineering time on work that follows known patterns. Most incidents are ones you've seen before.

AutoOps AI automates this entire loop while keeping humans in control of every risky decision.

---

## How It Works

```
[Infrastructure] → [Detect anomaly] → [Match playbook / LLM reasoning]
                                              ↓
                                    [Classify risk: LOW / MEDIUM / HIGH]
                                              ↓
                           ┌──────────────────┼──────────────────┐
                        [LOW]             [MEDIUM]             [HIGH]
                      Auto-execute      Approval card        Approval card
                      + notify          in dashboard         (no timeout)
                           └──────────────────┼──────────────────┘
                                              ↓
                                     [Execute fix]
                                              ↓
                                     [Verify outcome]
                                              ↓
                                     [Audit log + notify]
```

**Tiered autonomy:** LOW risk actions (cache clear, log rotation) execute automatically. MEDIUM risk (service restart, scale up) and HIGH risk (database restart, failover) surface an approval card in the dashboard chat window — similar to how an AI model asks for permission before taking an action — with a description of the action, risk level, and Approve/Deny buttons.

---

## Architecture Overview

The system has seven components:

| Component | Responsibility |
|---|---|
| **Metrics Collector** | Polls infrastructure every 15s for CPU, memory, health checks; queries Prometheus + Loki |
| **Agent Engine** | Detects anomalies, matches playbooks, calls LLM, classifies risk |
| **Knowledge Base** | YAML playbook files: symptom patterns → root cause → fix steps |
| **LLM Client** | Local Ollama inference for diagnosis and novel issue reasoning |
| **Approval Router** | Routes decisions: auto-execute (LOW) or approval card (MEDIUM/HIGH) |
| **Remediation Executor** | Executes approved actions via the provider interface; verifies outcome |
| **Dashboard** | Web UI: incident timeline, agent chat, approval cards, system health |
| **Observability Stack** | Prometheus (metrics) + Loki (logs) + Grafana (unified UI) — PLG stack |

All infrastructure interaction goes through the **`InfrastructureProvider` abstraction** — the agent engine never calls Docker or kubectl directly. This is what makes adding Kubernetes, ECS, or any other platform a matter of implementing one interface, not changing the core.

See [docs/architecture.md](docs/architecture.md) for the full system design and component breakdown.

> **Note on the architecture diagram (`image.png`):** The diagram in this repo shows "Claude / GPT" as the LLM engine. The actual implementation uses **Ollama exclusively** with local open-source models (Llama 3, Mistral, Codellama). No data leaves the network. The diagram will be updated separately.

---

## Tech Stack

### Core

| Layer | Technology | Version | Purpose |
|---|---|---|---|
| **Language** | Python | 3.12+ | Async-first, rich DevOps ecosystem |
| **Package Manager** | uv | latest | Fast dependency resolution + virtual env management |
| **Backend** | FastAPI | ≥0.135.2 | Async REST + WebSocket, auto OpenAPI docs |
| **ASGI Server** | Uvicorn | ≥0.42.0 | Production-grade ASGI server with WebSocket support |
| **Database** | MongoDB + Motor + Beanie | Motor ≥3.6, Beanie ≥1.27 (<2.0) | Async document store with ODM; incident, approval, audit, chat persistence |
| **LLM** | Ollama (local) | SDK ≥0.4.0 | Air-gapped inference — **no data leaves the network** |
| **LLM Models** | qwen3:4b (primary), mistral:7b (fallback) | — | Structured JSON diagnosis, novel issue reasoning, interactive chat |
| **Knowledge Base** | YAML playbook files | — | Human-readable, version-controlled remediation runbooks |
| **Infrastructure** | Docker SDK for Python | ≥7.1.0 | Container lifecycle management via provider abstraction |

### Frontend

| Layer | Technology | Purpose |
|---|---|---|
| **Dashboard** | Vanilla HTML/CSS/JS (SPA) | Dark ops-console UI — no build step, served by FastAPI |
| **Real-time** | WebSocket (`/api/v1/ws/events`) | Live incident feed, approval notifications, service state changes |
| **Styling** | Custom CSS (CSS variables) | Dark theme with semantic color system (severity, status badges) |

### Observability

| Layer | Technology | Purpose |
|---|---|---|
| **Metrics** | Prometheus + cAdvisor | Per-container telemetry; agent exposes `/metrics` for self-monitoring |
| **Logs** | Loki + Promtail | Label-indexed log aggregation; lighter than ELK |
| **Dashboards** | Grafana | Unified metrics + logs UI with auto-provisioned dashboards |
| **Agent Metrics** | Prometheus text format (`/metrics`) | Exposes `autoops_incidents_total`, `autoops_incidents_resolved_total`, `autoops_approval_pending_total`, `autoops_ws_clients` |

### Resilience & Security

| Layer | Technology | Purpose |
|---|---|---|
| **Retry** | Tenacity | Exponential backoff on LLM calls (3 retries, 2s–10s) |
| **HTTP** | httpx | Async HTTP for Prometheus/Loki/Grafana queries |
| **Config** | pydantic-settings + `.env` | Centralized typed config with validation |
| **Auth (pre-RBAC)** | `X-API-Key` header | Static API key guard on state-changing endpoints |
| **Graceful Degradation** | Built-in | Docker/Prometheus/Loki/Grafana failures don't crash the agent |

### Development & Testing

| Layer | Technology | Version | Purpose |
|---|---|---|---|
| **Test Framework** | pytest + pytest-asyncio | ≥9.0.2 / ≥1.3.0 | 236 unit tests across 16 test files |
| **Linter** | Ruff | ≥0.11.0 | Fast Python linter/formatter — zero warnings |
| **Live Reload** | watchfiles | ≥1.0.0 | Dev server auto-reload |

### Future (Planned)

| Layer | Technology | Purpose |
|---|---|---|
| **Approval** | MS Teams Adaptive Cards | Enterprise approval workflow in Teams |
| **Provider** | Kubernetes Python client | K8s cluster management via same provider abstraction |
| **Auth** | JWT + RBAC | Role-based access replacing static API key |
| **Learning Loop** | Incident outcome feedback | Playbooks auto-tuned from resolution success/failure |

---

## Project Status

**Phase 4 — Dashboard + Integration Complete**

The core system is fully implemented and running. All components are operational:

| Component | Status |
|---|---|
| Metrics Collector (Prometheus/Loki polling) | ✅ Running |
| Anomaly Detection Engine | ✅ Running |
| Knowledge Base (8 YAML playbooks) | ✅ Loaded |
| Ollama LLM Client (qwen3:4b) | ✅ Connected |
| Risk Classification (LOW/MEDIUM/HIGH) | ✅ Active |
| Approval Router (auto/card/timeout) | ✅ Active |
| Remediation Executor | ✅ Active |
| MongoDB Incident Store | ✅ Connected |
| REST API (12 endpoints) | ✅ Serving |
| WebSocket live events | ✅ Broadcasting |
| Dashboard UI | ✅ Serving at `/` |
| Unit Tests (236 passing) | ✅ Green |
| Ruff lint | ✅ Zero warnings |

Infrastructure dependencies degrade gracefully — the agent starts and operates in reduced mode when Docker, Prometheus, Loki, or Grafana are unavailable.

| Phase | Description |
|---|---|
| Phase 1 | Foundation: project setup, demo infrastructure stack, provider interface, metrics collector |
| Phase 2 | Agent Brain: knowledge base, Ollama LLM client, anomaly detection, core reasoning loop |
| Phase 3 | Approval + Remediation: dashboard chat approval, remediation executor, full wired loop |
| Phase 4 | Dashboard + Polish: Streamlit UI, three demo scenarios, approval card polish |
| Phase 5 | Demo Prep + Hardening: resilience fallbacks, backup recordings, pitch deck |
| Phase 6+ | Kubernetes, learning loop, predictive analysis, MS Teams, production hardening |

---

## Repository Layout

```
AutoOpsAI/
├── image.png                   # Architecture diagram (see note above re: LLM engine)
├── AutoOps_AI_Roadmap.md       # Strategy, competitive landscape, demo flow
└── docs/
    ├── architecture.md         # System design, component breakdown, tech stack
    ├── api-design.md           # REST + WebSocket API specification
    ├── implementation-plan.md  # Phased build plan with checklists
    ├── playbook-schema.md      # YAML knowledge base format with examples
    └── provider-interface.md   # InfrastructureProvider ABC and data models
```

No source code exists yet — all directories shown in the docs are planned structure.

---

## For Contributors

### Reading Order

Before writing any code, read the docs in this order:

1. **[docs/architecture.md](docs/architecture.md)** — Understand the system design and the provider abstraction. This is the most important doc.
2. **[docs/provider-interface.md](docs/provider-interface.md)** — Read the `InfrastructureProvider` ABC and all data models. These are the contracts everything is built around.
3. **[docs/playbook-schema.md](docs/playbook-schema.md)** — Understand the knowledge base format. This is how known issues are encoded.
4. **[docs/implementation-plan.md](docs/implementation-plan.md)** — See what gets built in what order, and why.
5. **[docs/api-design.md](docs/api-design.md)** — The full REST and WebSocket API spec.
6. **[AutoOps_AI_Roadmap.md](AutoOps_AI_Roadmap.md)** — Strategy, competitive context, and the full demo narrative.

### Key Design Decisions to Understand First

- **Provider abstraction is non-negotiable.** The agent engine, approval flow, and knowledge base must never import Docker- or Kubernetes-specific code. Use `provider.restart_service()`, not `container.restart()`.
- **LLM is local-only.** Ollama serves all inference. No calls to external APIs (OpenAI, Anthropic, etc.). Infrastructure data is sensitive.
- **Approval is dashboard-first for MVP.** No Slack, no Teams, no webhooks in Phase 1-4. The dashboard chat window handles all approval cards. MS Teams is the target for production.
- **Stateless engine.** The agent's reasoning loop has no mutable state. All state lives in the SQLite incident store.

### Ollama Setup

Before Phase 2, you'll need Ollama running locally:

```bash
# Install Ollama: https://ollama.com/download
ollama pull llama3:8b      # Primary model (good balance of quality + speed)
ollama pull mistral:7b     # Faster fallback for resource-constrained environments

# Verify it's running
curl http://localhost:11434/api/tags
```

### Environment Setup (when implementation starts)

```bash
# Clone and set up Python environment
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"    # pyproject.toml will be created in Phase 1

# Copy and fill in config
cp .env.example .env       # .env.example will be created in Phase 1
```

Required environment variables (to be configured in Phase 1):

| Variable | Description | Default |
|---|---|---|
| `OLLAMA_HOST` | Ollama server URL | `http://localhost:11434` |
| `OLLAMA_MODEL` | Model to use | `llama3:8b` |
| `PROVIDER_TYPE` | Infrastructure provider | `docker_compose` |
| `POLLING_INTERVAL` | Metrics polling interval (seconds) | `15` |
