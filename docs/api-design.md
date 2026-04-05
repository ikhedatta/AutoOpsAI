# AutoOps AI - API Design

## Overview

The AutoOps AI backend exposes a REST API via FastAPI. This API serves:
1. **The dashboard** (frontend) — incident data, system health, playbook management, approval card state
2. **The approval chat interface** — approval action callbacks (Approve/Deny/Investigate) from the dashboard
3. **External integrations** — programmatic access to the agent; MS Teams webhook callbacks (Phase 9+)

Base URL: `http://localhost:8000/api/v1`

---

## Endpoints

### System Health & Status

#### `GET /metrics`
Prometheus metrics scrape endpoint. Returns all agent metrics in Prometheus text format. Scraped by the Prometheus instance in the observability stack.

**Response (text/plain; version=0.0.4):**
```
# HELP autoops_incidents_total Total incidents by severity and status
# TYPE autoops_incidents_total counter
autoops_incidents_total{severity="MEDIUM",status="resolved"} 12
autoops_incidents_total{severity="HIGH",status="escalated"} 1

# HELP autoops_resolution_time_seconds Incident resolution time histogram
# TYPE autoops_resolution_time_seconds histogram
autoops_resolution_time_seconds_bucket{le="30"} 8
autoops_resolution_time_seconds_bucket{le="60"} 11
autoops_resolution_time_seconds_bucket{le="+Inf"} 12

# HELP autoops_llm_inference_duration_seconds Ollama inference latency
# TYPE autoops_llm_inference_duration_seconds histogram
autoops_llm_inference_duration_seconds_bucket{le="1"} 3
autoops_llm_inference_duration_seconds_bucket{le="5"} 10

# HELP autoops_approval_pending_total Current incidents awaiting approval
# TYPE autoops_approval_pending_total gauge
autoops_approval_pending_total 1

# HELP autoops_anomalies_detected_total Anomalies detected by type
# TYPE autoops_anomalies_detected_total counter
autoops_anomalies_detected_total{type="container_down"} 3
autoops_anomalies_detected_total{type="high_cpu"} 5
autoops_anomalies_detected_total{type="log_pattern"} 2
```

#### `GET /health`
Agent service health check.

**Response:**
```json
{
  "status": "healthy",
  "provider": "docker_compose",
  "uptime_seconds": 3621,
  "monitoring": true,
  "services_monitored": 4,
  "version": "0.1.0"
}
```

#### `GET /status`
Current state of all monitored services.

**Response:**
```json
{
  "provider": "docker_compose",
  "services": [
    {
      "name": "nginx",
      "state": "running",
      "cpu_percent": 2.3,
      "memory_percent": 15.1,
      "healthy": true,
      "uptime_seconds": 7200
    },
    {
      "name": "demo-app",
      "state": "running",
      "cpu_percent": 45.2,
      "memory_percent": 62.0,
      "healthy": true,
      "uptime_seconds": 7200
    },
    {
      "name": "mongodb",
      "state": "stopped",
      "cpu_percent": 0,
      "memory_percent": 0,
      "healthy": false,
      "uptime_seconds": 0,
      "last_error": "Exited (137) 2 minutes ago"
    }
  ],
  "timestamp": "2026-03-31T10:00:00Z"
}
```

#### `GET /metrics/{service_name}`
Detailed metrics for a specific service.

**Response:**
```json
{
  "service_name": "demo-app",
  "timestamp": "2026-03-31T10:00:00Z",
  "cpu_percent": 45.2,
  "memory_used_bytes": 268435456,
  "memory_limit_bytes": 536870912,
  "memory_percent": 50.0,
  "network_rx_bytes": 1048576,
  "network_tx_bytes": 2097152,
  "disk_read_bytes": 524288,
  "disk_write_bytes": 1048576
}
```

---

### Incidents

#### `GET /incidents`
List incidents, optionally filtered.

**Query params:**
| Param | Type | Default | Description |
|---|---|---|---|
| `status` | string | all | `active`, `resolved`, `escalated` |
| `severity` | string | all | `LOW`, `MEDIUM`, `HIGH` |
| `limit` | int | 50 | Max results |
| `offset` | int | 0 | Pagination offset |

