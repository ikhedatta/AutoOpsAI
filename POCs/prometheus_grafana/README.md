# POC 4: Prometheus, Grafana & Loki Observability Agent

Demonstrates an Ollama-powered agent that queries Prometheus metrics, Grafana dashboards, and Loki logs to investigate infrastructure issues.

## Architecture

```
User Question → Ollama (with tool schemas) → Tool Call Decision
                     ↕                             ↓
               Final Diagnosis ← Results ← Query APIs
                     ↑                        ↙  ↓  ↘
                (agentic loop)     Prometheus  Grafana  Loki
```

## Available Tools

### Prometheus (Metrics)
| Tool | Description |
|------|-------------|
| `prometheus_instant_query` | Current metric value via PromQL |
| `prometheus_range_query` | Time series over a window |
| `prometheus_get_targets` | Scrape target health |
| `prometheus_get_alerts` | Active firing alerts |
| `prometheus_list_metrics` | Available metric names |

### Grafana (Dashboards)
| Tool | Description |
|------|-------------|
| `grafana_list_dashboards` | Search dashboards |
| `grafana_get_dashboard` | Dashboard panels and queries |
| `grafana_get_annotations` | Events/alerts timeline |
| `grafana_get_datasources` | Configured data sources |

### Loki (Logs)
| Tool | Description |
|------|-------------|
| `loki_query_logs` | Query logs via LogQL |
| `loki_list_labels` | Available log labels |

## Quick Start

### Without observability stack (demo mode)
```bash
uv run python -m POCs.prometheus_grafana.demo
```
The agent will call tools, handle connection errors, and still demonstrate the tool-calling flow.

### With full observability stack
```bash
# Start Prometheus + Grafana + Loki + exporters
docker compose -f POCs/prometheus_grafana/docker-compose.yml up -d

# Wait ~30s for metrics to populate, then run
uv run python -m POCs.prometheus_grafana.demo
```

## Services

| Service | URL | Purpose |
|---------|-----|---------|
| Prometheus | http://localhost:9090 | Metrics storage & PromQL |
| Grafana | http://localhost:3000 | Dashboards (admin/admin) |
| Loki | http://localhost:3100 | Log aggregation |
| Node Exporter | http://localhost:9100 | Host metrics |
| cAdvisor | http://localhost:8080 | Container metrics |
