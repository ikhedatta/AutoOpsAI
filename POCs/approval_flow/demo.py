"""
POC 7 Demo — Interactive Approval Flow

Validates:
  1. Adaptive Card building with rich incident details
  2. Approve/Deny/Investigate callback handling
  3. Timeout auto-deny behavior
  4. LOW risk auto-approval (no human needed)
  5. Outcome card generation after resolution

Prerequisites:
  - None (local simulation, no Teams required)

Run:
    uv run python -m POCs.approval_flow.demo
"""

import asyncio
import json
import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax

from .cards import build_approval_card, build_outcome_card, build_timeout_card
from .approval_router import (
    ApprovalRouter, ApprovalRequest, ApprovalAction,
)

console = Console()


# --- Simulated incidents ------------------------------------------------------

INCIDENTS = [
    {
        "title": "LOW risk — Redis cache full (auto-approve)",
        "request": ApprovalRequest(
            incident_id="INC-001",
            container_name="redis",
            severity="LOW",
            diagnosis="Redis memory usage at 95%. Auto-executing cache purge.",
            remediation_steps=[
                {"action": "redis_command", "command": "MEMORY PURGE"},
                {"action": "metric_check", "metric": "redis_memory_used_ratio", "expected": "< 0.60"},
            ],
            confidence=0.92,
        ),
        "simulate_action": None,  # Auto-approved
    },
    {
        "title": "MEDIUM risk — MongoDB down (user approves)",
        "request": ApprovalRequest(
            incident_id="INC-002",
            container_name="mongodb",
            severity="MEDIUM",
            diagnosis="MongoDB container has stopped running. Flask app returning 500 errors on all database-dependent endpoints.",
            remediation_steps=[
                {"action": "docker_restart", "target": "mongodb"},
                {"action": "health_check", "target": "mongodb", "check": "mongosh --eval 'rs.status()'"},
                {"action": "health_check", "target": "flask-app", "check": "curl -s http://localhost:5000/health"},
            ],
            rollback_plan="If MongoDB fails to start, check disk space and OOM logs. Collect logs and escalate.",
            confidence=0.88,
            timeout_seconds=10,  # Short timeout for demo
        ),
        "simulate_action": ApprovalAction.APPROVE,
        "simulate_delay": 2,
    },
    {
        "title": "HIGH risk — Nginx 502 (user denies)",
        "request": ApprovalRequest(
            incident_id="INC-003",
            container_name="nginx",
            severity="HIGH",
            diagnosis="Nginx returning 502 Bad Gateway at >10/min. Upstream Flask application may be crashed or unreachable.",
            remediation_steps=[
                {"action": "health_check", "target": "flask-app", "check": "curl -s http://flask-app:5000/health"},
                {"action": "docker_restart", "target": "flask-app"},
                {"action": "health_check", "target": "nginx", "check": "curl -s http://localhost:80/health"},
            ],
            rollback_plan="If Flask app won't start, check application logs for crash reason. Collect logs and escalate.",
            confidence=0.75,
            timeout_seconds=10,
        ),
        "simulate_action": ApprovalAction.DENY,
        "simulate_delay": 3,
    },
    {
        "title": "MEDIUM risk — CPU spike (timeout → auto-deny)",
        "request": ApprovalRequest(
            incident_id="INC-004",
            container_name="flask-app",
            severity="MEDIUM",
            diagnosis="Container CPU at 96% for over 2 minutes. Possible resource leak or runaway process.",
            remediation_steps=[
                {"action": "collect_diagnostics", "command": "docker exec flask-app top -bn1"},
                {"action": "docker_restart", "target": "flask-app"},
                {"action": "metric_check", "metric": "container_cpu_percent", "expected": "< 50%"},
            ],
            confidence=0.80,
            timeout_seconds=3,  # Very short for demo — will timeout
        ),
        "simulate_action": None,  # Let it timeout
    },
]


