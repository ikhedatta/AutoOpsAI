# AutoOps AI — Project Roadmap & Differentiation Strategy

## Current Status: Phase 0 — Planning & Business Approval

All technical documentation is complete. This document and the supporting docs in `docs/` are the basis for stakeholder and SME review. Implementation begins after sign-off.

See [docs/implementation-plan.md](docs/implementation-plan.md) for the full phased build plan.

---

## 1. Idea evaluation

### Strengths

- **High-impact problem space**: Incident response is a $14.95B market (2025) growing at 25.7% CAGR, projected to reach $37.33B by 2029. Every cloud-native team has felt this pain.
- **Human-in-the-loop is your moat**: Most self-healing tools go fully autonomous. Enterprise buyers want safety guardrails. The approval-gate concept is the exact trust mechanism missing from competitors.
- **Demoability is excellent**: You can simulate a real outage, show the agent detecting it, proposing a fix in plain language, getting approval via a dashboard card, executing, and verifying — all in a 5-minute live demo.
- **Air-gapped inference**: Ollama runs entirely on-prem. No infrastructure telemetry, service names, or logs ever leave the network. This is a significant enterprise differentiator.
- **Skill coverage**: AI/ML + K8s + Cloud + DevOps + Python backend covers every layer of this system.

### Risks to manage

- **Scope creep is the #1 killer**: This could easily expand to 20+ features. The MVP needs exactly 3 polished demo scenarios, not 15 half-working ones.
- **"Just another dashboard" perception**: If the UI looks like Grafana with a chatbot bolted on, the demo will underwhelm. The agent conversation must be the primary interface — the approval card in the chat window is the "wow" moment, not a chart.
- **Real infra complexity**: Don't try to monitor actual production systems. Use a self-contained Docker Compose stack where failures can be injected predictably.
- **Ollama cold-start latency**: First inference call on an unloaded model can take several seconds. Pre-warm the model before the demo.

### Verdict

**Strong idea — 8/10 potential.** The gap between existing tools and this vision is real, the demo narrative is compelling, and the technical scope is achievable. The key is ruthless prioritisation.

---

## 2. Competitive landscape & positioning

### Existing platforms and what they do well

| Platform | Core strength | What they lack |
|---|---|---|
| **PagerDuty + Rundeck** | Enterprise runbook automation, alert routing, human escalation workflows | No AI reasoning — runbooks are manually authored; no conversational interface |
| **Shoreline.io** (acquired by NVIDIA) | Fleet-wide automated remediation, custom Op language for playbooks | Cloud-only, steep learning curve, no LLM-powered diagnosis, no longer accepting new customers |
| **Kubiya** | AI agent for DevOps via Slack/Teams, natural language commands | Focused on workflow execution, not anomaly detection or self-healing loops |
| **Harness** | AI-powered CI/CD, automated rollbacks, pipeline health monitoring | Deployment-focused, not general infrastructure monitoring and remediation |
| **Dynatrace (Davis AI)** | Deep observability, automatic root cause analysis, full-stack monitoring | Expensive, complex setup, no conversational agent, no human approval gates |
| **Datadog (Watchdog)** | Anomaly detection, unified monitoring, 1000+ integrations | Alerting-first, remediation requires external tooling |
| **StackStorm** (open-source) | Event-driven automation, multi-step workflows, good K8s integration | Rule-based only, no AI reasoning, complex YAML configuration |

### The gap you're filling

None of these tools provide a single experience where:
1. An AI agent **monitors** infrastructure in real-time
2. **Diagnoses** issues using both pattern matching AND LLM reasoning
3. **Explains** the problem and proposed fix in natural language
4. **Requests approval** through an interface the team is already using
5. **Executes** the fix and **verifies** the outcome
6. **Learns** by adding the resolution to a knowledge base

This is the "virtual DevOps engineer" experience. Existing tools are components; AutoOps AI is the orchestrator.

### Your 3 differentiation pillars

**Pillar 1: Conversational-first interface**
- The agent explains what it found, why it matters, and what it wants to do — in plain English
- Approval cards in the dashboard chat window make the interaction feel like working with an AI assistant, not navigating a dashboard
- Compare: PagerDuty pages you and you go digging. AutoOps AI tells you what's wrong and what to do about it

