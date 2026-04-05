"""
POC 4 Demo — Prometheus, Grafana & Loki Observability Agent

The agent uses Ollama with tool-calling to query metrics, dashboards, and logs
to investigate infrastructure issues.

Prerequisites:
  - Ollama running with qwen3:4b
  - Prometheus on localhost:9090 (optional — agent handles unavailability)
  - Grafana on localhost:3000 (optional)
  - Loki on localhost:3100 (optional)

Run:
    uv run python -m POCs.prometheus_grafana.demo
"""

import asyncio
import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .agent import health_check, run_agent, AgentRun
from .prometheus_client import PrometheusClient
from .grafana_client import GrafanaClient, LokiClient

console = Console()


SCENARIOS = [
    {
        "title": "Infrastructure Health Overview",
        "message": (
            "Give me an overview of our infrastructure health. "
            "Check which Prometheus targets are up, look for any active alerts, "
            "and list the Grafana dashboards we have."
        ),
    },
    {
        "title": "CPU & Memory Investigation",
        "message": (
            "I'm seeing slowness in our services. Can you check the current "
            "CPU and memory usage across all containers? Look at metrics like "
            "container_cpu_usage_seconds_total and container_memory_usage_bytes. "
            "Also check if there are any related error logs."
        ),
    },
    {
        "title": "Error Rate Spike Analysis",
        "message": (
            "We got an alert about high error rates. Check the HTTP error rate "
            "(5xx responses) over the last 30 minutes. Also look at the nginx "
            "and flask-app logs for any errors. What's going on?"
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
                out_str = str(r.output)
                if len(out_str) > 400:
                    out_str = out_str[:400] + "..."
                console.print(f"  [green]✓ {r.tool}[/green]: {out_str}")
            else:
                console.print(f"  [red]✗ {r.tool}[/red]: {r.error}")

    if run.final_response:
        console.print(
            Panel(run.final_response, title="🤖 AutoOps AI Response", border_style="green")
        )


async def check_services():
    """Check which observability services are available."""
    prom = PrometheusClient()
    graf = GrafanaClient()
    lok = LokiClient()

    prom_ok = await prom.health_check()
    graf_ok = await graf.health_check()
    loki_ok = await lok.health_check()

    table = Table(title="Service Status")
    table.add_column("Service", style="cyan")
    table.add_column("URL", style="dim")
    table.add_column("Status")

    table.add_row("Prometheus", "localhost:9090", "[green]✓ up[/green]" if prom_ok else "[red]✗ down[/red]")
    table.add_row("Grafana", "localhost:3000", "[green]✓ up[/green]" if graf_ok else "[red]✗ down[/red]")
    table.add_row("Loki", "localhost:3100", "[green]✓ up[/green]" if loki_ok else "[red]✗ down[/red]")
    console.print(table)

    if not any([prom_ok, graf_ok, loki_ok]):
        console.print(
            "\n[yellow]Note: No observability services are running locally. "
            "The agent will still demonstrate tool selection and error handling. "
            "For full functionality, start services with the docker-compose below.[/yellow]"
        )
    console.print()
    return prom_ok, graf_ok, loki_ok


async def run_demo():
    console.print(
        Panel(
            "AutoOpsAI — POC 4: Prometheus, Grafana & Loki Observability Agent\n"
            "The model queries metrics, dashboards, and logs to investigate issues",
            style="bold cyan",
        )
    )

    if not await health_check():
        console.print("[red]✗ Ollama is not running. Start it with: ollama serve[/red]")
        return
    console.print("[green]✓ Ollama is running[/green]\n")

    await check_services()

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

    console.print("\n[green]✓ POC 4 complete — observability agent works end-to-end[/green]")
    console.print(
        "[dim]To test with real services, start the observability stack:\n"
        "  docker compose -f POCs/prometheus_grafana/docker-compose.yml up -d[/dim]"
    )


if __name__ == "__main__":
    asyncio.run(run_demo())
