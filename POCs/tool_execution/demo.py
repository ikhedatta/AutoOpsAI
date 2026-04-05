"""
POC 3 Demo — Tool Execution (Docker + MongoDB)

The model decides which tools to call based on the user's request,
executes them, and reasons about the results.

Prerequisites:
  - Ollama running with qwen3:4b (or change MODEL in agent.py)
  - Docker daemon running (for Docker tools)
  - MongoDB running on localhost:27017 (for MongoDB tools, optional)

Run:
    uv run python -m POCs.tool_execution.demo
"""

import asyncio
import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .agent import health_check, run_agent, AgentRun

console = Console()


SCENARIOS = [
    {
        "title": "List running containers",
        "message": "What Docker containers are currently running on this machine?",
    },
    {
        "title": "Investigate a specific container",
        "message": (
            "Can you check the status and resource usage of the 'ai_rag_platform' container? "
            "Show me its CPU and memory stats."
        ),
    },
    {
        "title": "MongoDB health check",
        "message": (
            "Check if MongoDB is running and healthy. "
            "Show me server status and list all databases."
        ),
    },
]


def print_run(run: AgentRun):
    """Pretty-print an agent run with tool calls and final response."""
    for step in run.steps:
        if step.role == "assistant" and step.tool_calls:
            for tc in step.tool_calls:
                func = tc["function"]
                args_str = ", ".join(f"{k}={v!r}" for k, v in func.get("arguments", {}).items())
                console.print(
                    f"  [yellow]→ calling[/yellow] [bold]{func['name']}[/bold]({args_str})"
                )
        elif step.role == "tool" and step.tool_result:
            r = step.tool_result
            if r.success:
                # Truncate long output
                out_str = str(r.output)
                if len(out_str) > 500:
                    out_str = out_str[:500] + "..."
                console.print(f"  [green]✓ {r.tool}[/green]: {out_str}")
            else:
                console.print(f"  [red]✗ {r.tool}[/red]: {r.error}")

    if run.final_response:
        console.print(
            Panel(run.final_response, title="🤖 AutoOps AI Response", border_style="green")
        )


async def run_demo():
    console.print(
        Panel(
            "AutoOpsAI — POC 3: Tool Execution (Docker + MongoDB)\n"
            "The model decides which tools to call and reasons about results",
            style="bold cyan",
        )
    )

    if not await health_check():
        console.print("[red]✗ Ollama is not running. Start it with: ollama serve[/red]")
        return
    console.print("[green]✓ Ollama is running[/green]\n")

    timing_rows = []

    for scenario in SCENARIOS:
        console.print(f"\n[bold yellow]━━━ {scenario['title']} ━━━[/bold yellow]")
        console.print(Panel(scenario["message"], title="👤 User", border_style="blue"))

        start = time.time()
        run = await run_agent(scenario["message"])
        elapsed = time.time() - start

        print_run(run)
        timing_rows.append((
            scenario["title"],
            ", ".join(run.tools_called) or "(none)",
            f"{int(elapsed * 1000)}ms",
        ))

    # Summary
    console.print()
    table = Table(title="Agent Run Summary")
    table.add_column("Scenario", style="cyan")
    table.add_column("Tools Called", style="yellow")
    table.add_column("Duration", style="green", justify="right")
    for scenario, tools, duration in timing_rows:
        table.add_row(scenario, tools, duration)
    console.print(table)

    console.print("\n[green]✓ POC 3 complete — tool-calling agent works end-to-end[/green]")


if __name__ == "__main__":
    asyncio.run(run_demo())
