"""
POC 5 Demo — Playbook Matching & Knowledge Base

Validates:
  1. YAML playbook loading and parsing
  2. Pattern matching anomaly events against playbook entries
  3. LLM fallback for unknown/unmatched anomalies
  4. Structured JSON output reliability from Ollama

Prerequisites:
  - Ollama running with qwen3:4b (for LLM fallback scenarios)

Run:
    uv run python -m POCs.playbook_matching.demo
"""

import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .knowledge_base import KnowledgeBase, AnomalyEvent, MatchResult
from .llm_fallback import llm_diagnose, LLMDiagnosis

console = Console()

PLAYBOOKS_DIR = Path(__file__).parent / "playbooks"


# --- Test scenarios -----------------------------------------------------------

SCENARIOS: list[dict] = [
    # Scenario 1: Exact match — MongoDB container down
    {
        "title": "MongoDB container crash (exact match expected)",
        "event": AnomalyEvent(
            event_type="container_health",
            container_name="mongodb",
            status="exited",
            dependent_services=["flask-app"],
        ),
    },
    # Scenario 2: Exact match — Redis memory full
    {
        "title": "Redis memory at 95% (metric threshold match)",
        "event": AnomalyEvent(
            event_type="metric_threshold",
            metric_name="redis_memory_used_ratio",
            metric_value=0.95,
        ),
    },
    # Scenario 3: Exact match — Nginx 502 errors
    {
        "title": "Nginx 502 Bad Gateway (log pattern match)",
        "event": AnomalyEvent(
            event_type="log_pattern",
            container_name="nginx",
            log_pattern="502 Bad Gateway",
        ),
    },
    # Scenario 4: Exact match — High CPU
    {
        "title": "Container CPU spike at 96% (metric threshold match)",
        "event": AnomalyEvent(
            event_type="metric_threshold",
            metric_name="container_cpu_percent",
            metric_value=96.0,
        ),
    },
    # Scenario 5: Container restart loop
    {
        "title": "Container restart loop (restart count match)",
        "event": AnomalyEvent(
            event_type="container_health",
            container_name="flask-app",
            restart_count=5,
        ),
    },
    # Scenario 6: Fuzzy match — Redis container down (cross-type)
    {
        "title": "Redis container exited (fuzzy match expected)",
        "event": AnomalyEvent(
            event_type="container_health",
            container_name="redis",
            status="exited",
        ),
    },
    # Scenario 7: No match — unknown anomaly (LLM fallback)
    {
        "title": "Disk usage at 98% (NO playbook — LLM fallback)",
        "event": AnomalyEvent(
            event_type="metric_threshold",
            metric_name="host_disk_usage_percent",
            metric_value=98.2,
        ),
        "llm_fallback": True,
    },
    # Scenario 8: No match — unknown container issue (LLM fallback)
    {
        "title": "Celery worker OOMKilled (NO playbook — LLM fallback)",
        "event": AnomalyEvent(
            event_type="container_health",
            container_name="celery-worker",
            status="oomkilled",
        ),
        "llm_fallback": True,
    },
]


def _format_event(event: AnomalyEvent) -> str:
    """Format anomaly event as a human-readable description."""
    parts = [f"type={event.event_type}"]
    if event.container_name:
        parts.append(f"container={event.container_name}")
    if event.status:
        parts.append(f"status={event.status}")
    if event.restart_count:
        parts.append(f"restart_count={event.restart_count}")
    if event.metric_name:
        parts.append(f"metric={event.metric_name}")
    if event.metric_value:
        parts.append(f"value={event.metric_value}")
    if event.log_pattern:
        parts.append(f"pattern='{event.log_pattern}'")
    if event.dependent_services:
        parts.append(f"deps={event.dependent_services}")
    return ", ".join(parts)


def _format_anomaly_for_llm(event: AnomalyEvent) -> str:
    """Build a natural-language anomaly description for the LLM."""
    if event.event_type == "metric_threshold":
        return (
            f"Metric '{event.metric_name}' on container '{event.container_name or 'host'}' "
            f"has reached {event.metric_value}. This exceeds safe thresholds."
        )
    elif event.event_type == "container_health":
        desc = f"Container '{event.container_name}' has status '{event.status}'."
        if event.restart_count:
            desc += f" It has restarted {event.restart_count} times recently."
        return desc
    elif event.event_type == "log_pattern":
        return (
            f"Container '{event.container_name}' is producing log entries matching "
            f"pattern '{event.log_pattern}' at an elevated rate."
        )
    return f"Unknown anomaly: {_format_event(event)}"


