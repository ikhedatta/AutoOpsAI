"""
POC #4: Configuration State Management

Hierarchical config loading: defaults → environment → playbook
- Global defaults
- Environment-specific overrides (staging/production)
- Per-playbook configuration
- Safe defaults prevent accidents
"""

from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional
import yaml
import os


@dataclass
class RiskLevelPolicy:
    """Policy for a single risk level."""
    requires_approval: bool
    timeout_seconds: int
    auto_execute: bool = None
    
    def __post_init__(self):
        if self.auto_execute is None:
            self.auto_execute = not self.requires_approval


@dataclass
class EnvironmentConfig:
    """Configuration for a deployment environment."""
    name: str  # dev, staging, production
    approval_policy: Dict[str, Any]
    auto_execute_operations: Dict[str, list] = None  # Per risk level
    safe_operations_only: bool = False  # If True, only allow whitelisted ops
    require_multi_approval: Dict[str, int] = None  # Risk level -> min approvals
    incident_store_path: str = "./incidents.db"
    playbooks_dir: str = "./playbooks"
    audit_log_path: str = "./audit.log"
    max_remediation_cost: Optional[float] = None
    
    def __post_init__(self):
        """Set defaults for optional fields."""
        if self.auto_execute_operations is None:
            self.auto_execute_operations = {
                "LOW": ["redis_memory_purge", "log_rotation"],
                "MEDIUM": ["docker_restart_stateless"],
                "HIGH": [],
            }
        
        if self.require_multi_approval is None:
            self.require_multi_approval = {
                "LOW": 0,
                "MEDIUM": 1,
                "HIGH": 2 if self.name == "production" else 1,
            }


class ConfigManager:
    """
    Hierarchical configuration loader.
    
    Load order:
    1. Built-in defaults
    2. Global config file
    3. Environment-specific config
    4. Playbook-specific overrides
    """
    
    # Built-in defaults
    DEFAULT_CONFIG = {
        "approval_policy": {
            "LOW": {
                "requires_approval": False,
                "timeout_seconds": 0,
            },
            "MEDIUM": {
                "requires_approval": True,
                "timeout_seconds": 300,
            },
            "HIGH": {
                "requires_approval": True,
                "timeout_seconds": 0,
            },
        },
        "auto_execute_operations": {
            "LOW": ["redis_memory_purge", "log_rotation"],
            "MEDIUM": [],
            "HIGH": [],
        },
        "safe_operations_only": False,
        "require_multi_approval": {
            "LOW": 0,
            "MEDIUM": 1,
            "HIGH": 2,
        },
    }
    
    def __init__(self, config_dir: str = "./config"):
        """
        Initialize config manager.
        
        Args:
            config_dir: Directory containing config files
        """
        self.config_dir = config_dir
        self.environments: Dict[str, EnvironmentConfig] = {}
        self._load_all_configs()
    
    def _load_all_configs(self) -> None:
        """Load all environment configs."""
        for env_name in ["staging", "production"]:
            self.environments[env_name] = self._load_environment_config(env_name)
    
    def _load_environment_config(self, environment: str) -> EnvironmentConfig:
        """Load config for a specific environment."""
        config = self.DEFAULT_CONFIG.copy()
        
        # Load environment-specific config file
        env_config_file = os.path.join(self.config_dir, f"{environment}.yaml")
        if os.path.exists(env_config_file):
            with open(env_config_file, 'r') as f:
                env_overrides = yaml.safe_load(f) or {}
                config.update(env_overrides)
        
        return EnvironmentConfig(
            name=environment,
            **config,
        )
    
    def get_config(self, environment: str) -> EnvironmentConfig:
        """Get configuration for an environment."""
        if environment not in self.environments:
            raise ValueError(f"Unknown environment: {environment}")
        return self.environments[environment]
    
    def get_approval_policy(
        self,
        environment: str,
        risk_level: str,
    ) -> Dict[str, Any]:
        """Get approval policy for a risk level."""
        config = self.get_config(environment)
        return config.approval_policy.get(risk_level, {})
    
    def requires_approval(self, environment: str, risk_level: str) -> bool:
        """Check if approval is required for risk level."""
        policy = self.get_approval_policy(environment, risk_level)
        return policy.get("requires_approval", False)
    
    def get_approval_timeout(self, environment: str, risk_level: str) -> int:
        """Get approval timeout for risk level."""
        policy = self.get_approval_policy(environment, risk_level)
        return policy.get("timeout_seconds", 0)
    
    def is_operation_safe(
        self,
        environment: str,
        operation: str,
        risk_level: str,
    ) -> bool:
        """Check if operation is in safe list for environment."""
        config = self.get_config(environment)
        safe_ops = config.auto_execute_operations.get(risk_level, [])
        
        # Check exact match
        if operation in safe_ops:
            return True
        
        # Check prefix match (e.g., "docker_*")
        for safe_op in safe_ops:
            if safe_op.endswith("*"):
                prefix = safe_op.rstrip("*")
                if operation.startswith(prefix):
                    return True
        
        return False
    
    def get_multi_approval_count(self, environment: str, risk_level: str) -> int:
        """Get required number of approvals for risk level."""
        config = self.get_config(environment)
        return config.require_multi_approval.get(risk_level, 1)
    
    def override_policy(
        self,
        environment: str,
        risk_level: str,
        requires_approval: Optional[bool] = None,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        """Override approval policy for a risk level (runtime)."""
        config = self.get_config(environment)
        
        if requires_approval is not None:
            config.approval_policy[risk_level]["requires_approval"] = requires_approval
        
        if timeout_seconds is not None:
            config.approval_policy[risk_level]["timeout_seconds"] = timeout_seconds
    
    def to_dict(self, environment: str) -> Dict[str, Any]:
        """Export configuration as dictionary."""
        config = self.get_config(environment)
        return asdict(config)
    
    def to_yaml(self, environment: str) -> str:
        """Export configuration as YAML."""
        config = self.to_dict(environment)
        return yaml.dump(config, default_flow_style=False)


# Singleton instance
_config_manager = None


def get_config_manager(config_dir: str = "./config") -> ConfigManager:
    """Get or create config manager singleton."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager(config_dir)
    return _config_manager


def reset_config_manager() -> None:
    """Reset config manager (for testing)."""
    global _config_manager
    _config_manager = None