**Pillar 2: Tiered autonomy with human gates**
- LOW risk (log rotation, cache clear, temp file cleanup) → Auto-execute, notify in dashboard chat
- MEDIUM risk (restart a service, scale up replicas) → Approval card in dashboard (5-min timeout, deny-by-default); MS Teams in production
- HIGH risk (restart database, failover, scale down) → Approval card required, no timeout, no auto-execute
- Compare: Shoreline auto-executes everything. PagerDuty requires manual everything. AutoOps AI is the smart middle ground

**Pillar 3: Knowledge-base-driven playbooks**
- A structured YAML playbook of known issues: symptom patterns → root cause → fix steps → verification
- LLM (local, via Ollama) matches incoming anomalies to playbook entries AND can reason about novel issues
- Every resolved incident can be added back to the playbook (learning loop)
- Compare: StackStorm requires manual rule writing. Dynatrace uses proprietary ML. AutoOps AI combines structured knowledge with local LLM flexibility — no data leaves the network

---

## 3. Technical architecture

### Stack

| Layer | Technology | Why |
|---|---|---|
| **Metrics** | Prometheus + cAdvisor | Lightweight, runs in Docker, K8s-native; cAdvisor provides per-container telemetry out of the box |
| **Logs** | Loki + Promtail | Lightweight log aggregation (label-only indexing, far lighter than ELK); native Grafana integration |
| **Observability UI** | Grafana | Single pane for both metrics and logs; auto-provisioned dashboards for infra health and agent performance |
| **AI engine** | Ollama (local) — Llama 3 8B/70B, Mistral 7B, Codellama | Air-gapped inference — no data leaves the network; structured JSON output; no API costs |
| **Backend** | FastAPI (Python) | Async, fast, auto OpenAPI docs |
| **Task queue** | asyncio (MVP), Celery + Redis (production) | Keep it simple first |
| **Approval (MVP)** | Dashboard chat window with approval cards | No external service dependencies; first-class UI element |
| **Approval (production)** | MS Teams Adaptive Cards | Enterprise teams live in Teams; interactive button support |
| **Frontend dashboard** | Streamlit (MVP), React + Tailwind (production) | Streamlit for speed; React for polish |
| **Infrastructure targets** | Docker Compose stack (Nginx + FastAPI demo app + MongoDB + Redis) | Self-contained, failure-injectable, easy to demo |
| **Knowledge base** | YAML files in `playbooks/` | Human-readable, version-controlled |

### Component breakdown

**1. Metrics Collector Service** (Python)
- Polls Docker stats API + custom health endpoints every 15 seconds
- Watches: CPU/memory per container, request latency, error rates, disk usage
- Checks MongoDB replica set status, Redis ping, custom health endpoints
- Scrapes Prometheus (cAdvisor) for additional container telemetry
- Queries Loki for log-pattern anomalies (e.g., Nginx 502 rate)
- Exposes its own `/metrics` endpoint for Prometheus to scrape (meta-monitoring)
- Emits structured events to the Agent Engine

**2. Agent Engine** (Python + Ollama)
- Receives events from the collector
- Step 1: Rule-based anomaly detection (thresholds from config)
- Step 2: If anomaly detected, query the knowledge base for matching patterns
- Step 3: If match found, format the playbook fix. If no match, use local Ollama model to reason about the issue
- Step 4: Classify risk level (LOW/MEDIUM/HIGH)
- Step 5: Route to appropriate action path (auto-execute, request approval via dashboard card, or escalate)

**3. Approval Router** (Python)
- LOW risk → auto-execute + notification bubble in dashboard chat
- MEDIUM/HIGH risk → approval card in dashboard chat window
- Card shows: diagnosis, proposed action, risk badge, rollback plan, Approve / Deny / Investigate buttons
- MEDIUM: 5-minute timeout, deny-by-default
- HIGH: no timeout — explicit approval required
- Production (Phase 9+): routes to MS Teams Adaptive Cards instead

**4. Remediation Executor** (Python)
- Receives approved actions
- Executes via the `InfrastructureProvider` interface (Docker SDK, kubectl, etc.)
- Runs verification checks after execution
- Reports success/failure back to the Agent Engine
- Updates the approval card in-place with the outcome

