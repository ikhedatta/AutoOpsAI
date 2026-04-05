"""
POC 7 Demo — Permission & Approval System

Demonstrates:
1. Tool registry with risk classification
2. Permission checking with allowlist/blocklist
3. Interactive approval workflow
4. Audit logging of decisions

Run:
    uv run python -m POCs.permission_approval_system.demo
"""

import asyncio
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .tool_registry import get_registry, ToolRiskLevel
from .permission_manager import PermissionManager, UserPermissionConfig
from .approval_workflow import ApprovalWorkflow, ApprovalStatus, ApprovalMethod
from .audit_logger import AuditLogger

console = Console()


def print_tool_registry():
    """Print tool registry."""
    console.print("\n[bold cyan]Tool Registry[/bold cyan]\n")
    
    registry = get_registry()
    
    # Table by risk level
    table = Table(title="Tools by Risk Level")
    table.add_column("Tool Name", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Risk Level", style="yellow")
    table.add_column("Read-Only", style="green")
    
    for tool in registry.get_enabled_tools():
        risk_icon = {
            ToolRiskLevel.READ_ONLY: "✓",
            ToolRiskLevel.LOW_RISK: "⚠",
            ToolRiskLevel.MEDIUM_RISK: "⚠⚠",
            ToolRiskLevel.HIGH_RISK: "🔴",
            ToolRiskLevel.BLOCKED: "🚫",
        }.get(tool.risk_level, "?")
        
        table.add_row(
            tool.name,
            tool.description[:50] + "..." if len(tool.description) > 50 else tool.description,
            f"{risk_icon} {tool.risk_level.value}",
            "Yes" if tool.is_read_only else "No",
        )
    
    console.print(table)


def test_permission_manager():
    """Test permission manager."""
    console.print("\n[bold cyan]Part 1: Permission Manager Tests[/bold cyan]\n")
    
    registry = get_registry()
    manager = PermissionManager(registry)
    
    # Test 1: Check safe command (should be allowed)
    console.print("[bold]Test 1: Safe command (read-only)[/bold]")
    result = manager.check_permission('docker_list_containers')
    console.print(f"  Tool: docker_list_containers")
    console.print(f"  Allowed: {result.allowed}")
    console.print(f"  Reason: {result.reason}")
    console.print(f"  Source: {result.source}\n")
    
    # Test 2: Check destructive command without permission (should be denied)
    console.print("[bold]Test 2: Destructive command without permission[/bold]")
    result = manager.check_permission('docker_restart_container')
    console.print(f"  Tool: docker_restart_container")
    console.print(f"  Allowed: {result.allowed}")
    console.print(f"  Reason: {result.reason}\n")
    
    # Test 3: Grant permission and check again
    console.print("[bold]Test 3: Grant permission and recheck[/bold]")
    manager.grant_permission('docker_restart_container')
    result = manager.check_permission('docker_restart_container')
    console.print(f"  Tool: docker_restart_container")
    console.print(f"  Allowed: {result.allowed}")
    console.print(f"  Reason: {result.reason}\n")
    
    # Test 4: Block a tool
    console.print("[bold]Test 4: Block a tool[/bold]")
    manager.block_tool('docker_list_containers')
    result = manager.check_permission('docker_list_containers')
    console.print(f"  Tool: docker_list_containers")
    console.print(f"  Allowed: {result.allowed}")
    console.print(f"  Reason: {result.reason}\n")
    
    # Summary
    console.print("[bold]Permission Manager Status[/bold]")
    status = manager.get_status_summary()
    for key, value in status.items():
        console.print(f"  {key}: {value}")
    console.print()


async def test_approval_workflow():
    """Test approval workflow."""
    console.print("\n[bold cyan]Part 2: Approval Workflow Tests[/bold cyan]\n")
    
    registry = get_registry()
    workflow = ApprovalWorkflow(
        interactive=False,  # Non-interactive for testing
        auto_approve_read_only=True,
    )
    
    # Set up custom handler for testing (simulate user approval)
    async def test_handler(request):
        # Auto-approve docker_restart, reject others
        return request.tool_name == 'docker_restart_container'
    
    workflow.set_custom_handler(test_handler)
    
    # Test 1: Auto-approve read-only
    console.print("[bold]Test 1: Auto-approve read-only operation[/bold]")
    tool = registry.get('docker_list_containers')
    decision = await workflow.request_approval(
        tool_name='docker_list_containers',
        tool_meta=tool,
        parameters={},
        reason="List containers for monitoring",
    )
    console.print(f"  Tool: {decision.tool_name}")
    console.print(f"  Status: {decision.status.value}")
    console.print(f"  Method: {decision.method.value}")
    console.print(f"  Reason: {decision.reason}\n")
    
    # Test 2: Interactive approval (with custom handler)
    console.print("[bold]Test 2: Request approval for destructive operation[/bold]")
    tool = registry.get('docker_restart_container')
    decision = await workflow.request_approval(
        tool_name='docker_restart_container',
        tool_meta=tool,
        parameters={'container_name': 'flask-app'},
        reason="Restart stalled service",
    )
    console.print(f"  Tool: {decision.tool_name}")
    console.print(f"  Status: {decision.status.value}")
    console.print(f"  Method: {decision.method.value}")
    console.print(f"  Parameters: {decision.parameters}\n")
    
    # Test 3: Rejection
    console.print("[bold]Test 3: Approval rejected[/bold]")
    tool = registry.get('docker_stop_container')
    decision = await workflow.request_approval(
        tool_name='docker_stop_container',
        tool_meta=tool,
        parameters={'container_name': 'mongodb'},
        reason="Stop database container",
    )
    console.print(f"  Tool: {decision.tool_name}")
    console.print(f"  Status: {decision.status.value}")
    console.print(f"  Method: {decision.method.value}\n")
    
    # Print audit report
    workflow.print_approval_summary()


def test_audit_logger():
    """Test audit logger."""
    console.print("\n[bold cyan]Part 3: Audit Logger Tests[/bold cyan]\n")
    
    # Create logger
    log_file = Path("/tmp/audit_test.jsonl")
    logger = AuditLogger(log_file=log_file)
    
    # Log various events
    logger.log_permission_check(
        tool_name='docker_list_containers',
        allowed=True,
        reason='Safe read-only operation',
        source='safe_command',
        user_id='user1',
        session_id='session1',
    )
    
    logger.log_approval_requested(
        tool_name='docker_restart_container',
        risk_level='HIGH_RISK',
        parameters={'container_name': 'flask-app'},
        user_id='user1',
        session_id='session1',
    )
    
    logger.log_tool_execution(
        tool_name='docker_list_containers',
        parameters={},
        success=True,
        duration_ms=125.5,
        user_id='user1',
        session_id='session1',
    )
    
    logger.log_permission_denied(
        tool_name='docker_remove_container',
        reason='Tool not in allowlist',
        source='denied',
        user_id='user1',
        session_id='session1',
    )
    
    # Print report
    console.print("[bold]Audit Report[/bold]")
    report = logger.get_report()
    for key, value in report.items():
        if isinstance(value, dict):
            console.print(f"  {key}:")
            for k, v in value.items():
                console.print(f"    {k}: {v}")
        else:
            console.print(f"  {key}: {value}")
    
    console.print(f"\nAudit log written to: {log_file}")
    
    # Print log file content
    if log_file.exists():
        console.print("\n[bold]Audit Log Content (JSONL)[/bold]")
        with open(log_file) as f:
            for i, line in enumerate(f, 1):
                console.print(f"  {i}. {line.strip()}")


def test_config_persistence():
    """Test configuration persistence."""
    console.print("\n[bold cyan]Part 4: Configuration Persistence[/bold cyan]\n")
    
    registry = get_registry()
    config_file = Path("/tmp/permissions_config.json")
    
    # Create manager and set permissions
    manager = PermissionManager(registry)
    manager.grant_permission('docker_restart_container')
    manager.grant_permission('docker_stop_container')
    manager.grant_user_permission('docker:write')
    
    console.print("[bold]Before Save:[/bold]")
    console.print(f"  Allowed tools: {len(manager.config.allowed_tools)}")
    console.print(f"  Granted permissions: {len(manager.config.granted_permissions)}")
    
    # Save config
    manager.save_config(config_file)
    console.print(f"\n✓ Config saved to: {config_file}")
    
    # Load config in new manager
    manager2 = PermissionManager(registry, config_file=config_file)
    manager2.load_config(config_file)
    
    console.print("\n[bold]After Load:[/bold]")
    console.print(f"  Allowed tools: {len(manager2.config.allowed_tools)}")
    console.print(f"  Granted permissions: {len(manager2.config.granted_permissions)}")
    console.print(f"  Allowed: {manager2.config.allowed_tools}")


def run_demo():
    """Run complete demo."""
    console.print(Panel(
        "AutoOpsAI — POC 7: Permission & Approval System\n"
        "Tool Registry • Permission Manager • Approval Workflow • Audit Logging",
        style="bold cyan",
    ))
    
    # Part 1: Tool Registry
    print_tool_registry()
    
    # Part 2: Permission Manager
    test_permission_manager()
    
    # Part 3: Approval Workflow (async)
    asyncio.run(test_approval_workflow())
    
    # Part 4: Audit Logger
    test_audit_logger()
    
    # Part 5: Config Persistence
    test_config_persistence()
    
    console.print("\n" + "=" * 70)
    console.print("[bold green]✓ Demo Complete[/bold green]")
    console.print("=" * 70)


if __name__ == '__main__':
    run_demo()
