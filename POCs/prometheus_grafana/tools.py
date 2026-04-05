"""
Tool definitions for Prometheus, Grafana, and Loki.
These schemas are sent to Ollama for tool-calling, and executors perform the real queries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .prometheus_client import PrometheusClient
from .grafana_client import GrafanaClient, LokiClient

# Shared client instances (configured at module level, overridable)
prometheus = PrometheusClient()
grafana = GrafanaClient()
loki = LokiClient()


@dataclass
class ToolResult:
    tool: str
    success: bool
    output: Any
    error: str | None = None


# --- Tool schemas for Ollama --------------------------------------------------

TOOL_SCHEMAS = [
    # Prometheus tools
    {
        "type": "function",
        "function": {
            "name": "prometheus_instant_query",
            "description": (
                "Execute a PromQL instant query to get the current value of a metric. "
                "Examples: 'up', 'container_cpu_usage_seconds_total', "
                "'rate(http_requests_total[5m])', 'node_memory_MemAvailable_bytes'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "PromQL query expression.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prometheus_range_query",
            "description": (
                "Execute a PromQL range query to get a time series over a window. "
                "Useful for trends, spikes, or historical data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "PromQL query expression.",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "How far back to look in minutes. Default 30.",
                    },
                    "step": {
                        "type": "string",
                        "description": "Resolution step (e.g., '15s', '60s', '5m'). Default '60s'.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prometheus_get_targets",
            "description": "List all Prometheus scrape targets and their health status (up/down).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prometheus_get_alerts",
            "description": "Get all active firing alerts from Prometheus alerting rules.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prometheus_list_metrics",
            "description": "List available metric names in Prometheus, optionally filtered by keyword.",
            "parameters": {
                "type": "object",
                "properties": {
                    "match": {
                        "type": "string",
                        "description": "Filter metrics containing this keyword (e.g., 'cpu', 'memory', 'http').",
                    }
                },
                "required": [],
            },
        },
    },
    # Grafana tools
    {
        "type": "function",
        "function": {
            "name": "grafana_list_dashboards",
            "description": "Search Grafana dashboards by name or keyword.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for dashboard name/title. Leave empty for all.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grafana_get_dashboard",
            "description": "Get a Grafana dashboard's panels and their PromQL queries by dashboard UID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "uid": {
                        "type": "string",
                        "description": "Dashboard UID (from grafana_list_dashboards).",
                    }
                },
                "required": ["uid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grafana_get_annotations",
            "description": "Get recent annotations/events from Grafana (alerts, deploys, incidents).",
            "parameters": {
                "type": "object",
                "properties": {
                    "dashboard_uid": {
                        "type": "string",
                        "description": "Filter by dashboard UID. Optional.",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "How far back to look. Default 60.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grafana_get_datasources",
            "description": "List all data sources configured in Grafana (Prometheus, Loki, etc.).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    # Loki (logs) tools
    {
        "type": "function",
        "function": {
            "name": "loki_query_logs",
            "description": (
                "Query logs from Loki using LogQL. "
                "Examples: '{job=\"flask-app\"} |= \"error\"', "
                "'{container=\"nginx\"} | json | status >= 500'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "LogQL query expression.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max log lines to return. Default 100.",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "How far back to look. Default 30.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loki_list_labels",
            "description": "List available log label values (e.g., all job names, container names).",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "description": "Label name to query values for. Default 'job'.",
                    }
                },
                "required": [],
            },
        },
    },
]


# --- Tool executors -----------------------------------------------------------

async def execute_prometheus_instant_query(query: str) -> ToolResult:
    r = await prometheus.instant_query(query)
    return ToolResult("prometheus_instant_query", r.success, r.data, r.error)


async def execute_prometheus_range_query(
    query: str, duration_minutes: int = 30, step: str = "60s"
) -> ToolResult:
    r = await prometheus.range_query(query, duration_minutes=duration_minutes, step=step)
    return ToolResult("prometheus_range_query", r.success, r.data, r.error)


async def execute_prometheus_get_targets() -> ToolResult:
    r = await prometheus.get_targets()
    return ToolResult("prometheus_get_targets", r.success, r.data, r.error)


async def execute_prometheus_get_alerts() -> ToolResult:
    r = await prometheus.get_alerts()
    return ToolResult("prometheus_get_alerts", r.success, r.data, r.error)


async def execute_prometheus_list_metrics(match: str | None = None) -> ToolResult:
    r = await prometheus.get_metric_names(match)
    return ToolResult("prometheus_list_metrics", r.success, r.data, r.error)


async def execute_grafana_list_dashboards(query: str | None = None) -> ToolResult:
    r = await grafana.list_dashboards(query)
    return ToolResult("grafana_list_dashboards", r.success, r.data, r.error)


async def execute_grafana_get_dashboard(uid: str) -> ToolResult:
    r = await grafana.get_dashboard(uid)
    return ToolResult("grafana_get_dashboard", r.success, r.data, r.error)


async def execute_grafana_get_annotations(
    dashboard_uid: str | None = None, duration_minutes: int = 60
) -> ToolResult:
    r = await grafana.get_annotations(dashboard_uid, duration_minutes)
    return ToolResult("grafana_get_annotations", r.success, r.data, r.error)


async def execute_grafana_get_datasources() -> ToolResult:
    r = await grafana.get_datasources()
    return ToolResult("grafana_get_datasources", r.success, r.data, r.error)


async def execute_loki_query_logs(
    query: str, limit: int = 100, duration_minutes: int = 30
) -> ToolResult:
    r = await loki.query_logs(query, limit, duration_minutes)
    return ToolResult("loki_query_logs", r.success, r.data, r.error)


async def execute_loki_list_labels(label: str = "job") -> ToolResult:
    r = await loki.get_label_values(label)
    return ToolResult("loki_list_labels", r.success, r.data, r.error)


# --- Dispatcher ---------------------------------------------------------------

TOOL_EXECUTORS = {
    "prometheus_instant_query": execute_prometheus_instant_query,
    "prometheus_range_query": execute_prometheus_range_query,
    "prometheus_get_targets": execute_prometheus_get_targets,
    "prometheus_get_alerts": execute_prometheus_get_alerts,
    "prometheus_list_metrics": execute_prometheus_list_metrics,
    "grafana_list_dashboards": execute_grafana_list_dashboards,
    "grafana_get_dashboard": execute_grafana_get_dashboard,
    "grafana_get_annotations": execute_grafana_get_annotations,
    "grafana_get_datasources": execute_grafana_get_datasources,
    "loki_query_logs": execute_loki_query_logs,
    "loki_list_labels": execute_loki_list_labels,
}


async def execute_tool(name: str, arguments: dict[str, Any]) -> ToolResult:
    """Execute a tool by name with the given arguments."""
    executor = TOOL_EXECUTORS.get(name)
    if not executor:
        return ToolResult(tool=name, success=False, output=None, error=f"Unknown tool: {name}")
    return await executor(**arguments)
