import sys
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from .ollama_client import OllamaClient, OllamaConnectionError, OllamaModelNotFoundError, OllamaTimeoutError
from .agents import DiagnosticAgent, RCAAgent, RemediationAgent, SummaryAgent

console = Console()

INCIDENT_DATA = """
ALERT RECEIVED: 2024-01-15 14:23:45 UTC
Container: autoops-api (ID: a3f8c9d2)
Memory Usage: 95.2% (1.9GB / 2GB limit)
CPU Usage: 87.3%
Response Time P99: 8234ms (normal: <200ms)
OOMKill Events: 3 (last 10 minutes)
MongoDB Connection Pool: 0/50 available (all exhausted)
MongoDB Slow Queries: 47 queries >5s in last 5 minutes
Active HTTP Connections: 1,847 (normal: <200)
Error Rate: 34.2% (5xx errors)
Pod Restarts: 3 (last 15 minutes)
"""

def run_agent(agent, user_input: str, title: str, color: str) -> tuple:
    console.print(f"\n[{color}]Running {agent.name}...[/{color}]")
    try:
        response = agent.run(user_input)
        console.print(Panel(
            response.content,
            title=f"[bold {color}]{title}[/bold {color}]",
            border_style=color,
            padding=(1, 2)
        ))
        return response.content, response.duration_ms
    except OllamaConnectionError as e:
        console.print(f"[red]ERROR: {e}[/red]")
        sys.exit(1)
    except OllamaModelNotFoundError as e:
        console.print(f"[red]ERROR: {e}[/red]\nRun: ollama pull gemma3")
        sys.exit(1)
    except OllamaTimeoutError as e:
        console.print(f"[yellow]TIMEOUT: {e}[/yellow]")
        sys.exit(1)

def main():
    console.print(Panel.fit(
        "[bold cyan]AutoOpsAI — POC 1: Multi-Agent Ollama Pipeline[/bold cyan]\n"
        "[dim]Demonstrating specialized agents with local Ollama (gemma3)[/dim]",
        border_style="cyan"
    ))

    client = OllamaClient()
    if not client.health_check():
        console.print("[red]Ollama is not running. Start it with: ollama serve[/red]")
        sys.exit(1)
    console.print("[green]✓ Ollama is running[/green]")

    console.print(Panel(INCIDENT_DATA.strip(), title="[bold red]🚨 Incident Alert[/bold red]", border_style="red"))

    timings = []

    diagnostic_agent = DiagnosticAgent(client)
    diagnosis, t1 = run_agent(diagnostic_agent, f"Analyze this incident:\n{INCIDENT_DATA}", "🔍 Diagnostic Agent", "yellow")
    timings.append(("DiagnosticAgent", t1))

    rca_agent = RCAAgent(client)
    rca, t2 = run_agent(rca_agent, f"Original incident:\n{INCIDENT_DATA}\n\nDiagnosis:\n{diagnosis}", "🧠 RCA Agent", "magenta")
    timings.append(("RCAAgent", t2))

    remediation_agent = RemediationAgent(client)
    remediation, t3 = run_agent(remediation_agent, f"Incident:\n{INCIDENT_DATA}\n\nRCA:\n{rca}", "🔧 Remediation Agent", "blue")
    timings.append(("RemediationAgent", t3))

    summary_agent = SummaryAgent(client)
    summary, t4 = run_agent(summary_agent, f"Incident:\n{INCIDENT_DATA}\n\nDiagnosis:\n{diagnosis}\n\nRCA:\n{rca}\n\nRemediation Plan:\n{remediation}", "📋 Summary Agent", "green")
    timings.append(("SummaryAgent", t4))

    table = Table(title="Agent Timing Summary", box=box.ROUNDED)
    table.add_column("Agent", style="cyan")
    table.add_column("Duration", style="yellow", justify="right")
    table.add_column("Model", style="dim")
    for agent_name, ms in timings:
        table.add_row(agent_name, f"{ms:.0f}ms", "gemma3:4b")
    console.print("\n", table)
    console.print("\n[bold green]✓ POC 1 complete — all 4 agents ran successfully[/bold green]\n")

if __name__ == "__main__":
    main()