def print_match_result(result: MatchResult):
    if result.matched and result.entry:
        entry = result.entry
        console.print(f"  [green]✓ MATCHED[/green] → [bold]{entry.id}[/bold] ({entry.name})")
        console.print(f"    Confidence: [cyan]{result.confidence:.0%}[/cyan]")
        console.print(f"    Reason: {result.match_reason}")
        console.print(f"    Severity: [yellow]{entry.severity}[/yellow]")
        console.print(f"    Diagnosis: {entry.diagnosis.strip()[:120]}...")
        steps = entry.remediation.get("steps", [])
        if steps:
            console.print(f"    Remediation: {len(steps)} step(s) — first: {steps[0].get('action', '?')}")
    else:
        console.print("  [red]✗ NO MATCH[/red] — no playbook entry fits this anomaly")


def print_llm_diagnosis(diagnosis: LLMDiagnosis | None):
    if diagnosis:
        console.print(f"  [green]✓ LLM diagnosis received[/green]")
        console.print(f"    Severity: [yellow]{diagnosis.severity}[/yellow]")
        console.print(f"    Confidence: [cyan]{diagnosis.confidence:.0%}[/cyan]")
        console.print(f"    Diagnosis: {diagnosis.diagnosis[:150]}")
        console.print(f"    Action: {diagnosis.action_type} → {diagnosis.action_target}")
        console.print(f"    Rollback: {diagnosis.rollback_plan[:100]}")
        console.print(f"    Verify: {diagnosis.verification_check[:100]}")
    else:
        console.print("  [red]✗ LLM failed to produce valid structured output[/red]")


def run_demo():
    console.print(Panel(
        "AutoOpsAI — POC 5: Playbook Matching & Knowledge Base\n"
        "Tests: YAML loading, pattern matching, LLM fallback for unknowns",
        style="bold cyan",
    ))

    # Load knowledge base
    kb = KnowledgeBase(PLAYBOOKS_DIR)
    console.print(f"[green]✓ Loaded {len(kb.entries)} playbook entries from {PLAYBOOKS_DIR}[/green]")

    # List loaded entries
    table = Table(title="Loaded Playbook Entries")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Severity", style="yellow")
    table.add_column("Detection Type", style="magenta")
    for entry in kb.entries:
        table.add_row(entry.id, entry.name, entry.severity, entry.detection_type)
    console.print(table)

    # Run scenarios
    results_summary = []

    for scenario in SCENARIOS:
        console.print(f"\n[bold yellow]━━━ {scenario['title']} ━━━[/bold yellow]")
        event = scenario["event"]
        console.print(f"  Event: {_format_event(event)}")

        start = time.time()
        result = kb.match(event)
        match_ms = (time.time() - start) * 1000

        print_match_result(result)

        llm_result = None
        llm_ms = 0.0
        use_llm = scenario.get("llm_fallback", False) and not result.matched

        if use_llm:
            console.print("  [blue]→ No playbook match — invoking LLM fallback...[/blue]")
            llm_start = time.time()
            anomaly_desc = _format_anomaly_for_llm(event)
            llm_result = llm_diagnose(anomaly_desc)
            llm_ms = (time.time() - llm_start) * 1000
            print_llm_diagnosis(llm_result)

        results_summary.append({
            "title": scenario["title"],
            "matched": result.matched,
            "entry_id": result.entry.id if result.entry else "-",
            "confidence": result.confidence,
            "llm_used": use_llm,
            "llm_ok": llm_result is not None if use_llm else None,
            "time_ms": match_ms + llm_ms,
        })

    # Summary table
    console.print()
    summary_table = Table(title="Matching Results Summary")
    summary_table.add_column("Scenario", style="cyan", max_width=45)
    summary_table.add_column("Matched", style="green")
    summary_table.add_column("Entry", style="white")
    summary_table.add_column("Confidence", style="yellow", justify="right")
    summary_table.add_column("LLM?", style="blue")
    summary_table.add_column("Time", style="magenta", justify="right")

    for r in results_summary:
        matched_str = "✓" if r["matched"] else "✗"
        llm_str = ""
        if r["llm_used"]:
            llm_str = "✓ OK" if r["llm_ok"] else "✗ FAIL"
        summary_table.add_row(
            r["title"],
            matched_str,
            r["entry_id"],
            f"{r['confidence']:.0%}" if r["matched"] else "-",
            llm_str,
            f"{r['time_ms']:.0f}ms",
        )
    console.print(summary_table)

    # Final verdict
    playbook_matches = sum(1 for r in results_summary if r["matched"])
    llm_attempts = sum(1 for r in results_summary if r["llm_used"])
    llm_successes = sum(1 for r in results_summary if r.get("llm_ok"))

    console.print(f"\n[green]✓ POC 5 complete[/green]")
    console.print(f"  Playbook matches: {playbook_matches}/{len(results_summary)}")
    if llm_attempts:
        console.print(f"  LLM fallback: {llm_successes}/{llm_attempts} produced valid JSON")


if __name__ == "__main__":
    run_demo()
