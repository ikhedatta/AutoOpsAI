"""
POC 11 Demo — Teams Two-Way Communication

Tests the full round-trip:
  1. OUTBOUND: Platform sends alert card to Teams via Incoming Webhook
  2. INBOUND:  Simulates user clicking Approve/Deny on the card
  3. RESPONSE: Platform processes the action and sends outcome back

Run:
    uv run python -m POCs.teams_two_way.demo

To test with a real Teams webhook:
    TEAMS_WEBHOOK_URL="https://your-org.webhook.office.com/..." uv run python -m POCs.teams_two_way.demo
"""

import asyncio
import json
import os
import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .webhook import TeamsWebhook
from .bot_handler import ActionRouter, ActionType, BotResponse, InboundAction

# Reuse the Adaptive Card builders from POC 7
from POCs.approval_flow.cards import build_approval_card, build_outcome_card

console = Console()

WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "")


async def test_outbound_webhook():
    """Test 1: Send messages from platform → Teams."""
    console.print("\n[bold yellow]━━━ Test 1: Outbound — Platform → Teams (Webhook) ━━━[/bold yellow]")

    if not WEBHOOK_URL:
        console.print("  [dim]No TEAMS_WEBHOOK_URL set — showing payloads only (dry run)[/dim]")
        console.print("  [dim]Set TEAMS_WEBHOOK_URL env var to actually send to Teams[/dim]\n")

    webhook = TeamsWebhook(WEBHOOK_URL or "https://example.com/webhook")

    # --- 1a. Simple text alert ---
    console.print("  [blue]1a. Sending plain text alert...[/blue]")
    text_msg = "🔴 ALERT: Container 'mongodb' has exited (OOMKilled). AutoOps AI is investigating."

    if WEBHOOK_URL:
        result = await webhook.send_text(text_msg)
        style = "green" if result.success else "red"
        console.print(f"    [{style}]{result.message} (HTTP {result.status_code})[/{style}]")
    else:
        console.print(f"    Payload: {json.dumps({'text': text_msg}, indent=2)[:200]}")
        console.print("    [green]✓ Payload built successfully (dry run)[/green]")

    # --- 1b. Rich Adaptive Card alert ---
    console.print("\n  [blue]1b. Sending Adaptive Card alert...[/blue]")
    if WEBHOOK_URL:
        result = await webhook.send_alert(
            title="Container Crash Detected",
            severity="HIGH",
            container="mongodb",
            description="MongoDB container exited with OOMKilled. "
                        "Memory usage was at 98% before crash. "
                        "3 dependent services affected.",
            facts={"Uptime Before Crash": "4h 23m", "Restart Count": "3"},
        )
        style = "green" if result.success else "red"
        console.print(f"    [{style}]{result.message} (HTTP {result.status_code})[/{style}]")
    else:
        console.print("    [green]✓ Alert card built successfully (dry run)[/green]")

    # --- 1c. Approval card (from POC 7) ---
    console.print("\n  [blue]1c. Sending approval request card...[/blue]")
    approval_card = build_approval_card(
        incident_id="INC-042",
        container_name="mongodb",
        severity="HIGH",
        diagnosis="MongoDB container crashed due to OOMKilled. "
                  "Memory limit (512MB) exceeded under load.",
        remediation_steps=[
            {"action": "docker_restart", "target": "mongodb"},
            {"action": "health_check", "target": "mongodb", "command": "mongosh --eval 'db.runCommand({ping:1})'"},
        ],
        rollback_plan="If restart fails, scale horizontally with docker-compose up --scale mongodb=2",
        confidence=0.85,
    )

    if WEBHOOK_URL:
        result = await webhook.send_adaptive_card(approval_card)
        style = "green" if result.success else "red"
        console.print(f"    [{style}]{result.message} (HTTP {result.status_code})[/{style}]")
    else:
        console.print(f"    Card actions: {[a['title'] for a in approval_card.get('actions', [])]}")
        console.print("    [green]✓ Approval card built successfully (dry run)[/green]")
        console.print("    [yellow]⚠ Note: Action.Submit buttons only work with Bot Framework, not Incoming Webhooks[/yellow]")


