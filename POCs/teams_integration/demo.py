"""
POC 2 Demo — Teams Bot (local simulation)

Simulates a Teams-like conversation with the Ollama DevOps assistant.
No Teams registration needed — tests the bot logic directly.

Run:
    uv run python -m POCs.teams_integration.demo
"""

import asyncio
import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import ollama_bot

console = Console()


SAMPLE_CONVERSATIONS = [
    {
        "title": "Incident Investigation",
        "messages": [
            "Our MongoDB container just went down. The Flask app is throwing 500s. "
            "Here are the metrics:\n"
            "- mongodb container status: exited (OOMKilled)\n"
            "- flask-app error rate: 67%\n"
            "- flask-app response time p99: 12000ms\n"
            "- active connections: 342\n"
            "What's happening and what should we do?",
        ],
    },
    {
        "title": "Quick Health Check",
        "messages": [
            "Redis memory usage is at 92%. Is this something to worry about?",
        ],
    },
    {
        "title": "Multi-turn Conversation",
        "messages": [
            "We're seeing intermittent 502 errors from nginx. About 15 per minute. "
            "The upstream Flask app seems healthy when I curl it directly.",
            "Could this be related to the connection pool? We recently bumped "
            "max_connections from 100 to 500 in our nginx config.",
        ],
    },
]


async def run_demo():
    console.print(
        Panel(
            "AutoOpsAI — POC 2: Teams Bot Integration (Local Simulation)\n"
            "Demonstrating conversational DevOps assistant via local Ollama",
            style="bold cyan",
        )
    )

    # Health check
    if not await ollama_bot.health_check():
        console.print("[red]✗ Ollama is not running. Start it with: ollama serve[/red]")
        return
    console.print("[green]✓ Ollama is running[/green]\n")

    timing_rows = []

    for conv in SAMPLE_CONVERSATIONS:
        console.print(f"\n[bold yellow]━━━ {conv['title']} ━━━[/bold yellow]")
        history: list[dict] = []

        for msg in conv["messages"]:
            console.print(Panel(msg, title="👤 User (Teams)", border_style="blue"))

            start = time.time()
            reply = await ollama_bot.chat(msg, history)
            elapsed = time.time() - start

            history.append({"role": "user", "content": msg})
            history.append({"role": "assistant", "content": reply})

            console.print(
                Panel(reply, title="🤖 AutoOps AI", border_style="green")
            )

            timing_rows.append((conv["title"], f"{int(elapsed * 1000)}ms"))

    # Timing summary
    console.print()
    table = Table(title="Response Timing Summary")
    table.add_column("Scenario", style="cyan")
    table.add_column("Duration", style="green", justify="right")
    for scenario, duration in timing_rows:
        table.add_row(scenario, duration)
    console.print(table)

    console.print("\n[green]✓ POC 2 complete — Teams bot logic works end-to-end[/green]")
    console.print(
        "[dim]To deploy to actual Teams:\n"
        "  1. Register a bot in Azure Bot Service\n"
        "  2. Set TEAMS_APP_ID and TEAMS_APP_PASSWORD env vars\n"
        "  3. Run: uv run python -m POCs.teams_integration.teams_app\n"
        "  4. Expose port 3978 via ngrok or dev tunnel\n"
        "  5. Configure messaging endpoint in Azure Bot → Settings[/dim]"
    )


if __name__ == "__main__":
    asyncio.run(run_demo())