async def run_demo():
    console.print(Panel(
        "AutoOpsAI — POC 7: Interactive Approval Flow\n"
        "Tests: Adaptive Cards, approve/deny callbacks, timeout handling, auto-approve",
        style="bold cyan",
    ))

    router = ApprovalRouter()
    resolution_log: list[tuple[str, ApprovalAction, str]] = []

    # Register callback to track resolutions
    async def on_resolution(request: ApprovalRequest, action: ApprovalAction):
        latency = (request.resolved_at - request.created_at) if request.resolved_at else 0
        resolution_log.append((request.incident_id, action, f"{latency:.1f}s"))

    router.on_resolution(on_resolution)

    for incident in INCIDENTS:
        console.print(f"\n[bold yellow]━━━ {incident['title']} ━━━[/bold yellow]")

        request = incident["request"]

        # Build and show the adaptive card
        card = build_approval_card(
            incident_id=request.incident_id,
            container_name=request.container_name,
            severity=request.severity,
            diagnosis=request.diagnosis,
            remediation_steps=request.remediation_steps,
            rollback_plan=request.rollback_plan,
            confidence=request.confidence,
        )

        card_json = json.dumps(card, indent=2)
        console.print(Panel(
            Syntax(card_json, "json", theme="monokai", line_numbers=False),
            title=f"📋 Adaptive Card → Teams",
            border_style="blue",
            width=100,
        ))

        # Submit to router
        initial = await router.submit(request)

        if request.severity == "LOW":
            console.print(f"  [green]→ AUTO-APPROVED[/green] (LOW risk, no human needed)")
            # Show outcome card
            outcome = build_outcome_card(
                request.incident_id, "auto-approve", True,
                "LOW risk action auto-executed. Redis cache purged.",
            )
            console.print(f"  [dim]Outcome card generated ({len(json.dumps(outcome))} bytes)[/dim]")
            continue

        console.print(f"  [blue]→ Pending approval (timeout: {request.timeout_seconds}s)[/blue]")

        # Simulate user action or timeout
        simulate_action = incident.get("simulate_action")
        simulate_delay = incident.get("simulate_delay", 0)

        if simulate_action:
            # Simulate delayed user response
            async def delayed_resolve(rid, action, delay):
                await asyncio.sleep(delay)
                await router.resolve(rid, action, resolved_by="demo_user")

            resolve_task = asyncio.create_task(
                delayed_resolve(request.incident_id, simulate_action, simulate_delay)
            )
            # Wait for either resolution or timeout
            done, _ = await asyncio.wait(
                [resolve_task],
                timeout=request.timeout_seconds + 1,
            )
            if resolve_task in done:
                resolved = router.get_request(request.incident_id)
                console.print(
                    f"  [{'green' if simulate_action == ApprovalAction.APPROVE else 'red'}]"
                    f"→ User action: {simulate_action.value.upper()}[/] "
                    f"(after {simulate_delay}s)"
                )
                if simulate_action == ApprovalAction.APPROVE:
                    outcome = build_outcome_card(
                        request.incident_id, "approved", True,
                        "Remediation executed and verified successfully.",
                        duration_ms=simulate_delay * 1000 + 5000,
                    )
                else:
                    outcome = build_outcome_card(
                        request.incident_id, "denied", False,
                        "Action denied by operator. Incident logged for manual review.",
                    )
                console.print(f"  [dim]Outcome card generated ({len(json.dumps(outcome))} bytes)[/dim]")
        else:
            # Let it timeout
            console.print(f"  [dim]Waiting for timeout ({request.timeout_seconds}s)...[/dim]")
            await asyncio.sleep(request.timeout_seconds + 1)
            console.print(f"  [yellow]→ TIMED OUT[/yellow] — auto-denied")
            timeout_card = build_timeout_card(
                request.incident_id, request.severity, request.timeout_seconds,
            )
            console.print(f"  [dim]Timeout card generated ({len(json.dumps(timeout_card))} bytes)[/dim]")

    # Summary
    console.print(f"\n[bold]━━━ Approval Flow Summary ━━━[/bold]")
    table = Table(title="Resolutions")
    table.add_column("Incident", style="cyan")
    table.add_column("Action", style="white")
    table.add_column("Latency", style="yellow", justify="right")

    for iid, action, latency in resolution_log:
        action_style = {
            ApprovalAction.APPROVE: "green",
            ApprovalAction.DENY: "red",
            ApprovalAction.TIMEOUT: "yellow",
        }.get(action, "white")
        table.add_row(iid, f"[{action_style}]{action.value}[/{action_style}]", latency)

    console.print(table)

    # Stats
    pending = router.get_pending()
    resolved = router.get_resolved()
    console.print(f"\n  Pending: {len(pending)} | Resolved: {len(resolved)}")
    console.print(f"\n[green]✓ POC 7 complete — approval flow with cards, callbacks, and timeouts works[/green]")


if __name__ == "__main__":
    asyncio.run(run_demo())
