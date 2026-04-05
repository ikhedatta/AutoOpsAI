"""
Integration Example

Shows how to integrate the permission & approval system with the tool_execution agent.
This is a reference implementation for connecting the two POCs.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

from .tool_registry import get_registry, ToolRiskLevel
from .permission_manager import PermissionManager
from .approval_workflow import ApprovalWorkflow, ApprovalStatus
from .audit_logger import AuditLogger


@dataclass
class ToolExecutionRequest:
    """Request to execute a tool with permission checking."""
    tool_name: str
    parameters: dict
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    reason: str = ""


@dataclass
class ToolExecutionDecision:
    """Decision on whether to execute a tool."""
    allowed: bool
    reason: str
    tool_name: str
    status: str  # 'approved', 'rejected', 'pending_approval', 'timeout'


class SafeToolExecutor:
    """
    Wrapper for safe tool execution with permission and approval checks.
    
    This is how the permission/approval system integrates with tool_execution agent.
    """
    
    def __init__(
        self,
        interactive: bool = True,
        auto_approve_read_only: bool = True,
        audit_log_file: Optional[str] = None,
    ):
        """
        Initialize safe executor.
        
        Args:
            interactive: Enable interactive approval prompts
            auto_approve_read_only: Auto-approve read-only operations
            audit_log_file: Path to audit log file
        """
        self.registry = get_registry()
        self.permission_manager = PermissionManager(self.registry)
        self.approval_workflow = ApprovalWorkflow(
            interactive=interactive,
            auto_approve_read_only=auto_approve_read_only,
        )
        self.audit_logger = AuditLogger(
            log_file=audit_log_file if audit_log_file else None
        )
    
    async def can_execute(self, request: ToolExecutionRequest) -> ToolExecutionDecision:
        """
        Check if tool can be executed and request approval if needed.
        
        This is the main integration point with tool_execution agent.
        Returns decision with status and reason.
        """
        
        # 1. Check tool exists
        if not self.registry.exists(request.tool_name):
            decision = ToolExecutionDecision(
                allowed=False,
                reason=f"Tool '{request.tool_name}' not found in registry",
                tool_name=request.tool_name,
                status='rejected',
            )
            self.audit_logger.log_permission_denied(
                request.tool_name,
                decision.reason,
                'unknown',
                request.user_id,
                request.session_id,
            )
            return decision
        
        # 2. Check permissions
        perm_result = self.permission_manager.check_permission(request.tool_name)
        
        self.audit_logger.log_permission_check(
            request.tool_name,
            perm_result.allowed,
            perm_result.reason,
            perm_result.source,
            request.user_id,
            request.session_id,
        )
        
        if not perm_result.allowed:
            decision = ToolExecutionDecision(
                allowed=False,
                reason=f"Permission denied: {perm_result.reason}",
                tool_name=request.tool_name,
                status='rejected',
            )
            return decision
        
        # 3. Request approval if needed
        tool_meta = self.registry.get(request.tool_name)
        
        # Log approval request
        self.audit_logger.log_approval_requested(
            request.tool_name,
            tool_meta.risk_level.value,
            request.parameters,
            request.user_id,
            request.session_id,
        )
        
        # Request approval
        approval_decision = await self.approval_workflow.request_approval(
            request.tool_name,
            tool_meta,
            request.parameters,
            reason=request.reason,
        )
        
        # Log approval decision
        self.audit_logger.log_approval_decision(
            approval_decision,
            request.user_id,
            request.session_id,
        )
        
        # Convert approval decision to execution decision
        allowed = approval_decision.status == ApprovalStatus.APPROVED
        
        status_map = {
            ApprovalStatus.APPROVED: 'approved',
            ApprovalStatus.REJECTED: 'rejected',
            ApprovalStatus.TIMEOUT: 'timeout',
            ApprovalStatus.CANCELLED: 'rejected',
            ApprovalStatus.PENDING: 'pending_approval',
        }
        
        return ToolExecutionDecision(
            allowed=allowed,
            reason=approval_decision.reason,
            tool_name=request.tool_name,
            status=status_map.get(approval_decision.status, 'rejected'),
        )
    
    def log_tool_execution(
        self,
        tool_name: str,
        parameters: dict,
        success: bool,
        error: Optional[str] = None,
        duration_ms: Optional[float] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Log tool execution result."""
        self.audit_logger.log_tool_execution(
            tool_name,
            parameters,
            success,
            error,
            duration_ms,
            user_id,
            session_id,
        )
    
    def get_audit_report(self) -> dict:
        """Get complete audit report."""
        return self.audit_logger.get_report()


# ============================================================================
# Example usage with agent loop
# ============================================================================

async def example_agent_with_permissions():
    """
    Example showing how to use SafeToolExecutor in the agent loop.
    
    This demonstrates integration with tool_execution POC.
    """
    
    executor = SafeToolExecutor(
        interactive=False,  # Non-interactive for this example
        auto_approve_read_only=True,
    )
    
    # Simulate tool calls from LLM
    tool_calls = [
        {
            "function": {
                "name": "docker_list_containers",
                "arguments": {"all": True}
            }
        },
        {
            "function": {
                "name": "docker_restart_container",
                "arguments": {"container_name": "flask-app"}
            }
        },
    ]
    
    print("\n" + "=" * 70)
    print("AGENT EXECUTION WITH PERMISSIONS & APPROVAL")
    print("=" * 70 + "\n")
    
    # Set custom handler for testing
    async def auto_approve_low_risk(request):
        """Auto-approve low and medium risk for demo."""
        return request.tool_meta.risk_level in [
            ToolRiskLevel.READ_ONLY,
            ToolRiskLevel.LOW_RISK,
        ]
    
    executor.approval_workflow.set_custom_handler(auto_approve_low_risk)
    
    for i, tc in enumerate(tool_calls, 1):
        func = tc["function"]
        tool_name = func["name"]
        tool_args = func.get("arguments", {})
        
        print(f"[{i}] Tool Call: {tool_name}")
        print(f"    Arguments: {tool_args}")
        
        # Check permission and request approval
        request = ToolExecutionRequest(
            tool_name=tool_name,
            parameters=tool_args,
            user_id="agent_user",
            session_id="demo_session",
            reason="Agent requested tool execution",
        )
        
        decision = await executor.can_execute(request)
        
        print(f"    Permission: {decision.status.upper()}")
        print(f"    Reason: {decision.reason}")
        
        if decision.allowed:
            # Simulate tool execution
            print(f"    ✓ Executing tool...")
            # result = execute_tool(tool_name, tool_args)
            
            # Log execution
            executor.log_tool_execution(
                tool_name,
                tool_args,
                success=True,
                duration_ms=125.5,
                user_id="agent_user",
                session_id="demo_session",
            )
        else:
            print(f"    ✗ Tool execution blocked")
            executor.log_tool_execution(
                tool_name,
                tool_args,
                success=False,
                error=decision.reason,
                user_id="agent_user",
                session_id="demo_session",
            )
        
        print()
    
    # Print audit report
    print("=" * 70)
    print("AUDIT REPORT")
    print("=" * 70)
    report = executor.get_audit_report()
    print(f"Total events: {report['total_events']}")
    print(f"Event breakdown:")
    for event_type, count in report['by_type'].items():
        print(f"  - {event_type}: {count}")
    print(f"Tools involved: {report['unique_tools']}")
    print()


if __name__ == '__main__':
    import asyncio
    asyncio.run(example_agent_with_permissions())
