# POC 5: Playbook Matching & Knowledge Base

## What this proves

1. **YAML playbook loading** — Structured playbook entries (detection conditions, diagnosis, remediation steps, rollback) load from multiple YAML files
2. **Pattern matching** — Anomaly events match against playbook entries via container_health, metric_threshold, and log_pattern strategies
3. **Fuzzy fallback** — When detection types don't align exactly, keyword overlap still finds relevant playbooks
4. **LLM fallback** — When no playbook matches, Ollama generates a structured JSON diagnosis with severity, action, rollback, and verification
5. **Structured output reliability** — JSON extraction handles markdown fences, extra text, and validates all required fields

## Architecture

```
AnomalyEvent → KnowledgeBase.match()
                  ├── container_health matcher (name + status)
                  ├── metric_threshold matcher (metric name + value)
                  ├── log_pattern matcher (container + pattern)
                  └── fuzzy keyword fallback
              ↓
         MatchResult?
           ├── YES → PlaybookEntry (diagnosis, remediation, rollback)
           └── NO  → llm_diagnose() → LLMDiagnosis (structured JSON from Ollama)
```

## Prerequisites

- Python with `pyyaml`, `rich`, `httpx`, `tenacity`
- Ollama running with `qwen3:4b` (only needed for LLM fallback scenarios)

## Run

```bash
uv run python -m POCs.playbook_matching.demo
```

## Test scenarios

| # | Scenario | Expected result |
|---|----------|----------------|
| 1 | MongoDB container exited | Exact match → `mongodb_container_down` |
| 2 | Redis memory at 95% | Metric match → `redis_memory_full` |
| 3 | Nginx 502 errors | Log pattern match → `nginx_502_errors` |
| 4 | CPU at 96% | Metric match → `high_cpu_container` |
| 5 | Container restart loop (5x) | Container health match → `container_restart_loop` |
| 6 | Redis container exited | Exact match → `redis_connection_refused` |
| 7 | Disk usage at 98% | No match → LLM fallback |
| 8 | Celery worker OOMKilled | No match → LLM fallback |
