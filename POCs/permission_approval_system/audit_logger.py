"""
Audit Logger

Comprehensive audit logging for permission checks and tool execution decisions.
Provides JSONL-based audit trail for compliance and debugging.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

from .approval_workflow import ApprovalStatus, ApprovalMethod, ApprovalDecision


@dataclass
class AuditEvent:
    """Single audit event."""
    event_type: str  # 'permission_check', 'approval_requested', 'approval_decided', 'tool_executed'
    timestamp: datetime
    tool_name: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    details: Optional[dict] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'event_type': self.event_type,
            'timestamp': self.timestamp.isoformat(),
            'tool_name': self.tool_name,
            'user_id': self.user_id,
            'session_id': self.session_id,
            'details': self.details or {},
        }


class AuditLogger:
    """JSONL-based audit logger for tool execution and permissions."""
    
    def __init__(self, log_file: Optional[Path] = None):
        """
        Initialize audit logger.
        
        Args:
            log_file: Path to JSONL audit log file
        """
        self.log_file = log_file
        self.events: list[AuditEvent] = []
        
        if log_file:
            self.logger = logging.getLogger("audit")
            self.logger.setLevel(logging.INFO)
            
            # Create handler
            handler = logging.FileHandler(log_file)
            handler.setFormatter(logging.Formatter('%(message)s'))
            self.logger.addHandler(handler)
        else:
            self.logger = None
    
    def log_permission_check(
        self,
        tool_name: str,
        allowed: bool,
        reason: str,
        source: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Log a permission check."""
        event = AuditEvent(
            event_type='permission_check',
            timestamp=datetime.utcnow(),
            tool_name=tool_name,
            user_id=user_id,
            session_id=session_id,
            details={
                'allowed': allowed,
                'reason': reason,
                'source': source,
            }
        )
        self._write_event(event)
    
    def log_approval_requested(
        self,
        tool_name: str,
        risk_level: str,
        parameters: Optional[dict] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Log approval request."""
        event = AuditEvent(
            event_type='approval_requested',
            timestamp=datetime.utcnow(),
            tool_name=tool_name,
            user_id=user_id,
            session_id=session_id,
            details={
                'risk_level': risk_level,
                'parameters': parameters,
            }
        )
        self._write_event(event)
    
    def log_approval_decision(
        self,
        decision: ApprovalDecision,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Log approval decision."""
        event = AuditEvent(
            event_type='approval_decided',
            timestamp=decision.timestamp,
            tool_name=decision.tool_name,
            user_id=user_id,
            session_id=session_id,
            details={
                'status': decision.status.value,
                'method': decision.method.value,
                'approved_by': decision.approved_by,
                'reason': decision.reason,
                'risk_level': decision.risk_level.value if decision.risk_level else None,
            }
        )
        self._write_event(event)
    
    def log_tool_execution(
        self,
        tool_name: str,
        parameters: Optional[dict] = None,
        success: bool = True,
        error: Optional[str] = None,
        duration_ms: Optional[float] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Log tool execution."""
        event = AuditEvent(
            event_type='tool_executed',
            timestamp=datetime.utcnow(),
            tool_name=tool_name,
            user_id=user_id,
            session_id=session_id,
            details={
                'parameters': parameters,
                'success': success,
                'error': error,
                'duration_ms': duration_ms,
            }
        )
        self._write_event(event)
    
    def log_permission_denied(
        self,
        tool_name: str,
        reason: str,
        source: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Log permission denial."""
        self.log_permission_check(
            tool_name=tool_name,
            allowed=False,
            reason=reason,
            source=source,
            user_id=user_id,
            session_id=session_id,
        )
    
    def _write_event(self, event: AuditEvent) -> None:
        """Write event to log."""
        self.events.append(event)
        
        if self.logger:
            self.logger.info(json.dumps(event.to_dict()))
    
    def get_events(self, tool_name: Optional[str] = None) -> list[AuditEvent]:
        """Get audit events, optionally filtered by tool."""
        if tool_name:
            return [e for e in self.events if e.tool_name == tool_name]
        return self.events.copy()
    
    def get_report(self) -> dict:
        """Generate audit report."""
        return {
            'total_events': len(self.events),
            'by_type': {
                'permission_check': sum(1 for e in self.events if e.event_type == 'permission_check'),
                'approval_requested': sum(1 for e in self.events if e.event_type == 'approval_requested'),
                'approval_decided': sum(1 for e in self.events if e.event_type == 'approval_decided'),
                'tool_executed': sum(1 for e in self.events if e.event_type == 'tool_executed'),
            },
            'unique_tools': sorted(set(e.tool_name for e in self.events)),
            'total_tools_executed': len([e for e in self.events if e.event_type == 'tool_executed']),
        }