**Response:**
```json
{
  "incidents": [
    {
      "id": "inc_20260331_001",
      "title": "MongoDB container crash",
      "severity": "MEDIUM",
      "status": "resolved",
      "service": "mongodb",
      "detected_at": "2026-03-31T09:45:12Z",
      "resolved_at": "2026-03-31T09:45:59Z",
      "resolution_time_seconds": 47,
      "auto_resolved": false,
      "playbook_id": "mongodb_container_down"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

#### `GET /incidents/{incident_id}`
Full incident detail including agent reasoning, actions taken, and timeline.

**Response:**
```json
{
  "id": "inc_20260331_001",
  "title": "MongoDB container crash",
  "severity": "MEDIUM",
  "status": "resolved",
  "service": "mongodb",
  "detected_at": "2026-03-31T09:45:12Z",
  "resolved_at": "2026-03-31T09:45:59Z",
  "resolution_time_seconds": 47,
  "auto_resolved": false,
  "playbook_id": "mongodb_container_down",
  "diagnosis": {
    "summary": "MongoDB container has stopped running, causing demo app to return 500 errors on all database-dependent endpoints.",
    "confidence": 0.95,
    "llm_reasoning": "The MongoDB container exited with code 137 (OOM kill). The demo app health check is failing with connection refused errors. This matches the known playbook for MongoDB container crash.",
    "matched_playbook": "mongodb_container_down"
  },
  "actions": [
    {
      "type": "approval_requested",
      "timestamp": "2026-03-31T09:45:15Z",
      "detail": "Approval card displayed in dashboard chat window"
    },
    {
      "type": "approved",
      "timestamp": "2026-03-31T09:45:28Z",
      "detail": "Approved by operator via dashboard"
    },
    {
      "type": "remediation",
      "timestamp": "2026-03-31T09:45:30Z",
      "detail": "Restarting MongoDB container",
      "result": "success"
    },
    {
      "type": "verification",
      "timestamp": "2026-03-31T09:45:55Z",
      "detail": "MongoDB health check passed. demo app responding 200.",
      "result": "success"
    }
  ],
  "rollback_plan": "If MongoDB fails to start, check disk space and OOM logs. Escalate to on-call engineer.",
  "metrics_at_detection": {
    "mongodb": {"state": "stopped", "cpu_percent": 0, "memory_percent": 0},
    "demo-app": {"state": "running", "cpu_percent": 78.5, "error_rate": 95.2}
  }
}
```

---

### Agent Control

#### `POST /agent/start`
Start the monitoring and reasoning loop.

**Response:** `{"status": "started", "polling_interval_seconds": 15}`

#### `POST /agent/stop`
Stop the monitoring loop. No actions will be taken.

**Response:** `{"status": "stopped"}`

#### `GET /agent/config`
Get current agent configuration.

**Response:**
```json
{
  "provider": "docker_compose",
  "polling_interval_seconds": 15,
  "risk_thresholds": {
    "cpu_high": 90,
    "memory_high": 85,
    "error_rate_high": 50
  },
  "approval": {
    "channel": "dashboard",
    "timeout_medium_seconds": 300,
    "timeout_medium_default": "deny",
    "timeout_high_seconds": null
  },
  "llm": {
    "provider": "ollama",
    "model": "llama3:8b",
    "ollama_host": "http://localhost:11434",
    "temperature": 0.1
  }
}
```

#### `PATCH /agent/config`
Update agent configuration at runtime.

**Request body:** Partial config object (only fields to change).

---

### Playbooks

#### `GET /playbooks`
List all playbook entries.

**Query params:**
| Param | Type | Default | Description |
|---|---|---|---|
| `provider` | string | all | Filter by provider scope |
| `severity` | string | all | `LOW`, `MEDIUM`, `HIGH` |

**Response:**
```json
{
  "playbooks": [
    {
      "id": "mongodb_container_down",
      "name": "MongoDB container crash",
      "severity": "MEDIUM",
      "provider": null,
      "detection_type": "container_health",
      "file": "playbooks/docker_compose/mongodb.yaml"
    }
  ]
}
```

#### `GET /playbooks/{playbook_id}`
Get full playbook entry.

#### `POST /playbooks`
Add a new playbook entry.

**Request body:** Full playbook YAML (see [playbook-schema.md](playbook-schema.md)) as JSON.

#### `PUT /playbooks/{playbook_id}`
Update an existing playbook entry.

#### `DELETE /playbooks/{playbook_id}`
Remove a playbook entry.

---

### Approval

These endpoints power the dashboard chat window approval cards. When the agent raises a MEDIUM or HIGH risk incident, the dashboard subscribes to the `approval_requested` WebSocket event and renders an approval card. The card's Approve/Deny/Investigate buttons call these endpoints.

#### `GET /approval/pending`
List all incidents currently awaiting approval.

**Response:**
```json
{
  "pending": [
    {
      "incident_id": "inc_20260331_001",
      "title": "MongoDB container crash",
      "severity": "MEDIUM",
      "proposed_action": "Restart MongoDB container",
      "rollback_plan": "If MongoDB fails to start, check disk space and OOM logs.",
      "requested_at": "2026-03-31T09:45:15Z",
      "timeout_at": "2026-03-31T09:50:15Z",
      "timeout_default": "deny"
    }
  ]
}
```

#### `POST /approval/{incident_id}/approve`
Approve the proposed remediation for an incident.

**Request body:**
```json
{
  "approved_by": "operator"
}
```

**Response:** `{"status": "approved", "incident_id": "inc_20260331_001"}`

Triggers the Remediation Executor immediately. The WebSocket stream will emit `action_executed` and `incident_resolved` events as the fix progresses.

#### `POST /approval/{incident_id}/deny`
Deny the proposed remediation. The incident is escalated and marked as requiring manual intervention.

**Request body:**
```json
{
  "denied_by": "operator",
  "reason": "Investigating other potential cause first"
}
```

**Response:** `{"status": "denied", "incident_id": "inc_20260331_001"}`

#### `POST /approval/{incident_id}/investigate`
Request the agent's full reasoning — the agent returns additional diagnostic detail (log excerpts, metric trends, LLM reasoning chain) as a follow-up message in the chat window. Does not approve or deny.

**Response:** `{"status": "investigating", "incident_id": "inc_20260331_001"}`

---

### Webhooks (External Integrations)

#### `POST /webhooks/teams/events`
MS Teams Adaptive Card callback endpoint (Phase 9+). Handles button actions from Teams approval cards.

**Handled events:**
- Button click payload from Teams — includes `action` (`approve`, `deny`, `investigate`) and `incident_id`
- Verification of Teams webhook signature required

#### `POST /webhooks/generic`
Generic webhook for custom approval integrations (e.g., PagerDuty, custom tooling).

**Request body:**
```json
{
  "incident_id": "inc_20260331_001",
  "action": "approve",
  "user": "alice@example.com",
  "token": "webhook-auth-token"
}
```

---

### Chat / Agent Interaction

#### `GET /chat/{incident_id}`
Get the agent's conversational reasoning log for an incident.

**Response:**
```json
{
  "incident_id": "inc_20260331_001",
  "messages": [
    {
      "role": "agent",
      "timestamp": "2026-03-31T09:45:12Z",
      "content": "I detected that MongoDB is unreachable. The demo app is returning 500 errors on all database-dependent endpoints."
    },
    {
      "role": "agent",
      "timestamp": "2026-03-31T09:45:13Z",
      "type": "approval_card",
      "content": "Based on my playbook, this is a known issue — the MongoDB container has crashed. I'd like to restart the MongoDB container and verify replica set health.",
      "card": {
        "severity": "MEDIUM",
        "proposed_action": "Restart MongoDB container",
        "rollback_plan": "If MongoDB fails to start, check disk space and OOM logs.",
        "timeout_at": "2026-03-31T09:50:13Z",
        "timeout_default": "deny"
      }
    },
    {
      "role": "human",
      "timestamp": "2026-03-31T09:45:28Z",
      "content": "Approved"
    },
    {
      "role": "agent",
      "timestamp": "2026-03-31T09:45:55Z",
      "content": "MongoDB restarted successfully. Replica set is healthy. demo app is responding normally. Incident resolved in 47 seconds."
    }
  ]
}
```

Note: Messages with `"type": "approval_card"` include a `card` object. The dashboard renders these as interactive approval cards rather than plain text bubbles. Once resolved (approved/denied/timed out), the card renders in a resolved state showing the outcome.

#### `POST /chat`
Ask the agent a question about current system state (interactive mode).

**Request:**
```json
{
  "message": "What's the current memory usage on the demo app?"
}
```

**Response:**
```json
{
  "response": "The demo app is currently using 256MB of its 512MB limit (50%). Memory usage has been stable over the last 15 minutes.",
  "data": {
    "service": "demo-app",
    "memory_used_bytes": 268435456,
    "memory_limit_bytes": 536870912,
    "memory_percent": 50.0
  }
}
```

---

### WebSocket: Live Events

#### `WS /ws/events`
Real-time event stream for the dashboard.

**Event types:**
```json
{"type": "metric_update", "data": {"service": "demo-app", "cpu_percent": 45.2, ...}}
{"type": "anomaly_detected", "data": {"incident_id": "inc_...", "service": "mongodb", ...}}
{"type": "approval_requested", "data": {"incident_id": "inc_...", "severity": "MEDIUM", "card": {...}}}
{"type": "action_executed", "data": {"incident_id": "inc_...", "action": "restart", ...}}
{"type": "incident_resolved", "data": {"incident_id": "inc_...", "resolution_time": 47, ...}}
```

The dashboard subscribes to this stream on load. When `approval_requested` arrives, the dashboard renders the approval card in the chat window. This is the mechanism that drives the real-time feel of the approval flow without polling.

---

## Authentication (Post-MVP)

For the MVP, the API has no authentication. Post-MVP:

- **API keys** for programmatic access
- **Teams webhook verification** (HMAC signature) for webhook endpoints
- **JWT tokens** for dashboard login
- **RBAC** for approval permissions (who can approve HIGH risk actions)

---

## Error Format

All errors follow a consistent structure:

```json
{
  "error": {
    "code": "SERVICE_NOT_FOUND",
    "message": "Service 'postgres' not found in the current environment",
    "detail": "Available services: nginx, demo-app, mongodb, redis"
  }
}
```

HTTP status codes:
- `400` — Bad request (invalid params)
- `404` — Resource not found
- `409` — Conflict (e.g., agent already running, incident already approved)
- `500` — Internal server error
- `503` — Agent not ready / provider unavailable