**5. Dashboard** (Streamlit / React)
- Live incident timeline
- Chat interface showing agent reasoning and approval cards
- Playbook management (view/add known issues)
- Metrics overview (recent incidents, MTTR, auto-resolved count)

---

## 4. What to BUILD (core MVP)

These are the must-haves that need to work in the demo:

1. **Docker Compose target stack** — Nginx reverse proxy + FastAPI demo app + MongoDB + Redis. Include a chaos script that can inject failures (kill a container, spike CPU, corrupt MongoDB connection).

2. **Metrics collector** — Poll Docker stats API + custom health endpoints every 10-15 seconds. Detect: container down, high CPU, high memory, health check failures.

3. **Agent reasoning loop** — When anomaly detected: check playbook YAML → format diagnosis → classify risk → decide action. Use local Ollama model for the "explain what's happening" step.

4. **Dashboard chat window approval flow** — When a MEDIUM/HIGH risk action is proposed, an approval card appears in the dashboard chat window. The card has Approve / Deny / Investigate More buttons. This is the "wow" moment of the demo — watching a card appear in real time, with the agent clearly explaining what it wants to do and why, before taking any action.

5. **Remediation execution** — Docker restart, MongoDB connection pool reset, Redis flush. Verify fix worked by re-checking health after 30 seconds. Update the approval card with the outcome.

6. **Simple web dashboard** — Incident timeline, agent chat log with approval cards, system health. Streamlit is fastest for MVP.

### What to MOCK (save time)

- **Predictive analytics** — Use threshold-based rules and have the agent say "Based on the trend, this will likely cause an outage in 20 minutes." The LLM makes it sound predictive even with simple logic.
- **Kubernetes integration** — Keep it Docker-only and mention K8s support in the pitch as "next phase."
- **Azure DevOps integration** — Show with Docker, pitch the extensibility.
- **Multi-cloud support** — Don't try. One Docker Compose stack, done well, beats a broken multi-cloud demo.
- **User management / auth** — Skip entirely for MVP.
- **Playbook learning loop** — Have a pre-populated playbook. The "agent learns from new incidents" can be a pitch point without being fully automated.
- **MS Teams integration** — Pitch as production roadmap; MVP uses dashboard approval only.

---

## 5. Suggested demo flow (5 minutes)

**Minute 0-1: Set the stage**
- Show the healthy dashboard: "Here's our stack — Nginx, FastAPI demo app, MongoDB, Redis. Everything green."
- "AutoOps AI is monitoring all containers, metrics, and health endpoints in real-time."

**Minute 1-2: Inject the failure**
- Run the chaos script: kill the MongoDB container
- Show the agent detecting it within seconds
- An approval card appears in the dashboard chat: "I detected MongoDB is unreachable. The FastAPI demo app is returning 500 errors. Based on my playbook, this is a known issue — the MongoDB container has crashed. I'd like to restart the MongoDB container and verify replica set health. Risk level: MEDIUM. Approve?"

**Minute 2-3: Human approval**
- Click "Approve" on the card in the dashboard
- Show the agent executing: restarting MongoDB, waiting for it to come up, checking replica set status
- Card updates in-place: "MongoDB restarted successfully. Replica set is healthy. FastAPI demo app is responding normally. Incident resolved in 47 seconds."

**Minute 3-4: Show a second scenario (auto-resolved)**
- Inject a LOW risk issue: Redis cache is full
- Agent auto-executes a cache flush (no approval needed for LOW risk)
- A notification bubble appears in chat: "Auto-resolved: Redis memory at 95% → purged → now at 42%. No approval needed for LOW risk actions."

**Minute 4-5: Show the knowledge base and pitch**
- Show the playbook: "Here are the known issues AutoOps AI can handle today"
- Show the incident timeline: "Two incidents resolved in under 2 minutes with zero human investigation time"
- Pitch the vision: "AutoOps AI is your virtual DevOps engineer that never sleeps, always explains its reasoning, and never takes dangerous actions without your approval."

---

## 6. Knowledge base schema (starter playbook)

