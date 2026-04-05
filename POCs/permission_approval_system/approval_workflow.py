"""
Approval Workflow

Interactive user approval system with risk assessment,
timeout handling, and audit logging.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Callable, Awaitable

from .tool_registry import ToolMetadata, ToolRiskLevel


class ApprovalStatus(str, Enum):
    """Status of an approval request."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ApprovalMethod(str, Enum):
    """How the approval was obtained."""
    AUTO = "auto"                  # Auto-approved
    USER_INTERACTIVE = "user_interactive"  # Interactive prompt
    CONFIG = "config"              # From config allowlist
    SAFE_COMMAND = "safe_command"  # Pre-approved safe command


@dataclass
class ApprovalDecision:
    """Record of an approval decision."""
    tool_name: str
    status: ApprovalStatus
    method: ApprovalMethod
    timestamp: datetime = field(default_factory=datetime.utcnow)
    approved_by: Optional[str] = None
    reason: str = ""
    risk_level: Optional[ToolRiskLevel] = None
    parameters: Optional[dict] = None


@dataclass
class ApprovalRequest:
    """Request for user approval of tool execution."""
    tool_name: str
    tool_meta: ToolMetadata
    parameters: dict
    risk_level: ToolRiskLevel
    reason: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def summary(self) -> str:
        """Human-readable summary of the request."""
        lines = [
            f"🔐 Tool Approval Request",
            f"━━━━━━━━━━━━━━━━━━━━━━━━",
            f"Tool:        {self.tool_name}",
            f"Category:    {self.tool_meta.category}",
            f"Risk Level:  {self.risk_level.value.upper()}",
            f"Description: {self.tool_meta.description}",
        ]
        
        if self.parameters:
            lines.append(f"Parameters:")
            for k, v in self.parameters.items():
                lines.append(f"  - {k}: {v}")
        
        if self.reason:
            lines.append(f"Reason: {self.reason}")
        
        lines.extend([
            "",
            "Required Permissions:",
        ])
        for perm in self.tool_meta.required_permissions:
            lines.append(f"  ✓ {perm}")
        
        return "\n".join(lines)


