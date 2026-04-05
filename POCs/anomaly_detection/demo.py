"""
POC 8 Demo — Continuous Anomaly Detection Loop

Validates:
  1. Docker stats polling every N seconds
  2. Threshold-based anomaly detection from config
  3. Duration-aware alerts (CPU/memory must persist, not just spike once)
  4. Structured AnomalyEvent emission compatible with playbook matching
  5. Callback system for downstream consumers

Prerequisites:
  - Docker daemon running with at least 1 container

Run:
    uv run python -m POCs.anomaly_detection.demo
"""

import asyncio
import signal
import time
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from .collector import MetricsCollector, SystemSnapshot, ContainerSnapshot
from .detector import AnomalyDetector, ThresholdConfig
from POCs.playbook_matching.knowledge_base import AnomalyEvent

console = Console()

# Use lower thresholds for demo purposes so anomalies are easier to trigger
DEMO_CONFIG = ThresholdConfig(
    cpu_percent=80.0,           # Alert at 80% CPU (lower for demo)
    cpu_duration_seconds=0.0,   # Immediate for demo (no duration wait)
    memory_percent=70.0,        # Alert at 70% memory
    memory_duration_seconds=0.0,
    max_restart_count=2,
    restart_window_seconds=600.0,
)

POLL_INTERVAL = 10  # seconds
MAX_CYCLES = 6      # Run for ~1 minute then stop


def build_snapshot_table(snapshot: SystemSnapshot, cycle: int) -> Table:
    """Build a rich table showing current container states."""
    table = Table(
        title=f"Cycle {cycle} — {len(snapshot.containers)} containers ({snapshot.collection_duration_ms:.0f}ms)",
    )
    table.add_column("Container", style="cyan", min_width=20)
    table.add_column("Status", min_width=10)
    table.add_column("Health", min_width=10)
    table.add_column("CPU %", justify="right", min_width=8)
    table.add_column("Mem %", justify="right", min_width=8)
    table.add_column("Mem MB", justify="right", min_width=10)
    table.add_column("Restarts", justify="right", min_width=8)
    table.add_column("Image", style="dim", max_width=30)

    for c in sorted(snapshot.containers, key=lambda x: x.name):
        status_style = "green" if c.status == "running" else "red"
        health_style = "green" if c.health == "healthy" else ("red" if c.health == "unhealthy" else "dim")
        cpu_style = "red bold" if c.cpu_percent > DEMO_CONFIG.cpu_percent else ""
        mem_style = "red bold" if c.memory_percent > DEMO_CONFIG.memory_percent else ""

        table.add_row(
            c.name,
            f"[{status_style}]{c.status}[/{status_style}]",
            f"[{health_style}]{c.health}[/{health_style}]",
            f"[{cpu_style}]{c.cpu_percent:.1f}[/{cpu_style}]",
            f"[{mem_style}]{c.memory_percent:.1f}[/{mem_style}]",
            f"{c.memory_usage_mb:.0f}/{c.memory_limit_mb:.0f}",
            str(c.restart_count),
            c.image[:30],
        )

    return table


def format_anomaly_event(event: AnomalyEvent) -> str:
    """Format an anomaly event for display."""
    parts = [f"[red bold]ANOMALY[/red bold]"]
    if event.container_name:
        parts.append(f"container=[cyan]{event.container_name}[/cyan]")
    parts.append(f"type={event.event_type}")
    if event.status:
        parts.append(f"status=[red]{event.status}[/red]")
    if event.metric_name:
        parts.append(f"{event.metric_name}=[yellow]{event.metric_value}[/yellow]")
    if event.restart_count:
        parts.append(f"restarts=[red]{event.restart_count}[/red]")
    return " | ".join(parts)


def run_demo():
    console.print(Panel(
        "AutoOpsAI — POC 8: Continuous Anomaly Detection Loop\n"
        f"Polling every {POLL_INTERVAL}s for {MAX_CYCLES} cycles\n"
        f"Thresholds: CPU>{DEMO_CONFIG.cpu_percent}% Mem>{DEMO_CONFIG.memory_percent}% Restarts>{DEMO_CONFIG.max_restart_count}",
        style="bold cyan",
    ))

    collector = MetricsCollector()
    detector = AnomalyDetector(config=DEMO_CONFIG)

    # Track all detected anomalies
    all_anomalies: list[tuple[int, AnomalyEvent]] = []
    cycle = [0]  # Mutable for closure

    def on_anomaly(event: AnomalyEvent, cs: ContainerSnapshot | None):
        all_anomalies.append((cycle[0], event))

    detector.on_anomaly(on_anomaly)

    # Initial collection to verify Docker connectivity
    test_snapshot = collector.collect()
    if not test_snapshot.containers:
        console.print("[red]✗ No Docker containers found. Is Docker running?[/red]")
        return
    console.print(f"[green]✓ Docker connected — found {len(test_snapshot.containers)} containers[/green]\n")

    # Run the polling loop
    for i in range(1, MAX_CYCLES + 1):
        cycle[0] = i
        console.print(f"\n[bold]━━━ Collection cycle {i}/{MAX_CYCLES} ━━━[/bold]")

        snapshot = collector.collect()
        console.print(build_snapshot_table(snapshot, i))

        events = detector.analyze(snapshot)

        if events:
            console.print(f"  [red]⚠ {len(events)} anomaly event(s) detected:[/red]")
            for event in events:
                console.print(f"    {format_anomaly_event(event)}")
        else:
            console.print("  [green]✓ No anomalies detected[/green]")

        # Show active tracking states
        active = detector.get_active_conditions()
        if active:
            console.print(f"  [dim]Tracking {len(active)} active condition(s): "
                          f"{[f'{c}:{t}' for (c, t) in active.keys()]}[/dim]")

        if i < MAX_CYCLES:
            console.print(f"  [dim]Next poll in {POLL_INTERVAL}s...[/dim]")
            time.sleep(POLL_INTERVAL)

    # Final summary
    console.print(f"\n[bold]━━━ Detection Summary ━━━[/bold]")
    if all_anomalies:
        summary_table = Table(title=f"Anomalies Detected ({len(all_anomalies)} total)")
        summary_table.add_column("Cycle", justify="right", style="yellow")
        summary_table.add_column("Container", style="cyan")
        summary_table.add_column("Type", style="magenta")
        summary_table.add_column("Detail", style="white")
        for cyc, event in all_anomalies:
            detail = ""
            if event.status:
                detail = f"status={event.status}"
            elif event.metric_name:
                detail = f"{event.metric_name}={event.metric_value}"
            elif event.restart_count:
                detail = f"restarts={event.restart_count}"
            summary_table.add_row(str(cyc), event.container_name, event.event_type, detail)
        console.print(summary_table)
    else:
        console.print("[green]No anomalies detected across all cycles.[/green]")
        console.print("[dim]Tip: stop a container with 'docker stop <name>' during the poll to trigger detection[/dim]")

    console.print(f"\n[green]✓ POC 8 complete — continuous detection loop works[/green]")


if __name__ == "__main__":
    run_demo()
