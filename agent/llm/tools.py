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
