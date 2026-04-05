"""
Tool-calling agent for Prometheus, Grafana, and Loki.

Uses Ollama with tool schemas to autonomously query metrics and logs,
then reasons about the results to diagnose infrastructure issues.
"""

from __future__ import annotations

import POCs.env  # noqa: F401 — load .env

import json
import os
from dataclasses import dataclass, field

import httpx

from .tools import TOOL_SCHEMAS, execute_tool, ToolResult

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")

SYSTEM_PROMPT = """\
You are AutoOps AI, a DevOps observability agent with access to Prometheus, Grafana, and Loki.

Your capabilities:
- Query Prometheus metrics using PromQL (CPU, memory, request rates, error rates, etc.)
- Browse Grafana dashboards to understand what's being monitored
- Query Loki for application and infrastructure logs using LogQL
- Check scrape target health and active alerts

When investigating an issue:
1. Start by checking relevant metrics or targets
2. Look at trends over time if needed (range queries)
3. Check logs for error details
4. Correlate metrics with log events
5. Provide a clear diagnosis with evidence

Rules:
- Always ground your analysis in real data from the tools
- Use PromQL best practices (rate() for counters, avoid raw counters)
- When checking logs, use targeted LogQL filters to avoid noise
- State confidence level in your diagnosis
- Suggest next steps or remediation with risk levels
"""


@dataclass
class AgentStep:
    role: str
    content: str | None = None
    tool_calls: list[dict] | None = None
    tool_name: str | None = None
    tool_result: ToolResult | None = None


@dataclass
class AgentRun:
    user_message: str
    steps: list[AgentStep] = field(default_factory=list)
    final_response: str = ""
    tools_called: list[str] = field(default_factory=list)


async def health_check() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{OLLAMA_BASE}/api/tags")
            return resp.status_code == 200
    except httpx.ConnectError:
        return False


async def run_agent(user_message: str, max_iterations: int = 10) -> AgentRun:
    """Run the observability agent loop with tool calling."""
    run = AgentRun(user_message=user_message)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    for _ in range(max_iterations):
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{OLLAMA_BASE}/api/chat",
                json={
                    "model": MODEL,
                    "messages": messages,
                    "tools": TOOL_SCHEMAS,
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        msg = data["message"]
        tool_calls = msg.get("tool_calls")

        if tool_calls:
            step = AgentStep(role="assistant", content=msg.get("content"), tool_calls=tool_calls)
            run.steps.append(step)
            messages.append(msg)

            for tc in tool_calls:
                func = tc["function"]
                tool_name = func["name"]
                tool_args = func.get("arguments", {})

                result = await execute_tool(tool_name, tool_args)
                run.tools_called.append(tool_name)
                run.steps.append(AgentStep(role="tool", tool_name=tool_name, tool_result=result))

                messages.append({
                    "role": "tool",
                    "content": json.dumps(
                        {"success": result.success, "output": result.output, "error": result.error},
                        default=str,
                    ),
                })
        else:
            run.final_response = msg.get("content", "")
            run.steps.append(AgentStep(role="assistant", content=run.final_response))
            break

    return run