```yaml
playbook:
  - id: mongodb_container_down
    name: "MongoDB container crash"
    severity: MEDIUM
    detection:
      type: container_health
      conditions:
        - container_name: "mongodb"
          status: "exited"
        - dependent_service: "demo-app"
          error_rate: "> 50%"
    diagnosis: >
      MongoDB container has stopped running. This is causing the FastAPI demo
      application to return 500 errors on all database-dependent endpoints.
      Common causes: OOM kill, disk full, or unclean shutdown.
    remediation:
      steps:
        - action: docker_restart
          target: mongodb
          timeout: 30s
        - action: health_check
          target: mongodb
          check: "mongosh --eval 'rs.status()'"
          timeout: 15s
        - action: health_check
          target: demo-app
          check: "curl -s http://localhost:5000/health"
          timeout: 10s
    rollback:
      description: "If MongoDB fails to start, check disk space and OOM logs"
      steps:
        - action: collect_logs
          target: mongodb
        - action: escalate
          message: "MongoDB failed to restart. Manual investigation required."

  - id: redis_memory_full
    name: "Redis memory at capacity"
    severity: LOW
    detection:
      type: metric_threshold
      conditions:
        - metric: "redis_memory_used_ratio"
          threshold: "> 0.90"
    diagnosis: >
      Redis memory usage has exceeded 90%. This may cause eviction of cached
      data and increased latency on cache-dependent endpoints.
    remediation:
      steps:
        - action: redis_command
          command: "MEMORY PURGE"
        - action: metric_check
          metric: "redis_memory_used_ratio"
          expected: "< 0.60"
          timeout: 10s

  - id: high_cpu_container
    name: "Container CPU spike"
    severity: MEDIUM
    detection:
      type: metric_threshold
      conditions:
        - metric: "container_cpu_percent"
          threshold: "> 90%"
          duration: "2m"
    diagnosis: >
      Container CPU usage has been above 90% for over 2 minutes. This may
      indicate a resource leak, runaway process, or insufficient allocation.
    remediation:
      steps:
        - action: collect_diagnostics
          command: "docker exec {container} top -bn1"
        - action: docker_restart
          target: "{container}"
          timeout: 30s
        - action: metric_check
          metric: "container_cpu_percent"
          expected: "< 50%"
          timeout: 30s

  - id: nginx_502_errors
    name: "Nginx returning 502 Bad Gateway"
    severity: HIGH
    detection:
      type: log_pattern
      conditions:
        - container_name: "nginx"
          pattern: "502 Bad Gateway"
          rate: "> 10/min"
    diagnosis: >
      Nginx is returning 502 errors, indicating the upstream FastAPI demo application
      is unreachable or timing out. This could be caused by the app crashing,
      port binding issues, or network connectivity problems within Docker.
    remediation:
      steps:
        - action: health_check
          target: demo-app
          check: "curl -s http://demo-app:5000/health"
        - action: docker_restart
          target: demo-app
          timeout: 30s
        - action: health_check
          target: nginx
          check: "curl -s http://localhost:80/health"
          timeout: 15s
    rollback:
      description: "If FastAPI demo app won't start, check application logs for crash reason"
      steps:
        - action: collect_logs
          target: demo-app
        - action: escalate
          message: "FastAPI demo application failed to restart. Check logs for stack trace."
```

---

## 7. Project structure (suggested)

```
autoops-ai/
├── docker-compose.yml              # Target infrastructure stack
├── docker-compose.agent.yml        # AutoOps AI services
├── chaos/
│   ├── kill_mongodb.sh
│   ├── spike_cpu.sh
│   ├── fill_redis.sh
│   └── break_nginx.sh
├── agent/
│   ├── main.py                     # FastAPI app - agent API + dashboard backend
│   ├── collector.py                # Metrics and health check polling
│   ├── engine.py                   # Core reasoning loop
│   ├── knowledge_base.py           # Playbook loader and matcher
│   ├── llm_client.py               # Ollama local LLM client
│   ├── remediation.py              # Action executor (Docker API)
│   ├── approval/
│   │   ├── router.py               # Risk-based routing
│   │   ├── chat_approval.py        # Dashboard chat window approval cards (MVP)
│   │   └── webhook.py              # Generic webhook (external integrations)
│   └── models.py                   # Pydantic models for incidents, actions
├── playbooks/
│   ├── mongodb.yaml
│   ├── redis.yaml
│   ├── nginx.yaml
│   └── general.yaml
├── dashboard/
│   ├── app.py                      # Streamlit dashboard
│   └── components/
│       └── chat.py                 # Agent chat + inline approval cards
├── tests/
│   └── test_engine.py
└── README.md
```

