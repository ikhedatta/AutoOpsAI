"""
Tool-calling agent that uses Ollama to decide which tools to invoke.

The agent sends tool schemas to Ollama via the tools parameter.
When the model returns tool_calls, we execute them and feed results back.
This loop continues until the model produces a final text response.
"""

from __future__ import annotations

import POCs.env  # noqa: F401 — load .env

import json
import os
from dataclasses import dataclass, field

import httpx

from .tools import TOOL_SCHEMAS, execute_tool, ToolResult

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")  # Good tool-calling support

SYSTEM_PROMPT = """\
You are AutoOps AI, a DevOps operations agent with access to Docker and MongoDB tools.

You can inspect infrastructure, diagnose issues, and take remediation actions.

When a user asks about infrastructure:
1. Use the available tools to gather real data
2. Analyze the results
3. Provide a clear diagnosis and recommendation

Rules:
- Always gather data before making claims
- State risk levels for any remediation actions
- Explain your reasoning concisely
- For destructive actions (restart, etc.), explain what you're about to do first
"""


@dataclass
class AgentStep:
    """One step in the agent's reasoning loop."""
    role: str  # "assistant" or "tool"
    content: str | None = None
    tool_calls: list[dict] | None = None
    tool_name: str | None = None
    tool_result: ToolResult | None = None


@dataclass
class AgentRun:
    """Complete record of an agent run."""
    user_message: str
    steps: list[AgentStep] = field(default_factory=list)
    final_response: str = ""
    tools_called: list[str] = field(default_factory=list)


async def health_check() -> bool:
    """Check if Ollama is reachable."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{OLLAMA_BASE}/api/tags")
            return resp.status_code == 200
    except httpx.ConnectError:
        return False


async def run_agent(user_message: str, max_iterations: int = 10) -> AgentRun:
    """
    Run the tool-calling agent loop.

    1. Send user message + tool schemas to Ollama
    2. If model returns tool_calls → execute tools, append results, repeat
    3. If model returns text content → done
    """
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
            # Model wants to call tools
            step = AgentStep(
                role="assistant",
                content=msg.get("content"),
                tool_calls=tool_calls,
            )
            run.steps.append(step)

            # Add assistant message to history
            messages.append(msg)

            # Execute each tool call and feed results back
            for tc in tool_calls:
                func = tc["function"]
                tool_name = func["name"]
                tool_args = func.get("arguments", {})

                result = execute_tool(tool_name, tool_args)
                run.tools_called.append(tool_name)

                tool_step = AgentStep(
                    role="tool",
                    tool_name=tool_name,
                    tool_result=result,
                )
                run.steps.append(tool_step)

                # Add tool result to message history
                messages.append({
                    "role": "tool",
                    "content": json.dumps(
                        {"success": result.success, "output": result.output, "error": result.error},
                        default=str,
                    ),
                })
        else:
            # Model produced a final text response
            run.final_response = msg.get("content", "")
            run.steps.append(AgentStep(role="assistant", content=run.final_response))
            break

    return run
