"""
POC 9 Demo — Remediation + Verification Loop

Validates:
  1. Execute a remediation action (docker restart)
  2. Wait and run verification checks (health check)
  3. Handle failure: retry once, then escalate
  4. Report success/failure with timing metrics (MTTR)
  5. Integration with playbook entries from POC 5

Prerequisites:
  - Docker daemon running
  - At least one running container to test with

Run:
    uv run python -m POCs.remediation_loop.demo
"""

import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .executor import RemediationExecutor, RemediationResult, ActionStatus

console = Console()


def print_result(result: RemediationResult):
    """Pretty-print a remediation result."""
    for step in result.steps:
        status_style = {
            ActionStatus.SUCCESS: "green",
            ActionStatus.FAILED: "red",
            ActionStatus.TIMEOUT: "yellow",
            ActionStatus.SKIPPED: "dim",
        }.get(step.status, "white")

        icon = "✓" if step.status == ActionStatus.SUCCESS else "✗"
        console.print(
            f"    [{status_style}]{icon} {step.action}[/{status_style}] → {step.target} "
            f"({step.duration_ms:.0f}ms)"
        )
        if step.output:
            console.print(f"      Output: {step.output[:200]}")
        if step.error:
            console.print(f"      [red]Error: {step.error}[/red]")

    if result.verified:
        console.print(f"  [green bold]✓ VERIFIED[/green bold] — remediation successful "
                       f"({result.total_duration_ms:.0f}ms)")
    elif result.escalated:
        console.print(f"  [red bold]⚠ ESCALATED[/red bold] — {result.escalation_message}")
    else:
        console.print(f"  [yellow]? UNVERIFIED[/yellow] — completed but verification inconclusive")


def run_demo():
    console.print(Panel(
        "AutoOpsAI — POC 9: Remediation + Verification Loop\n"
        "Tests: execute fix → verify → retry/escalate → report MTTR",
        style="bold cyan",
    ))

    executor = RemediationExecutor()

    # Find a running container to test with
    import docker
    client = docker.from_env()
    running = [c for c in client.containers.list() if c.status == "running"]

    if not running:
        console.print("[red]✗ No running containers found. Start some containers first.[/red]")
        return

    test_container = running[0].name
    console.print(f"[green]✓ Docker connected — using '{test_container}' for testing[/green]\n")

    scenarios = []

    # Scenario 1: Health check on a running container (should succeed)
    scenarios.append({
        "title": "Health check on running container",
        "playbook_id": "health_check_test",
        "container": test_container,
        "steps": [
            {"action": "health_check", "target": test_container, "timeout": "10s"},
        ],
    })

    # Scenario 2: Collect logs (should succeed)
    scenarios.append({
        "title": "Collect container logs",
        "playbook_id": "log_collection_test",
        "container": test_container,
        "steps": [
            {"action": "collect_logs", "target": test_container, "tail": 50},
        ],
    })

    # Scenario 3: Restart + verify (full loop)
    scenarios.append({
        "title": "Restart container + verify health",
        "playbook_id": "restart_verify_test",
        "container": test_container,
        "steps": [
            {"action": "docker_restart", "target": test_container, "timeout": "30s"},
            {"action": "health_check", "target": test_container, "timeout": "10s"},
        ],
    })

    # Scenario 4: Health check on nonexistent container (should fail + escalate)
    scenarios.append({
        "title": "Health check on nonexistent container (expect escalation)",
        "playbook_id": "fail_escalate_test",
        "container": "nonexistent_container_xyz",
        "steps": [
            {"action": "health_check", "target": "nonexistent_container_xyz", "timeout": "5s"},
            {"action": "escalate", "message": "Container not found. Manual investigation required."},
        ],
    })

    # Scenario 5: Metric check placeholder
    scenarios.append({
        "title": "Metric verification check (simulated)",
        "playbook_id": "metric_check_test",
        "container": test_container,
        "steps": [
            {"action": "metric_check", "metric": "container_cpu_percent", "expected": "< 50%", "timeout": "10s"},
        ],
    })

    # Scenario 6: Multi-step playbook from POC 5 schema
    scenarios.append({
        "title": "Full playbook: restart MongoDB → verify health → verify app",
        "playbook_id": "mongodb_container_down",
        "container": test_container,
        "steps": [
            {"action": "docker_restart", "target": test_container, "timeout": "30s"},
            {"action": "health_check", "target": test_container, "timeout": "15s"},
            {"action": "health_check", "target": test_container, "timeout": "10s"},
        ],
    })

    # Run all scenarios
    results_summary = []

    for scenario in scenarios:
        console.print(f"\n[bold yellow]━━━ {scenario['title']} ━━━[/bold yellow]")

        start = time.time()
        result = executor.execute_playbook(
            playbook_id=scenario["playbook_id"],
            container_name=scenario["container"],
            steps=scenario["steps"],
        )
        total_ms = (time.time() - start) * 1000

        print_result(result)

        results_summary.append({
            "title": scenario["title"],
            "playbook_id": scenario["playbook_id"],
            "verified": result.verified,
            "escalated": result.escalated,
            "steps": len(result.steps),
            "time_ms": total_ms,
        })

    # Summary
    console.print()
    table = Table(title="Remediation Results Summary")
    table.add_column("Scenario", style="cyan", max_width=50)
    table.add_column("Steps", justify="right")
    table.add_column("Verified", style="green")
    table.add_column("Escalated", style="red")
    table.add_column("MTTR", justify="right", style="yellow")

    for r in results_summary:
        table.add_row(
            r["title"],
            str(r["steps"]),
            "✓" if r["verified"] else "✗",
            "⚠" if r["escalated"] else "-",
            f"{r['time_ms']:.0f}ms",
        )
    console.print(table)

    verified_count = sum(1 for r in results_summary if r["verified"])
    console.print(f"\n[green]✓ POC 9 complete[/green] — {verified_count}/{len(results_summary)} scenarios verified")


if __name__ == "__main__":
    run_demo()
