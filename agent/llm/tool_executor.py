"""
Tool executor — bridges LLM tool calls to real provider / store methods.

Validation pipeline (inspired by claude-code ``query.ts``):
1. Check tool name exists in registry
2. Check permission deny-list (write tools blocked in chat)
3. Validate required arguments
4. Validate argument types against schema
5. Execute with timeout
6. Truncate large outputs (claude-code middle-elision pattern)
7. Return structured ``ToolResult`` (compact for LLM, rich for UI)
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from agent.llm.tools import TOOL_REGISTRY, ToolDefinition

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 2048  # Truncate tool output to fit 4B model context

# ── Permission deny-list (P1 #10) ─────────────────────────────────────────
# Tools that must NEVER be callable from the chat interface.
# Write / destructive actions go through the approval flow exclusively.
CHAT_DENY_LIST: frozenset[str] = frozenset({
    "restart_service",
    "scale_service",
    "exec_command",
    "stop_service",
    "start_service",
})

# Prefixes that are also denied (catches future namespaced write tools).
CHAT_DENY_PREFIXES: tuple[str, ...] = (
    "write_",
    "delete_",
    "destroy_",
    "drop_",
)

# JSON-schema type → Python types mapping for argument validation.
_SCHEMA_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def _is_denied(tool_name: str) -> bool:
    """Return True if a tool name is on the permission deny-list."""
    name_lower = tool_name.lower()
    if name_lower in CHAT_DENY_LIST:
        return True
    return any(name_lower.startswith(p) for p in CHAT_DENY_PREFIXES)


def _validate_arg_types(
    tool_def: ToolDefinition, arguments: dict[str, Any],
) -> str | None:
    """
    Validate argument types against the tool's JSON-schema ``properties``.

    Returns an error string if validation fails, else ``None``.
    """
    properties = tool_def.parameters.get("properties", {})
    errors: list[str] = []
    for arg_name, arg_value in arguments.items():
        prop = properties.get(arg_name)
        if not prop:
            continue  # extra args are tolerated
        expected_type = prop.get("type")
        if not expected_type:
            continue
        allowed_types = _SCHEMA_TYPE_MAP.get(expected_type)
        if allowed_types and not isinstance(arg_value, allowed_types):
            errors.append(
                f"{arg_name}: expected {expected_type}, got {type(arg_value).__name__}"
            )
    return "; ".join(errors) if errors else None


@dataclass(frozen=True)
class ToolResult:
    """Structured result from a tool execution."""
    tool: str
    success: bool
    output: Any
    error: str | None = None
    _raw_output: Any = field(default=None, repr=False)

    def to_json(self) -> str:
        """Compact serialization for the LLM ``tool`` role message (P1 #16)."""
        return json.dumps(
            {"success": self.success, "data": self.output, "error": self.error},
            default=str,
        )

    def to_rich_dict(self) -> dict[str, Any]:
        """Rich representation for the UI / chat history (P1 #16).

        Includes the full untruncated output so dashboards can display
        complete data even though the LLM only sees the compact version.
        """
        return {
            "tool": self.tool,
            "success": self.success,
            "output": self._raw_output if self._raw_output is not None else self.output,
            "error": self.error,
        }


def _truncate_output(text: str, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    """Truncate with middle-elision if output exceeds max_chars."""
    if len(text) <= max_chars:
        return text
    keep = max_chars // 2 - 20  # leave room for the elision notice
    removed = len(text) - keep * 2
    return f"{text[:keep]}\n... ({removed} chars truncated) ...\n{text[-keep:]}"


class ToolExecutor:
    """
    Dispatches LLM tool calls to real infrastructure methods.

    Only read-only tools are supported — write actions go through
    the approval flow exclusively.
    """

    def __init__(
        self,
        provider: Any = None,
        incident_store: Any = None,
    ):
        self._provider = provider
        self._incident_store = incident_store

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool call. Returns structured ToolResult (never raises)."""
        # 1. Permission deny-list — checked FIRST so write tools are blocked
        #    even if they don't exist in the registry (P1 #10).
        if _is_denied(tool_name):
            logger.warning("Denied tool call from chat: %s", tool_name)
            return ToolResult(
                tool=tool_name, success=False, output=None,
                error=f"Tool '{tool_name}' is not allowed in chat. Use the approval flow.",
            )

        # 2. Validate tool exists in registry
        tool_def = TOOL_REGISTRY.get(tool_name)
        if not tool_def:
            return ToolResult(
                tool=tool_name, success=False, output=None,
                error=f"Unknown tool: {tool_name}",
            )

        # 3. Validate required arguments
        required = tool_def.parameters.get("required", [])
        missing = [r for r in required if r not in arguments]
        if missing:
            return ToolResult(
                tool=tool_name, success=False, output=None,
                error=f"Missing required arguments: {', '.join(missing)}",
            )

        # 4. Validate argument types (P1 #9)
        type_err = _validate_arg_types(tool_def, arguments)
        if type_err:
            return ToolResult(
                tool=tool_name, success=False, output=None,
                error=f"Invalid argument types: {type_err}",
            )

        # 5. Dispatch with timeout
        try:
            timeout = tool_def.timeout_seconds or 5
            raw_result = await asyncio.wait_for(
                self._dispatch(tool_name, arguments),
                timeout=timeout,
            )
            # 6. Truncate large outputs for LLM, keep raw for UI (P1 #16)
            compact = raw_result
            if isinstance(raw_result, str) and len(raw_result) > MAX_OUTPUT_CHARS:
                compact = _truncate_output(raw_result)
            elif isinstance(raw_result, (dict, list)):
                serialized = json.dumps(raw_result, default=str)
                if len(serialized) > MAX_OUTPUT_CHARS:
                    compact = _truncate_output(serialized)
            return ToolResult(
                tool=tool_name, success=True,
                output=compact, _raw_output=raw_result,
            )

        except asyncio.TimeoutError:
            logger.warning("Tool '%s' timed out after %ds", tool_name, tool_def.timeout_seconds)
            return ToolResult(
                tool=tool_name, success=False, output=None,
                error=f"Tool timed out after {tool_def.timeout_seconds}s",
            )
        except Exception as e:
            logger.warning("Tool '%s' failed: %s", tool_name, e, exc_info=True)
            return ToolResult(
                tool=tool_name, success=False, output=None,
                error=str(e),
            )

    async def _dispatch(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Route tool call to the correct provider / store method."""
        if tool_name == "think":
            thought = args.get("thought", "")
            logger.info("LLM think: %s", thought[:200])
            return "Your thought has been logged."

        if tool_name == "list_services":
            return await self._list_services()

        if tool_name == "get_service_status":
            return await self._get_service_status(args["service_name"])

        if tool_name == "get_service_logs":
            return await self._get_service_logs(
                args["service_name"], args.get("lines", 50),
            )

        if tool_name == "get_service_metrics":
            return await self._get_service_metrics(args["service_name"])

        if tool_name == "check_service_health":
            return await self._check_service_health(args["service_name"])

        if tool_name == "get_active_incidents":
            return await self._get_active_incidents()

        if tool_name == "get_incident_history":
            return await self._get_incident_history(
                args["service_name"], args.get("limit", 5),
            )

        return {"error": f"No handler for tool: {tool_name}"}

    # ── Provider-backed tools ────────────────────────────────────────────

    async def _list_services(self) -> list[dict]:
        if not self._provider:
            return [{"error": "Infrastructure provider not available"}]
        services = await self._provider.list_services()
        return [
            {
                "name": s.name,
                "image": s.image,
                "labels": s.labels if hasattr(s, "labels") else {},
            }
            for s in services
        ]

    async def _get_service_status(self, service_name: str) -> dict:
        if not self._provider:
            return {"error": "Infrastructure provider not available"}
        status = await self._provider.get_service_status(service_name)
        return {
            "service": service_name,
            "state": status.state,
            "uptime_seconds": status.uptime_seconds if hasattr(status, "uptime_seconds") else None,
            "restart_count": status.restart_count if hasattr(status, "restart_count") else 0,
            "health": status.health if hasattr(status, "health") else "unknown",
        }

    async def _get_service_logs(self, service_name: str, lines: int) -> list[str]:
        if not self._provider:
            return ["Error: Infrastructure provider not available"]
        log_entries = await self._provider.get_logs(service_name, lines=lines)
        return [
            entry.message if hasattr(entry, "message") else str(entry)
            for entry in log_entries
        ]

    async def _get_service_metrics(self, service_name: str) -> dict:
        if not self._provider:
            return {"error": "Infrastructure provider not available"}
        metrics = await self._provider.get_metrics(service_name)
        return {
            "service": service_name,
            "cpu_percent": metrics.cpu_percent,
            "memory_percent": metrics.memory_percent,
            "memory_used_bytes": metrics.memory_used_bytes if hasattr(metrics, "memory_used_bytes") else None,
            "memory_limit_bytes": metrics.memory_limit_bytes if hasattr(metrics, "memory_limit_bytes") else None,
        }

    async def _check_service_health(self, service_name: str) -> dict:
        if not self._provider:
            return {"error": "Infrastructure provider not available"}
        result = await self._provider.health_check(service_name)
        return {
            "service": service_name,
            "healthy": result.healthy,
            "message": result.message if hasattr(result, "message") else "",
        }

    # ── Incident-store-backed tools ────────────────────────────────────────

    async def _get_active_incidents(self) -> list[dict]:
        if not self._incident_store:
            return [{"error": "Incident store not available"}]
        try:
            incidents = await self._incident_store.list_incidents(
                status="AWAITING_APPROVAL",
            )
            # Also include other active statuses
            for status in ("DETECTING", "DIAGNOSING", "APPROVED", "EXECUTING"):
                incidents += await self._incident_store.list_incidents(status=status)
            return [
                {
                    "incident_id": inc.incident_id,
                    "service": inc.service_name,
                    "type": inc.anomaly_type,
                    "severity": inc.severity,
                    "status": inc.status,
                    "summary": inc.diagnosis_summary,
                }
                for inc in incidents[:20]
            ]
        except Exception as e:
            return [{"error": f"Could not fetch incidents: {e}"}]

    async def _get_incident_history(self, service_name: str, limit: int) -> list[dict]:
        if not self._incident_store:
            return [{"error": "Incident store not available"}]
        try:
            incidents = await self._incident_store.list_incidents(
                service=service_name, limit=limit,
            )
            return [
                {
                    "incident_id": inc.incident_id,
                    "type": inc.anomaly_type,
                    "severity": inc.severity,
                    "status": inc.status,
                    "summary": inc.diagnosis_summary,
                    "detected_at": str(inc.detected_at) if hasattr(inc, "detected_at") else "",
                }
                for inc in incidents
            ]
        except Exception as e:
            return [{"error": f"Could not fetch incident history: {e}"}]
