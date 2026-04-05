# POC 1 — Multi-Agent Ollama Pipeline

## What this proves

A chain of four specialized LLM agents can be orchestrated locally using Ollama (gemma3), passing structured outputs from one agent as input to the next. No cloud APIs, no data leaving the machine.

This validates the core AutoOpsAI pattern: raw telemetry → Diagnose → RCA → Remediate → Summarize.

## How to run

```bash
# 1. Start Ollama and pull the model (one-time)
ollama serve
ollama pull gemma3

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the demo
python demo.py
```

## Agent pipeline

| Agent | Role | Production mapping |
|---|---|---|
| `DiagnosticAgent` | Classifies severity and affected components from raw metrics | Alertmanager → triage layer |
| `RCAAgent` | Traces causal chain back to root cause | Incident analysis service |
| `RemediationAgent` | Produces ordered, risk-annotated remediation steps | Runbook automation layer |
| `SummaryAgent` | Translates technical output to stakeholder-friendly summary | Incident comms / PagerDuty notes |

## Sample output structure

```
SEVERITY: CRITICAL
AFFECTED_COMPONENTS: autoops-api, MongoDB connection pool
ROOT_CAUSE_HYPOTHESIS: MongoDB connection pool exhaustion causing memory pressure and cascading OOMKills
CONFIDENCE: 92%
...
```

Each agent receives the full context from upstream agents, enabling downstream reasoning to build on prior structured output.

## Architecture notes

- `OllamaClient` wraps the `/api/chat` endpoint with retry logic (tenacity) and typed exceptions
- `BaseAgent` provides the run/history interface; concrete agents only define `name` and `system_prompt`
- The pipeline is sequential by design — each agent's output is a dependency for the next
