"""
POC #1: Tiered Permission System

Tests safe operation whitelisting and auto-execute logic.
- LOW risk: auto-execute immediately
- MEDIUM risk: require approval, 5-min timeout
- HIGH risk: require approval, no timeout

This is the foundation for all remediation decisions.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Set, Dict, List, Optional
import yaml


class RiskLevel(Enum):
    """Risk classification for remediation actions."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PermissionResult:
    """Result of a permission check."""
    def __init__(self, result: bool, reason: str = ""):
        self.result = result
        self.reason = reason
    
    def __repr__(self):
        return f"PermissionResult(result={self.result}, reason='{self.reason}')"


@dataclass
class SafeOperation:
    """Definition of a safe operation."""
    action: str
    risk_level: RiskLevel
    description: str
    requires_verification: bool = True


class PermissionChecker:
    """
    Checks if an action is safe to execute automatically
    or requires human approval.
    """
    
    def __init__(self, config_file: str = "safe_operations.yaml"):
        """
        Initialize permission checker with safe operations config.
        
        Args:
            config_file: Path to YAML file with safe operations whitelist
        """
        self.safe_operations: Dict[RiskLevel, Set[str]] = {
            RiskLevel.LOW: set(),
            RiskLevel.MEDIUM: set(),
            RiskLevel.HIGH: set(),
        }
        self._load_safe_operations(config_file)
    
    def _load_safe_operations(self, config_file: str) -> None:
        """Load safe operations from YAML config."""
        try:
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f) or {}
            
            for risk_level in RiskLevel:
                operations = config.get(risk_level.value, [])
                self.safe_operations[risk_level] = set(operations)
        except FileNotFoundError:
            # Initialize with defaults if config not found
            self._initialize_defaults()
    
    def _initialize_defaults(self) -> None:
        """Initialize with default safe operations."""
        self.safe_operations[RiskLevel.LOW] = {
            "redis_memory_purge",
            "log_rotation",
            "cache_clear",
            "dns_cache_flush",
            "temp_file_cleanup",
        }
        self.safe_operations[RiskLevel.MEDIUM] = {
            "docker_restart_stateless_services",
            "scale_up_replicas",
            "update_configuration",
            "restart_worker_process",
        }
        self.safe_operations[RiskLevel.HIGH] = {
            "database_failover",
            "primary_ip_change",
            "ssl_certificate_renewal",
        }
    
    def check_permission(
        self,
        action: str,
        risk_level: RiskLevel,
        environment: str = "staging",
        config_overrides: Optional[Dict[str, bool]] = None,
    ) -> PermissionResult:
        """
        Check if an action can be auto-executed or requires approval.
        
        Args:
            action: Action identifier (e.g., "docker_restart_mongodb")
            risk_level: Risk level of the action
            environment: Deployment environment (staging/production)
            config_overrides: Per-environment permission overrides
        
        Returns:
            PermissionResult with decision and reason
        """
        config_overrides = config_overrides or {}
        
        # Check explicit config override first
        if action in config_overrides:
            allowed = config_overrides[action]
            return PermissionResult(
                result=allowed,
                reason=f"Config override: {action} is {'allowed' if allowed else 'blocked'} in {environment}"
            )
        
        # Check if action matches safe operations
        if self._is_safe_action(action, risk_level):
            return PermissionResult(
                result=True,
                reason=f"{action} is a known safe {risk_level.value} operation"
            )
        
        # Check prefix matching (e.g., "docker_restart_*")
        if self._matches_prefix(action, risk_level):
            return PermissionResult(
                result=True,
                reason=f"{action} matches safe prefix for {risk_level.value} operations"
            )
        
        # Unknown action - requires approval
        return PermissionResult(
            result=False,
            reason=f"{action} is not in safe operations list, requires approval"
        )
    
    def _is_safe_action(self, action: str, risk_level: RiskLevel) -> bool:
        """Check if action is in the safe operations list."""
        return action in self.safe_operations[risk_level]
    
    def _matches_prefix(self, action: str, risk_level: RiskLevel) -> bool:
        """Check if action matches a safe prefix (e.g., 'docker_restart_*')."""
        for safe_action in self.safe_operations[risk_level]:
            if safe_action.endswith('*'):
                prefix = safe_action.rstrip('*')
                if action.startswith(prefix):
                    return True
        return False
    
    def get_required_approval_time(self, risk_level: RiskLevel) -> int:
        """Get timeout (seconds) for approval by risk level."""
        timeouts = {
            RiskLevel.LOW: 0,        # Auto-execute, no approval
            RiskLevel.MEDIUM: 300,   # 5 minutes
            RiskLevel.HIGH: 0,       # No timeout, wait indefinitely
        }
        return timeouts[risk_level]
    
    def add_safe_operation(
        self,
        action: str,
        risk_level: RiskLevel,
    ) -> None:
        """Add an operation to the safe list (for dynamic configuration)."""
        self.safe_operations[risk_level].add(action)


# Approval thresholds (based on risk level)
APPROVAL_REQUIREMENTS = {
    RiskLevel.LOW: {
        "requires_approval": False,
        "timeout_seconds": 0,
        "description": "Auto-execute immediately, notify after",
    },
    RiskLevel.MEDIUM: {
        "requires_approval": True,
        "timeout_seconds": 300,  # 5 minutes
        "description": "Request approval, auto-deny on timeout",
    },
    RiskLevel.HIGH: {
        "requires_approval": True,
        "timeout_seconds": 0,  # No auto-timeout, wait forever
        "description": "Request explicit approval, no timeout",
    },
}


def should_auto_execute(risk_level: RiskLevel) -> bool:
    """Check if action should auto-execute without approval."""
    return not APPROVAL_REQUIREMENTS[risk_level]["requires_approval"]


def get_approval_timeout(risk_level: RiskLevel) -> int:
    """Get approval timeout (seconds) for risk level."""
    return APPROVAL_REQUIREMENTS[risk_level]["timeout_seconds"]
