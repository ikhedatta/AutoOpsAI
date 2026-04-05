"""
POC #6: Audit Logging & Error Handling

Capture all incident events for compliance and debugging.
- Audit log entries with context
- Error categorization
- Session tracking
- Export capability for compliance
- MongoDB persistence with file fallback
"""

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, List

logger = logging.getLogger("autoopsai.audit")


class AuditAction(Enum):
    """Types of audit log events."""
    INCIDENT_DETECTED = "incident_detected"
    PLAYBOOK_MATCHED = "playbook_matched"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    ACTION_EXECUTED = "action_executed"
    ACTION_FAILED = "action_failed"
    ACTION_TIMEOUT = "action_timeout"
    ACTION_ROLLED_BACK = "action_rolled_back"
    VERIFICATION_PASSED = "verification_passed"
    VERIFICATION_FAILED = "verification_failed"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


class ErrorCategory(Enum):
    """Error classification for auditing."""
    PLAYBOOK_NOT_FOUND = "playbook_not_found"
    REMEDIATION_FAILED = "remediation_failed"
    APPROVAL_TIMEOUT = "approval_timeout"
    APPROVAL_DENIED = "approval_denied"
    INSUFFICIENT_PERMISSIONS = "insufficient_permissions"
    LLM_INFERENCE_ERROR = "llm_inference_error"
    INFRASTRUCTURE_ERROR = "infrastructure_error"
    VERIFICATION_FAILED = "verification_failed"
    UNKNOWN = "unknown"


@dataclass
class AuditLogEntry:
    """Single audit log entry."""
    timestamp: datetime
    incident_id: str
    action: AuditAction
    user_id: str
    session_id: str
    details: Dict[str, Any]
    error: Optional[str] = None
    error_category: Optional[ErrorCategory] = None
    severity: str = "INFO"  # INFO, WARNING, ERROR, CRITICAL
    
    def to_json(self) -> str:
        """Convert entry to JSON string."""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        data['action'] = self.action.value
        data['error_category'] = self.error_category.value if self.error_category else None
        return json.dumps(data)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert entry to dictionary."""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        data['action'] = self.action.value
        data['error_category'] = self.error_category.value if self.error_category else None
        return data


@dataclass
class AuditLogStats:
    """Statistics from audit log."""
    total_entries: int
    by_action: Dict[str, int]
    by_error_category: Dict[str, int]
    by_severity: Dict[str, int]
    success_rate: float
    avg_resolution_time_seconds: Optional[float]


class AuditLogger:
    """Log and query incident audit trails, with MongoDB + file persistence."""
    
    def __init__(self, log_file: str | None = None, use_db: bool = True):
        """
        Initialize audit logger.
        
        Args:
            log_file: Path to audit log file (also writes to MongoDB if available)
            use_db: Whether to attempt MongoDB persistence
        """
        self.log_file = log_file or os.getenv("AUDIT_LOG_PATH", "audit.log")
        self.session_id = str(uuid.uuid4())
        self.entries: List[AuditLogEntry] = []
        self._file_lock = threading.Lock()
        self._db_available = False
        if use_db:
            try:
                from POCs.persistence import health_check
                self._db_available = health_check()
                if self._db_available:
                    logger.info("AuditLogger: MongoDB persistence enabled")
            except Exception:
                logger.debug("AuditLogger: MongoDB unavailable, file-only mode")
    
    async def log(
        self,
        incident_id: str,
        action: AuditAction,
        user_id: str,
        details: Dict[str, Any],
        error: Optional[str] = None,
        error_category: Optional[ErrorCategory] = None,
        severity: str = "INFO",
    ) -> None:
        """
        Log an audit entry.
        
        Args:
            incident_id: ID of incident
            action: Type of action
            user_id: User performing action (or "system")
            details: Action-specific details
            error: Error message if applicable
            error_category: Error category for classification
            severity: Log level (INFO/WARNING/ERROR/CRITICAL)
        """
        entry = AuditLogEntry(
            timestamp=datetime.now(),
            incident_id=incident_id,
            action=action,
            user_id=user_id,
            session_id=self.session_id,
            details=details,
            error=error,
            error_category=error_category,
            severity=severity,
        )
        
        self.entries.append(entry)

        # Persist to MongoDB
        if self._db_available:
            try:
                from POCs.persistence import append_audit_entry
                append_audit_entry(entry.to_dict())
            except Exception:
                logger.warning("Failed to persist audit entry to MongoDB", exc_info=True)

        # Also write to file for persistence (thread-safe)
        with self._file_lock:
            try:
                with open(self.log_file, 'a') as f:
                    f.write(entry.to_json() + '\n')
            except OSError:
                logger.warning("Failed to write audit entry to file %s", self.log_file, exc_info=True)
    
    def get_incident_trail(self, incident_id: str) -> List[AuditLogEntry]:
        """Get all audit entries for an incident."""
        return [e for e in self.entries if e.incident_id == incident_id]
    
    def get_stats(self) -> AuditLogStats:
        """Get statistics from audit log."""
        by_action = {}
        by_error_category = {}
        by_severity = {}
        
        for entry in self.entries:
            # Count by action
            action_key = entry.action.value
            by_action[action_key] = by_action.get(action_key, 0) + 1
            
            # Count by error category
            if entry.error_category:
                cat_key = entry.error_category.value
                by_error_category[cat_key] = by_error_category.get(cat_key, 0) + 1
            
            # Count by severity
            by_severity[entry.severity] = by_severity.get(entry.severity, 0) + 1
        
        # Calculate success rate (resolved incidents without errors)
        resolved_count = len([e for e in self.entries if e.action == AuditAction.RESOLVED])
        failed_count = len([e for e in self.entries if e.error_category])
        success_rate = (resolved_count - failed_count) / resolved_count if resolved_count > 0 else 0
        
        return AuditLogStats(
            total_entries=len(self.entries),
            by_action=by_action,
            by_error_category=by_error_category,
            by_severity=by_severity,
            success_rate=success_rate,
            avg_resolution_time_seconds=None,  # TODO: calculate from timestamps
        )
    
    def export_for_compliance(self, output_file: str = "audit_export.json") -> None:
        """Export all audit logs for compliance review."""
        export_data = {
            "session_id": self.session_id,
            "exported_at": datetime.now().isoformat(),
            "total_entries": len(self.entries),
            "entries": [e.to_dict() for e in self.entries],
        }

        with self._file_lock:
            with open(output_file, 'w') as f:
                json.dump(export_data, f, indent=2)


# Helper function to categorize errors
def categorize_error(error_message: str, context: Dict[str, Any] = None) -> ErrorCategory:
    """
    Categorize an error based on its message and context.
    
    Args:
        error_message: Error message to categorize
        context: Additional context (e.g., action_type, step)
    
    Returns:
        ErrorCategory
    """
    context = context or {}
    error_lower = error_message.lower()
    
    if "playbook" in error_lower and "not found" in error_lower:
        return ErrorCategory.PLAYBOOK_NOT_FOUND
    elif "permission" in error_lower or "denied" in error_lower:
        return ErrorCategory.INSUFFICIENT_PERMISSIONS
    elif "timeout" in error_lower:
        return ErrorCategory.APPROVAL_TIMEOUT
    elif "inference" in error_lower or "llm" in error_lower:
        return ErrorCategory.LLM_INFERENCE_ERROR
    elif context.get("action_type") == "remediation":
        return ErrorCategory.REMEDIATION_FAILED
    elif context.get("action_type") == "verification":
        return ErrorCategory.VERIFICATION_FAILED
    else:
        return ErrorCategory.UNKNOWN
