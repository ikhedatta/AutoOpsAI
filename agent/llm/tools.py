"""
Chat tool definitions for AutoOps AI.

Each tool is a frozen dataclass with an Ollama-compatible schema.
Only **read-only** tools are exposed in chat — write actions
(restart, scale, exec) go through the approval flow.

Patterns:
- Frozen dataclasses (claw-code ``tools.py``)
- Ollama-native ``tools`` parameter schemas (POC ``tool_execution/tools.py``)
- ThinkTool scratchpad (claude-code ``ThinkTool``)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any


@dataclass(frozen=True)
class ToolDefinition:
    """Immutable definition of a tool the LLM can invoke."""
    name: str
    description: str
    parameters: dict[str, Any]
    is_read_only: bool = True
    timeout_seconds: int = 5


# ═══════════════════════════════════════════════════════════════════════════
# Tool definitions
# ═══════════════════════════════════════════════════════════════════════════

LIST_SERVICES = ToolDefinition(
    name="list_services",
    description="List all managed services with their current status, image, and labels.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)

GET_SERVICE_STATUS = ToolDefinition(
    name="get_service_status",
    description=(
        "Get detailed status of a specific service: state (running/stopped/error), "
        "uptime, and restart count."
    ),
    parameters={
        "type": "object",
        "properties": {
            "service_name": {
                "type": "string",
                "description": "Name of the service to check.",
            },
        },
        "required": ["service_name"],
    },
)

GET_SERVICE_LOGS = ToolDefinition(
    name="get_service_logs",
    description="Retrieve recent log lines from a service. Use to investigate errors or recent events.",
    parameters={
        "type": "object",
        "properties": {
            "service_name": {
                "type": "string",
                "description": "Name of the service.",
            },
            "lines": {
                "type": "integer",
                "description": "Number of recent log lines to retrieve. Default 50.",
            },
        },
        "required": ["service_name"],
    },
    timeout_seconds=10,
)

GET_SERVICE_METRICS = ToolDefinition(
    name="get_service_metrics",
    description=(
        "Get current CPU, memory, and network I/O metrics for a service. "
        "Use for performance analysis."
    ),
    parameters={
        "type": "object",
        "properties": {
            "service_name": {
                "type": "string",
                "description": "Name of the service.",
            },
        },
        "required": ["service_name"],
    },
)

CHECK_SERVICE_HEALTH = ToolDefinition(
    name="check_service_health",
    description="Run a health check on a service. Returns healthy/unhealthy status.",
    parameters={
        "type": "object",
        "properties": {
            "service_name": {
                "type": "string",
                "description": "Name of the service to health-check.",
            },
        },
        "required": ["service_name"],
    },
)

GET_ACTIVE_INCIDENTS = ToolDefinition(
    name="get_active_incidents",
    description="Get all currently active (unresolved) incidents across all services.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)

GET_INCIDENT_HISTORY = ToolDefinition(
    name="get_incident_history",
    description="Get past incidents for a specific service. Useful for pattern analysis.",
    parameters={
        "type": "object",
        "properties": {
            "service_name": {
                "type": "string",
                "description": "Name of the service.",
            },
            "limit": {
                "type": "integer",
                "description": "Max number of past incidents to return. Default 5.",
            },
        },
        "required": ["service_name"],
    },
)

THINK = ToolDefinition(
    name="think",
    description=(
        "Use this tool to reason through complex questions step by step "
        "before providing your answer. The thought is logged but not shown "
        "to the user. Use for: correlating multiple metrics, analysing "
        "incident patterns, planning investigation steps."
    ),
    parameters={
        "type": "object",
        "properties": {
            "thought": {
                "type": "string",
                "description": "Your internal reasoning or analysis.",
            },
        },
        "required": ["thought"],
    },
    timeout_seconds=0,  # No execution needed
)


# ═══════════════════════════════════════════════════════════════════════════
# Observability tools (Prometheus, Loki, Grafana)
# ═══════════════════════════════════════════════════════════════════════════

PROMETHEUS_QUERY = ToolDefinition(
    name="prometheus_query",
    description=(
        "Execute an instant PromQL query against Prometheus. Returns current metric values. "
        "Use for checking error rates, CPU usage, memory, up status, etc. "
        "Example queries: 'up', 'node_cpu_seconds_total', 'rate(http_requests_total[5m])'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "promql": {
                "type": "string",
                "description": "PromQL expression to execute.",
            },
        },
        "required": ["promql"],
    },
    timeout_seconds=10,
)

PROMETHEUS_QUERY_RANGE = ToolDefinition(
    name="prometheus_query_range",
    description=(
        "Execute a range PromQL query — returns time-series data over a window. "
        "Use for trend analysis: CPU over time, memory growth, error rate spikes."
    ),
    parameters={
        "type": "object",
        "properties": {
            "promql": {
                "type": "string",
                "description": "PromQL expression.",
            },
            "duration_minutes": {
                "type": "integer",
                "description": "How far back to query, in minutes. Default 30.",
            },
            "step": {
                "type": "string",
                "description": "Query resolution step. Default '60s'.",
            },
        },
        "required": ["promql"],
    },
    timeout_seconds=15,
)

PROMETHEUS_GET_ALERTS = ToolDefinition(
    name="prometheus_get_alerts",
    description="Get all currently active/firing alerts from Prometheus.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    timeout_seconds=10,
)

PROMETHEUS_GET_TARGETS = ToolDefinition(
    name="prometheus_get_targets",
    description=(
        "Get all Prometheus scrape targets and their health (up/down). "
        "Use to check if monitoring targets are reachable."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    timeout_seconds=10,
)

LOKI_QUERY_LOGS = ToolDefinition(
    name="loki_query_logs",
    description=(
        "Query logs from Loki using LogQL. ALWAYS use this when asked about errors, warnings, "
        "or recent log activity. Examples: '{container=\"grafana\"}', "
        "'{container=\"nginx\"} |= \"error\"', '{job=\"varlogs\"} |~ \"(?i)error|warn|fatal\"'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "logql": {
                "type": "string",
                "description": "LogQL query expression.",
            },
            "limit": {
                "type": "integer",
                "description": "Max log lines to return. Default 50.",
            },
            "duration_minutes": {
                "type": "integer",
                "description": "How far back to search, in minutes. Default 60.",
            },
        },
        "required": ["logql"],
    },
    timeout_seconds=15,
)

LOKI_GET_LABELS = ToolDefinition(
    name="loki_get_labels",
    description=(
        "List all available log labels in Loki (e.g. 'container', 'job', 'host'). "
        "Use to discover what log streams are available before querying."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    timeout_seconds=10,
)

LOKI_GET_LABEL_VALUES = ToolDefinition(
    name="loki_get_label_values",
    description=(
        "Get all values for a specific Loki label. "
        "Example: label='container' returns all container names with logs."
    ),
    parameters={
        "type": "object",
        "properties": {
            "label": {
                "type": "string",
                "description": "Label name to get values for (e.g. 'container', 'job').",
            },
        },
        "required": ["label"],
    },
    timeout_seconds=10,
)

GRAFANA_LIST_DASHBOARDS = ToolDefinition(
    name="grafana_list_dashboards",
    description="List all Grafana dashboards. Use to find dashboards by name or tag.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional search query to filter dashboards.",
            },
        },
        "required": [],
    },
    timeout_seconds=10,
)

GRAFANA_GET_DATASOURCES = ToolDefinition(
    name="grafana_get_datasources",
    description="List all configured Grafana data sources (Prometheus, Loki, etc.).",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    timeout_seconds=10,
)


# ═══════════════════════════════════════════════════════════════════════════
# Registry and schema export
# ═══════════════════════════════════════════════════════════════════════════

ALL_CHAT_TOOLS: tuple[ToolDefinition, ...] = (
    LIST_SERVICES,
    GET_SERVICE_STATUS,
    GET_SERVICE_LOGS,
    GET_SERVICE_METRICS,
    CHECK_SERVICE_HEALTH,
    GET_ACTIVE_INCIDENTS,
    GET_INCIDENT_HISTORY,
    THINK,
    # Observability — Prometheus
    PROMETHEUS_QUERY,
    PROMETHEUS_QUERY_RANGE,
    PROMETHEUS_GET_ALERTS,
    PROMETHEUS_GET_TARGETS,
    # Observability — Loki (logs)
    LOKI_QUERY_LOGS,
    LOKI_GET_LABELS,
    LOKI_GET_LABEL_VALUES,
    # Observability — Grafana
    GRAFANA_LIST_DASHBOARDS,
    GRAFANA_GET_DATASOURCES,
)

TOOL_REGISTRY: dict[str, ToolDefinition] = {t.name: t for t in ALL_CHAT_TOOLS}


@lru_cache(maxsize=1)
def get_ollama_tool_schemas() -> list[dict[str, Any]]:
    """Return tool schemas in the format Ollama's ``tools`` parameter expects."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in ALL_CHAT_TOOLS
    ]