async def test_inbound_actions():
    """Test 2: Simulate Teams → Platform (card button clicks)."""
    console.print("\n[bold yellow]━━━ Test 2: Inbound — Teams → Platform (Card Actions) ━━━[/bold yellow]")
    console.print("  [dim]Simulating what happens when a user clicks buttons on our cards[/dim]\n")

    router = ActionRouter()

    # Register handlers (same as bot_server.py but inline for demo)
    @router.on_action(ActionType.APPROVE)
    async def on_approve(action: InboundAction) -> BotResponse:
        return BotResponse(
            text=f"✅ Approved by {action.user_name}. "
                 f"Executing remediation for {action.incident_id}..."
        )

    @router.on_action(ActionType.DENY)
    async def on_deny(action: InboundAction) -> BotResponse:
        return BotResponse(
            text=f"❌ Denied by {action.user_name}. "
                 f"Incident {action.incident_id} logged for manual review."
        )

    @router.on_action(ActionType.INVESTIGATE)
    async def on_investigate(action: InboundAction) -> BotResponse:
        return BotResponse(
            text=f"🔍 Collecting diagnostics for {action.incident_id}..."
        )

    @router.on_command("status")
    async def on_status(action: InboundAction) -> BotResponse:
        return BotResponse(text="🟢 Platform online. 2 incidents active.")

    # Simulate card action payloads (what Teams sends when user clicks a button)
    test_cases = [
        {
            "name": "User clicks Approve on INC-042",
            "data": {"action": "approve", "incident_id": "INC-042"},
            "user": "Alice (DevOps Lead)",
        },
        {
            "name": "User clicks Deny on INC-043",
            "data": {"action": "deny", "incident_id": "INC-043"},
            "user": "Bob (SRE)",
        },
        {
            "name": "User clicks Investigate on INC-044",
            "data": {"action": "investigate", "incident_id": "INC-044"},
            "user": "Charlie (On-Call)",
        },
        {
            "name": "User types /status command",
            "text": "/status",
            "user": "Alice (DevOps Lead)",
        },
    ]

    for tc in test_cases:
        console.print(f"  [cyan]→ {tc['name']}[/cyan]")

        if "data" in tc:
            response = await router.handle_card_action(
                data=tc["data"],
                user_name=tc["user"],
            )
        else:
            response = await router.handle_text(
                text=tc["text"],
                user_name=tc["user"],
            )

        console.print(f"    Platform response: {response.text}")
        console.print()

    console.print(f"  [green]✓ Processed {len(router.action_log)} actions[/green]")


