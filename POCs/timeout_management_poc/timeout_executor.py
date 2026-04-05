"""
POC #3: Timeout Management

Enforce timeouts on remediation actions with automatic rollback.
- Execute action with timeout
- On timeout, trigger rollback
- Track SLA against target MTTR
- Escalate if SLA exceeded
"""

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable, Any, Dict
from datetime import datetime, timedelta


class ActionStatus(Enum):
    """Status of a remediation action."""
    PENDING = "pending"
    EXECUTING = "executing"
    SUCCESS = "success"
    TIMEOUT = "timeout"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class ActionResult:
    """Result of action execution."""
    status: ActionStatus
    result: Optional[Any] = None
    error: Optional[str] = None
    elapsed_seconds: float = 0.0
    rollback_status: Optional[str] = None


@dataclass
class IncidentSLA:
    """Service Level Agreement for incident resolution."""
    severity: str  # P1, P2, P3, P4
    target_mttr_minutes: int
    max_escalation_time_minutes: int = None
    
    def __post_init__(self):
        if self.max_escalation_time_minutes is None:
            self.max_escalation_time_minutes = self.target_mttr_minutes * 2


class SLATracker:
    """Track incident against SLA targets."""
    
    # SLA definitions per severity
    SLA_DEFINITIONS = {
        "P1": IncidentSLA(severity="P1", target_mttr_minutes=5, max_escalation_time_minutes=10),
        "P2": IncidentSLA(severity="P2", target_mttr_minutes=15, max_escalation_time_minutes=30),
        "P3": IncidentSLA(severity="P3", target_mttr_minutes=60, max_escalation_time_minutes=120),
        "P4": IncidentSLA(severity="P4", target_mttr_minutes=480, max_escalation_time_minutes=1440),
    }
    
    def __init__(self, severity: str, start_time: datetime = None):
        """Initialize SLA tracker."""
        self.severity = severity
        self.start_time = start_time or datetime.now()
        self.sla = self.SLA_DEFINITIONS.get(severity)
        if not self.sla:
            raise ValueError(f"Unknown severity: {severity}")
    
    @property
    def elapsed_minutes(self) -> float:
        """Get elapsed time since incident start."""
        return (datetime.now() - self.start_time).total_seconds() / 60
    
    @property
    def is_sla_breached(self) -> bool:
        """Check if SLA target has been exceeded."""
        return self.elapsed_minutes > self.sla.target_mttr_minutes
    
    @property
    def is_escalation_needed(self) -> bool:
        """Check if escalation time has been exceeded."""
        return self.elapsed_minutes > self.sla.max_escalation_time_minutes
    
    @property
    def remaining_sla_minutes(self) -> float:
        """Get minutes remaining before SLA breach."""
        return max(0, self.sla.target_mttr_minutes - self.elapsed_minutes)
    
    def get_status_message(self) -> str:
        """Get human-readable SLA status."""
        if self.is_escalation_needed:
            return f"⚠️ ESCALATION NEEDED: {self.elapsed_minutes:.1f}m elapsed (max {self.sla.max_escalation_time_minutes}m)"
        elif self.is_sla_breached:
            return f"❌ SLA BREACHED: {self.elapsed_minutes:.1f}m elapsed (target {self.sla.target_mttr_minutes}m)"
        else:
            return f"✓ On track: {self.remaining_sla_minutes:.1f}m remaining"


class TimeoutExecutor:
    """Execute actions with timeout enforcement and rollback."""
    
    # Default timeouts per risk level (seconds)
    DEFAULT_TIMEOUTS = {
        "LOW": 30,      # 30 seconds
        "MEDIUM": 120,  # 2 minutes
        "HIGH": 300,    # 5 minutes
    }
    
    def __init__(self):
        """Initialize timeout executor."""
        self.running_actions: Dict[str, asyncio.Task] = {}
    
    async def execute_with_timeout(
        self,
        action_id: str,
        execute_fn: Callable[[], Any],
        rollback_fn: Optional[Callable[[], Any]] = None,
        timeout_seconds: Optional[int] = None,
        risk_level: str = "MEDIUM",
    ) -> ActionResult:
        """
        Execute action with timeout and optional rollback.
        
        Args:
            action_id: Unique action identifier
            execute_fn: Async function to execute
            rollback_fn: Optional async function to rollback on timeout
            timeout_seconds: Timeout in seconds (uses default if not provided)
            risk_level: Risk level (LOW/MEDIUM/HIGH) for default timeout
        
        Returns:
            ActionResult with status and details
        """
        timeout = timeout_seconds or self.DEFAULT_TIMEOUTS.get(risk_level, 120)
        start_time = time.time()
        
        try:
            # Execute action with timeout
            result = await asyncio.wait_for(
                execute_fn(),
                timeout=timeout,
            )
            
            elapsed = time.time() - start_time
            return ActionResult(
                status=ActionStatus.SUCCESS,
                result=result,
                elapsed_seconds=elapsed,
            )
        
        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            
            # Timeout exceeded - execute rollback if provided
            rollback_status = None
            if rollback_fn:
                try:
                    await asyncio.wait_for(
                        rollback_fn(),
                        timeout=timeout / 2,  # Give rollback half the time
                    )
                    rollback_status = "success"
                except asyncio.TimeoutError:
                    rollback_status = "timeout"
                except Exception as e:
                    rollback_status = f"failed: {str(e)}"
            
            return ActionResult(
                status=ActionStatus.TIMEOUT,
                error=f"Action exceeded timeout of {timeout}s",
                elapsed_seconds=elapsed,
                rollback_status=rollback_status,
            )
        
        except Exception as e:
            elapsed = time.time() - start_time
            
            # Action failed - attempt rollback
            rollback_status = None
            if rollback_fn and isinstance(e, Exception):
                try:
                    await rollback_fn()
                    rollback_status = "success"
                except Exception as rollback_e:
                    rollback_status = f"failed: {str(rollback_e)}"
            
            return ActionResult(
                status=ActionStatus.FAILED,
                error=str(e),
                elapsed_seconds=elapsed,
                rollback_status=rollback_status,
            )
    
    async def execute_with_sla_tracking(
        self,
        action_id: str,
        execute_fn: Callable[[], Any],
        rollback_fn: Optional[Callable[[], Any]] = None,
        timeout_seconds: Optional[int] = None,
        sla: Optional[IncidentSLA] = None,
    ) -> tuple[ActionResult, SLATracker]:
        """
        Execute action with timeout and SLA tracking.
        
        Returns:
            Tuple of (ActionResult, SLATracker)
        """
        tracker = SLATracker(sla.severity) if sla else None
        
        result = await self.execute_with_timeout(
            action_id=action_id,
            execute_fn=execute_fn,
            rollback_fn=rollback_fn,
            timeout_seconds=timeout_seconds,
        )
        
        return result, tracker


# Convenience functions for testing
async def dummy_action(duration: float = 0.1, should_fail: bool = False):
    """Dummy action for testing."""
    await asyncio.sleep(duration)
    if should_fail:
        raise Exception("Action failed!")
    return {"status": "completed", "duration": duration}


async def dummy_rollback(duration: float = 0.05):
    """Dummy rollback for testing."""
    await asyncio.sleep(duration)
    return {"status": "rolled_back", "duration": duration}