class ApprovalWorkflow:
    """Interactive approval workflow for tool execution."""
    
    def __init__(
        self,
        interactive: bool = True,
        timeout_seconds: int = 300,
        auto_approve_read_only: bool = True,
    ):
        """
        Initialize approval workflow.
        
        Args:
            interactive: Enable interactive prompts
            timeout_seconds: Default timeout for approval requests
            auto_approve_read_only: Auto-approve read-only operations
        """
        self.interactive = interactive
        self.timeout_seconds = timeout_seconds
        self.auto_approve_read_only = auto_approve_read_only
        
        # Audit trail
        self.decisions: list[ApprovalDecision] = []
        
        # Custom approval handler (for testing)
        self._custom_handler: Optional[Callable[[ApprovalRequest], Awaitable[bool]]] = None
    
    def set_custom_handler(
        self,
        handler: Callable[[ApprovalRequest], Awaitable[bool]],
    ) -> None:
        """Set custom approval handler (for testing)."""
        self._custom_handler = handler
    
    async def request_approval(
        self,
        tool_name: str,
        tool_meta: ToolMetadata,
        parameters: dict,
        reason: str = "",
    ) -> ApprovalDecision:
        """
        Request approval for tool execution.
        
        Returns decision with approval status and method.
        """
        request = ApprovalRequest(
            tool_name=tool_name,
            tool_meta=tool_meta,
            parameters=parameters,
            risk_level=tool_meta.risk_level,
            reason=reason,
        )
        
        # Auto-approve read-only operations
        if tool_meta.is_read_only and self.auto_approve_read_only:
            decision = ApprovalDecision(
                tool_name=tool_name,
                status=ApprovalStatus.APPROVED,
                method=ApprovalMethod.AUTO,
                approved_by="system",
                reason="Auto-approved read-only operation",
                risk_level=tool_meta.risk_level,
                parameters=parameters,
            )
            self.decisions.append(decision)
            return decision
        
        # Use custom handler if set (for testing)
        if self._custom_handler:
            approved = await self._custom_handler(request)
            decision = ApprovalDecision(
                tool_name=tool_name,
                status=ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED,
                method=ApprovalMethod.USER_INTERACTIVE,
                approved_by="test_handler",
                reason="Custom test handler decision",
                risk_level=tool_meta.risk_level,
                parameters=parameters,
            )
            self.decisions.append(decision)
            return decision
        
        # Interactive approval
        if self.interactive and tool_meta.supports_approval:
            return await self._interactive_approval(request)
        
        # Non-interactive mode: reject by default
        decision = ApprovalDecision(
            tool_name=tool_name,
            status=ApprovalStatus.REJECTED,
            method=ApprovalMethod.CONFIG,
            reason="Approval required but interactive mode disabled",
            risk_level=tool_meta.risk_level,
            parameters=parameters,
        )
        self.decisions.append(decision)
        return decision
    
    async def _interactive_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        """Interactive approval prompt with timeout."""
        print("\n" + "=" * 70)
        print(request.summary())
        print("=" * 70)
        
        # Determine timeout based on risk level
        timeout = self._get_timeout_for_risk(request.risk_level)
        print(f"\n⏱️  You have {timeout} seconds to respond.\n")
        
        try:
            # Run async input with timeout
            response = await asyncio.wait_for(
                self._prompt_user_async(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            decision = ApprovalDecision(
                tool_name=request.tool_name,
                status=ApprovalStatus.TIMEOUT,
                method=ApprovalMethod.USER_INTERACTIVE,
                reason=f"No response within {timeout} seconds",
                risk_level=request.risk_level,
                parameters=request.parameters,
            )
            self.decisions.append(decision)
            return decision
        
        # Parse response
        response = response.lower().strip()
        
        if response in ('y', 'yes'):
            decision = ApprovalDecision(
                tool_name=request.tool_name,
                status=ApprovalStatus.APPROVED,
                method=ApprovalMethod.USER_INTERACTIVE,
                approved_by="user",
                reason="User approved",
                risk_level=request.risk_level,
                parameters=request.parameters,
            )
        elif response in ('n', 'no'):
            decision = ApprovalDecision(
                tool_name=request.tool_name,
                status=ApprovalStatus.REJECTED,
                method=ApprovalMethod.USER_INTERACTIVE,
                reason="User rejected",
                risk_level=request.risk_level,
                parameters=request.parameters,
            )
        else:
            decision = ApprovalDecision(
                tool_name=request.tool_name,
                status=ApprovalStatus.REJECTED,
                method=ApprovalMethod.USER_INTERACTIVE,
                reason="Invalid response",
                risk_level=request.risk_level,
                parameters=request.parameters,
            )
        
        self.decisions.append(decision)
        return decision
    
    async def _prompt_user_async(self) -> str:
        """Async wrapper for user input."""
        # Run blocking input in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            input,
            "Allow this tool to execute? (yes/no): ",
        )
    
    def _get_timeout_for_risk(self, risk_level: ToolRiskLevel) -> int:
        """Get timeout in seconds based on risk level."""
        timeouts = {
            ToolRiskLevel.READ_ONLY: 60,
            ToolRiskLevel.LOW_RISK: 120,
            ToolRiskLevel.MEDIUM_RISK: 300,
            ToolRiskLevel.HIGH_RISK: 600,
            ToolRiskLevel.BLOCKED: 0,
        }
        return timeouts.get(risk_level, self.timeout_seconds)
    
    def get_audit_report(self) -> dict:
        """Generate audit report of all approval decisions."""
        return {
            'total_requests': len(self.decisions),
            'approved': sum(1 for d in self.decisions if d.status == ApprovalStatus.APPROVED),
            'rejected': sum(1 for d in self.decisions if d.status == ApprovalStatus.REJECTED),
            'timeout': sum(1 for d in self.decisions if d.status == ApprovalStatus.TIMEOUT),
            'by_method': {
                method.value: sum(1 for d in self.decisions if d.method == method)
                for method in ApprovalMethod
            },
            'by_risk_level': {
                level.value: sum(1 for d in self.decisions if d.risk_level == level)
                for level in ToolRiskLevel
            },
            'decisions': [
                {
                    'tool': d.tool_name,
                    'status': d.status.value,
                    'method': d.method.value,
                    'risk_level': d.risk_level.value,
                    'timestamp': d.timestamp.isoformat(),
                    'approved_by': d.approved_by,
                    'reason': d.reason,
                }
                for d in self.decisions
            ]
        }
    
    def print_approval_summary(self) -> None:
        """Print human-readable approval summary."""
        report = self.get_audit_report()
        
        print("\n" + "=" * 70)
        print("📊 Approval Workflow Summary")
        print("=" * 70)
        print(f"Total Requests:    {report['total_requests']}")
        print(f"  ✓ Approved:      {report['approved']}")
        print(f"  ✗ Rejected:      {report['rejected']}")
        print(f"  ⏱ Timeout:       {report['timeout']}")
        print()
        print("By Method:")
        for method, count in report['by_method'].items():
            print(f"  - {method}: {count}")
        print()
        print("By Risk Level:")
        for level, count in report['by_risk_level'].items():
            if count > 0:
                print(f"  - {level}: {count}")
        print("=" * 70)
