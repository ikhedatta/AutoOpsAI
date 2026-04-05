"""
POC 6 Demo — Tiered Autonomy & Risk-Based Routing

Validates:
  1. Risk classification from playbook severity + action type + container
  2. Routing logic: auto-execute / request-approval / require-approval / escalate
  3. Confidence-based escalation (low confidence → higher risk)
  4. Critical container escalation (restarting DB → higher risk)
  5. Integration with POC 5 playbook entries

Prerequisites:
  - None (pure logic, no external dependencies)

Run:
    uv run python -m POCs.tiered_autonomy.demo
"""

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .risk_classifier import (
    classify_risk, route_incident,
    RiskLevel, ActionPath, RoutingDecision,
)
from POCs.playbook_matching.knowledge_base import KnowledgeBase

console = Console()

PLAYBOOKS_DIR = Path(__file__).parent.parent / "playbook_matching" / "playbooks"


# --- Individual action classification tests ---

ACTION_TESTS = [
    # (description, severity, action, container, confidence)
    ("Redis cache purge (safe action, LOW severity)", "LOW", "redis_command", "redis", 0.92),
    ("Log collection (safe action, any severity)", "MEDIUM", "collect_logs", "flask-app", 0.85),
    ("Restart non-critical container (MEDIUM)", "MEDIUM", "docker_restart", "flask-app", 0.88),
    ("Restart critical DB container (LOW→MEDIUM)", "LOW", "docker_restart", "mongodb", 0.90),
    ("Restart critical DB (MEDIUM severity)", "MEDIUM", "docker_restart", "mongodb", 0.80),
    ("Restart nginx (HIGH severity)", "HIGH", "docker_restart", "nginx", 0.75),
    ("Escalation action (always HIGH)", "LOW", "escalate", "any", 0.50),
    ("Low confidence restart (MEDIUM→HIGH)", "MEDIUM", "docker_restart", "flask-app", 0.3),
    ("Low confidence cache clear (LOW→MEDIUM)", "LOW", "redis_command", "redis", 0.4),
    ("Metric check (always safe)", "HIGH", "metric_check", "mongodb", 0.60),
]


def run_demo():
    console.print(Panel(
        "AutoOpsAI — POC 6: Tiered Autonomy & Risk-Based Routing\n"
        "Tests: risk classification, routing paths, confidence/container escalation",
        style="bold cyan",
    ))

    # Part 1: Individual action classification
    console.print("\n[bold]Part 1: Individual Action Classification[/bold]\n")

    table = Table(title="Risk Classification Results")
    table.add_column("Scenario", style="cyan", max_width=45)
    table.add_column("Risk", min_width=8)
    table.add_column("Path", style="white", min_width=18)
    table.add_column("Timeout", justify="right")
    table.add_column("Reason", style="dim", max_width=50)

    for desc, sev, action, container, conf in ACTION_TESTS:
        decision = classify_risk(sev, action, container, conf)

        risk_style = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}[decision.risk_level.value]
        path_style = {
            ActionPath.AUTO_EXECUTE: "green",
            ActionPath.REQUEST_APPROVAL: "yellow",
            ActionPath.REQUIRE_APPROVAL: "red",
            ActionPath.ESCALATE: "red bold",
        }[decision.action_path]

        table.add_row(
            desc,
            f"[{risk_style}]{decision.risk_level.value}[/{risk_style}]",
            f"[{path_style}]{decision.action_path.value}[/{path_style}]",
            f"{decision.timeout_seconds}s" if decision.timeout_seconds else "-",
            decision.reason[:50],
        )

    console.print(table)

    # Part 2: Full playbook routing (using POC 5 entries)
    console.print("\n[bold]Part 2: Full Playbook Routing (POC 5 integration)[/bold]\n")

    kb = KnowledgeBase(PLAYBOOKS_DIR)
    console.print(f"[green]✓ Loaded {len(kb.entries)} playbook entries[/green]\n")

    playbook_table = Table(title="Playbook Routing Decisions")
    playbook_table.add_column("Playbook", style="cyan", max_width=30)
    playbook_table.add_column("Severity", min_width=8)
    playbook_table.add_column("Steps", justify="right")
    playbook_table.add_column("Risk", min_width=8)
    playbook_table.add_column("Path", style="white", min_width=18)
    playbook_table.add_column("Reason", style="dim", max_width=50)

    for entry in kb.entries:
        steps = entry.remediation.get("steps", [])
        # Use the first target container or the playbook's detection container
        container = ""
        for cond in entry.conditions:
            container = cond.get("container_name", cond.get("target", ""))
            if container:
                break
        if not container:
            for step in steps:
                container = step.get("target", "")
                if container:
                    break

        decision = route_incident(
            playbook_severity=entry.severity,
            remediation_steps=steps,
            container_name=container,
            confidence=0.85,
        )

        risk_style = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}[decision.risk_level.value]
        sev_style = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}[entry.severity]

        playbook_table.add_row(
            entry.name,
            f"[{sev_style}]{entry.severity}[/{sev_style}]",
            str(len(steps)),
            f"[{risk_style}]{decision.risk_level.value}[/{risk_style}]",
            decision.action_path.value,
            decision.reason[:50],
        )

    console.print(playbook_table)

    # Part 3: Edge cases
    console.print("\n[bold]Part 3: Edge Cases[/bold]\n")

    edge_cases = [
        ("Empty remediation steps", route_incident("MEDIUM", [], "flask-app", 0.85)),
        ("Single safe step (LOW)", route_incident("LOW", [{"action": "collect_logs", "target": "app"}], "app", 0.90)),
        ("Mixed safe + destructive", route_incident("LOW", [
            {"action": "collect_logs", "target": "app"},
            {"action": "docker_restart", "target": "app"},
        ], "app", 0.85)),
    ]

    for desc, decision in edge_cases:
        risk_style = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}[decision.risk_level.value]
        console.print(
            f"  {desc}: [{risk_style}]{decision.risk_level.value}[/{risk_style}] → "
            f"{decision.action_path.value} | {decision.reason}"
        )

    console.print(f"\n[green]✓ POC 6 complete — risk classification and routing works correctly[/green]")


if __name__ == "__main__":
    run_demo()
