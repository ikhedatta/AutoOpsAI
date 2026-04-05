# [Step 00] — Observability Stack (Optional: Loki + Promtail + cAdvisor)

## Context

This step is **optional and additive** — run it only if Loki, Promtail, or cAdvisor are not already deployed in your environment.

Per the production implementation plan:
- **Prometheus and Grafana are assumed already deployed.** This step does NOT deploy them.
- **Loki + Promtail:** deploy if log querying is not yet available.
- **cAdvisor:** deploy if per-container CPU/memory metrics are not yet exported to Prometheus.

This step can be run **in parallel with Steps 01-04** — it has no dependency on the Python project.

## Objective

Produce `docker-compose.observability.yml` with optional Loki, Promtail, and cAdvisor services. Provide Prometheus scrape config additions and a Grafana datasource provisioning file. All services connect to the existing Prometheus/Grafana network.

## Files to Create

- `infra/docker-compose/docker-compose.observability.yml` — Loki, Promtail, cAdvisor services.
- `infra/observability/loki-config.yaml` — Loki configuration.
- `infra/observability/promtail-config.yaml` — Promtail configuration (tails Docker container logs).
- `infra/observability/prometheus-scrape-additions.yaml` — Scrape targets to add to existing Prometheus config.
- `infra/observability/grafana-datasources.yaml` — Loki datasource for Grafana provisioning.

## Files to Modify

None — existing Prometheus/Grafana configs are modified by the operator manually using the provided snippets.

## Key Requirements

**infra/docker-compose/docker-compose.observability.yml:**

```yaml
version: "3.8"

services:

  loki:
    image: grafana/loki:2.9.0
    container_name: loki
    command: -config.file=/etc/loki/config.yaml
    volumes:
      - ./infra/observability/loki-config.yaml:/etc/loki/config.yaml:ro
      - loki-data:/loki
    ports:
      - "3100:3100"
    networks:
      - autoops-observability-net
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:3100/ready"]
      interval: 10s
      timeout: 5s
      retries: 3

  promtail:
    image: grafana/promtail:2.9.0
    container_name: promtail
    command: -config.file=/etc/promtail/config.yaml
    volumes:
      - ./infra/observability/promtail-config.yaml:/etc/promtail/config.yaml:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - autoops-observability-net
    depends_on:
      loki:
        condition: service_healthy
    restart: unless-stopped

  cadvisor:
    image: gcr.io/cadvisor/cadvisor:v0.49.1
    container_name: cadvisor
    privileged: true
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    ports:
      - "8081:8080"
    networks:
      - autoops-observability-net
    restart: unless-stopped

volumes:
  loki-data:

networks:
  autoops-observability-net:
    external: true   # Must match the network name of the existing Grafana/Prometheus stack
    name: autoops-observability-net
```

> **Network name:** Change `autoops-observability-net` to match whatever network your existing Prometheus/Grafana stack uses. Run `docker network ls` to find it.

**infra/observability/loki-config.yaml:**

```yaml
auth_enabled: false

server:
  http_listen_port: 3100
  grpc_listen_port: 9096

common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    instance_addr: 127.0.0.1
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: 2020-10-24
      store: boltdb-shipper
      object_store: filesystem
      schema: v11
      index:
        prefix: index_
        period: 24h

limits_config:
  retention_period: 7d     # Keep 7 days of logs (adjust as needed)
  ingestion_rate_mb: 10
  ingestion_burst_size_mb: 20

compactor:
  working_directory: /loki/boltdb-shipper-compactor
  shared_store: filesystem
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
  retention_delete_worker_count: 150
```

**infra/observability/promtail-config.yaml:**

```yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: docker-containers
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 5s
    relabel_configs:
      # Use container name as the "job" label
      - source_labels: [__meta_docker_container_name]
        regex: "/(.*)"
        target_label: container
      # Use compose project as the "compose_project" label
      - source_labels: [__meta_docker_container_label_com_docker_compose_project]
        target_label: compose_project
      # Use compose service name as the "service" label
      - source_labels: [__meta_docker_container_label_com_docker_compose_service]
        target_label: service
      # Only scrape containers on the autoops-demo network (demo target stack)
      # Remove this filter to scrape ALL Docker container logs
      - source_labels: [__meta_docker_container_label_com_docker_compose_project]
        regex: "autoops-demo"
        action: keep

    pipeline_stages:
      # Parse JSON logs (demo-app emits structured JSON)
      - json:
          expressions:
            level: level
            message: message
            timestamp: timestamp
      - labels:
          level:
      - timestamp:
          source: timestamp
          format: RFC3339
```

**infra/observability/prometheus-scrape-additions.yaml:**

This file is NOT loaded automatically — the operator manually copies these job definitions into their existing `prometheus.yml` scrape_configs section.

```yaml
# Add these jobs to your existing prometheus.yml → scrape_configs:

- job_name: 'autoops-agent'
  scrape_interval: 15s
  static_configs:
    - targets: ['autoops-agent:8000']
  metrics_path: /metrics

- job_name: 'cadvisor'
  scrape_interval: 15s
  static_configs:
    - targets: ['cadvisor:8080']
  metrics_path: /metrics

# cAdvisor exposes these key metrics used by AutoOps:
#   container_cpu_usage_seconds_total{name="..."}
#   container_memory_usage_bytes{name="..."}
#   container_network_receive_bytes_total{name="..."}
#   container_network_transmit_bytes_total{name="..."}
#   container_fs_reads_bytes_total{name="..."}
#   container_fs_writes_bytes_total{name="..."}
```

**infra/observability/grafana-datasources.yaml:**

Grafana provisioning file — place in Grafana's `provisioning/datasources/` directory so Loki appears automatically as a datasource.

```yaml
apiVersion: 1

datasources:
  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    isDefault: false
    jsonData:
      maxLines: 1000
    version: 1
    editable: false
```

**AutoOps agent `LOKI_URL` configuration:**

Once Loki is running, set in `.env`:
```
LOKI_URL=http://loki:3100
```

The `LokiClient` in `agent/collector/loki_client.py` reads this URL.

**Verification queries (run after stack is up):**

```bash
# Verify Loki is running
curl http://localhost:3100/ready
# Expected: "ready"

# Verify Promtail is ingesting logs (after demo stack is running a minute)
curl 'http://localhost:3100/loki/api/v1/query?query={compose_project="autoops-demo"}&limit=5'
# Expected: JSON with log streams (may be empty if demo stack not started)

# Verify cAdvisor is exposing metrics
curl http://localhost:8081/metrics | grep container_cpu_usage
# Expected: Prometheus-format metrics lines

# Verify AutoOps agent can query Loki
python -c "
import asyncio
from agent.collector.loki_client import LokiClient
async def test():
    client = LokiClient(base_url='http://localhost:3100')
    ok = await client.check_connection()
    print('Loki connection:', ok)
asyncio.run(test())
"
# Expected: Loki connection: True
```

## Test Criteria

```bash
# Start observability stack
docker compose -f infra/docker-compose/docker-compose.observability.yml up -d

# Wait 30s for Loki to initialize
sleep 30

# Health checks
curl -s http://localhost:3100/ready        # Expected: ready
curl -s http://localhost:8081/healthz      # Expected: ok

# After starting the demo target stack (Step 05):
docker compose -f infra/docker-compose/docker-compose.target.yml -p autoops-demo up -d
sleep 60  # Let Promtail collect some logs

# Query Loki for demo stack logs
curl -G 'http://localhost:3100/loki/api/v1/query_range' \
  --data-urlencode 'query={compose_project="autoops-demo"}' \
  --data-urlencode 'limit=5' \
  --data-urlencode "start=$(date -d '5 minutes ago' +%s)000000000" \
  --data-urlencode "end=$(date +%s)000000000"
# Expected: JSON response with at least 1 log stream entry
```

## Dependencies

- None — this step is independent of the Python project.
- Step 05 (demo target stack) — to have containers whose logs Promtail will collect.
- The **existing Prometheus/Grafana deployment** must be reachable on the same Docker network.