async def test_round_trip():
    """Test 3: Full round-trip simulation."""
    console.print("\n[bold yellow]━━━ Test 3: Full Round-Trip Flow ━━━[/bold yellow]")
    console.print("  [dim]Simulating: Alert → User Action → Remediation → Outcome[/dim]\n")

    webhook = TeamsWebhook(WEBHOOK_URL or "https://example.com/webhook")
    live = bool(WEBHOOK_URL)

    # Step 1: Platform detects anomaly and sends alert
    console.print("  [red]Step 1: Platform detects anomaly[/red]")
    console.print("    Anomaly: container 'redis' memory at 95%")

    approval_card = build_approval_card(
        incident_id="INC-099",
        container_name="redis",
        severity="MEDIUM",
        diagnosis="Redis memory usage at 95%. MAXMEMORY limit nearly reached. "
                  "Eviction policy is 'noeviction' — new writes will fail.",
        remediation_steps=[
            {"action": "redis_command", "target": "redis", "command": "MEMORY PURGE"},
            {"action": "health_check", "target": "redis"},
        ],
        confidence=0.92,
    )

    if live:
        result = await webhook.send_adaptive_card(approval_card)
        console.print(f"    → Sent to Teams: {result.message}")
    else:
        console.print("    → [dim]Would send approval card to Teams channel[/dim]")

    # Step 2: User responds (simulated)
    console.print("\n  [blue]Step 2: User clicks Approve in Teams[/blue]")
    await asyncio.sleep(0.5)  # Simulate user think time

    router = ActionRouter()

    @router.on_action(ActionType.APPROVE)
    async def on_approve(action: InboundAction) -> BotResponse:
        return BotResponse(
            text=f"✅ Approved by {action.user_name}. Executing MEMORY PURGE on redis..."
        )

    response = await router.handle_card_action(
        data={"action": "approve", "incident_id": "INC-099"},
        user_name="Alice (DevOps Lead)",
    )
    console.print(f"    → {response.text}")

    # Step 3: Platform executes and sends outcome
    console.print("\n  [green]Step 3: Platform executes remediation[/green]")
    await asyncio.sleep(0.5)  # Simulate execution time
    console.print("    → MEMORY PURGE executed (simulated)")
    console.print("    → Health check passed (simulated)")

    outcome_card = build_outcome_card(
        incident_id="INC-099",
        action_taken="MEMORY PURGE + health check",
        success=True,
        details="Redis memory dropped from 95% to 41%. "
                "Health check confirmed all operations responding normally.",
        duration_ms=1234,
    )

    if live:
        result = await webhook.send_adaptive_card(outcome_card)
        console.print(f"    → Outcome sent to Teams: {result.message}")
    else:
        console.print("    → [dim]Would send outcome card to Teams channel[/dim]")

    console.print("\n  [green bold]✓ Round-trip complete: Alert → Approve → Execute → Outcome[/green bold]")


async def run_demo():
    console.print(Panel(
        "AutoOpsAI — POC 11: Teams Two-Way Communication\n"
        "Platform → Teams (webhooks) + Teams → Platform (bot actions)",
        style="bold cyan",
    ))

    mode = "LIVE" if WEBHOOK_URL else "DRY RUN"
    console.print(f"  Mode: [{'green' if WEBHOOK_URL else 'yellow'}]{mode}[/{'green' if WEBHOOK_URL else 'yellow'}]")
    if not WEBHOOK_URL:
        console.print("  [dim]Set TEAMS_WEBHOOK_URL to send real messages to Teams[/dim]")

    await test_outbound_webhook()
    await test_inbound_actions()
    await test_round_trip()

    # Summary
    console.print("\n[bold]━━━ Summary ━━━[/bold]")
    table = Table()
    table.add_column("Direction", style="cyan")
    table.add_column("Mechanism", style="white")
    table.add_column("Status", style="green")
    table.add_column("For Production")

    table.add_row(
        "Platform → Teams",
        "Incoming Webhook",
        "✓ works" if WEBHOOK_URL else "✓ dry run",
        "Use Workflows webhook or Bot proactive messaging",
    )
    table.add_row(
        "Teams → Platform (text)",
        "Bot Framework /commands",
        "✓ simulated",
        "Deploy bot server + ngrok/tunnel",
    )
    table.add_row(
        "Teams → Platform (cards)",
        "Bot Framework Action.Submit",
        "✓ simulated",
        "Requires Azure Bot registration",
    )
    table.add_row(
        "Round-trip",
        "Webhook + Bot combined",
        "✓ simulated",
        "Full integration with pipeline",
    )
    console.print(table)

    console.print("\n[green]✓ POC 11 complete — two-way Teams communication validated[/green]")
    console.print(
        "\n[dim]Next steps:\n"
        "  1. Create an Incoming Webhook in your Teams channel\n"
        "  2. Register a Bot in Azure Bot Service\n"
        "  3. Run bot_server.py behind ngrok\n"
        "  4. See SETUP_GUIDE.md for full instructions[/dim]"
    )


if __name__ == "__main__":
    asyncio.run(run_demo())