---

## 8. Key API prompt for the agent engine

When the agent detects an anomaly and needs to reason about it, here's the system prompt pattern. Note that this is sent to the local Ollama model — keep prompts concise, as smaller models perform better with focused context:

```
You are AutoOps AI, a DevOps operations agent. You have detected an
anomaly in the infrastructure you're monitoring.

Current system state:
{metrics_snapshot}

Anomaly detected:
{anomaly_description}

Known playbook matches:
{playbook_matches_or_none}

Your task:
1. Explain what's happening in plain language (2-3 sentences)
2. Assess the severity (LOW / MEDIUM / HIGH)
3. Recommend a specific remediation action
4. Explain the rollback plan if the fix doesn't work
5. State what you'll check to verify the fix worked

Respond in this JSON format:
{
  "diagnosis": "...",
  "severity": "LOW|MEDIUM|HIGH",
  "recommended_action": "...",
  "action_type": "docker_restart|redis_command|collect_logs|escalate",
  "action_target": "container_name",
  "rollback_plan": "...",
  "verification_check": "...",
  "confidence": 0.0-1.0
}
```

---

## 9. Judging / evaluation criteria alignment

| Criterion | How AutoOps AI scores |
|---|---|
| **Innovation** | Conversational AI agent for DevOps with local LLM (no cloud dependency). Human-in-the-loop approval cards as a first-class UI concept. |
| **Technical complexity** | Multi-service architecture, local Ollama inference, real-time monitoring, Docker API automation, WebSocket-driven approval card UI. |
| **Completeness** | End-to-end flow from detection to resolution. Working demo with real failures and real fixes. |
| **Impact / usefulness** | Addresses a $15B+ market pain point. Every DevOps team would use this. |
| **Presentation** | The live demo practically runs itself: break something → watch the approval card appear → click Approve → watch it fix itself. Visceral and memorable. |
| **Scalability** | Playbook-driven design means new issue types are config, not code. Provider abstraction extends naturally to K8s, ECS, cloud APIs. |
| **Security / enterprise readiness** | Ollama-only LLM means no data leaves the network. Air-gapped inference is a significant enterprise differentiator. |

---

## 10. Timeline suggestion (MVP build)

### Hours 0-6: Foundation
- Set up Docker Compose target stack (Nginx + FastAPI demo app + MongoDB + Redis)
- Write chaos scripts that reliably inject failures
- Set up FastAPI project skeleton and Pydantic models

### Hours 6-16: Core agent
- Build metrics collector (Docker stats API + health endpoints)
- Build playbook loader and pattern matcher
- Integrate local Ollama model for diagnosis generation
- Build remediation executor (Docker API restart, Redis commands)

### Hours 16-24: Approval flow + integration
- Build dashboard chat window approval card mechanism
- Wire up the full loop: detect → diagnose → approval card → execute → verify
- Test all 3-4 demo scenarios end-to-end

### Hours 24-36: Dashboard + polish
- Build Streamlit dashboard (incident timeline, agent chat with approval cards, system health)
- Polish the approval cards (severity badges, timing info, code blocks)
- Add the second and third demo scenarios
- Investigate More flow: agent posts detailed reasoning on demand

### Hours 36-48: Demo prep
- Practice the demo flow 5+ times
- Prepare backup recordings in case of live demo issues
- Write the pitch deck (5 slides max: Problem → Solution → Demo → Architecture → Vision)
- Stress-test: run all chaos scenarios back-to-back

---

## 11. References for deeper study

- **PagerDuty Rundeck** — Best reference for runbook automation patterns
- **Shoreline.io** (NVIDIA) — Study their "Op" language for defining automations
- **Kubiya** — AI agent orchestration for DevOps teams
- **StackStorm** — Open-source event-driven automation (great patterns to learn from)
- **Autonomous SRE Agent guide** — Detailed implementation patterns with approval gates
- **PagerDuty Auto-Remediation Guide** — Self-healing system design patterns
