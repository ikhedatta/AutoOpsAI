"""
Permission Manager

Handles permission checking, allowlist/blocklist management, and
user configuration for tool execution authorization.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .tool_registry import ToolRegistry, ToolRiskLevel


@dataclass
class PermissionResult:
    """Result of a permission check."""
    allowed: bool
    reason: str = ""
    source: str = ""  # "config", "safe_command", "blocklist", "denied"


@dataclass
class UserPermissionConfig:
    """User's permission configuration."""
    
    # Allowlist: explicitly allowed tools
    allowed_tools: list[str] = field(default_factory=list)
    
    # Blocklist: explicitly blocked tools
    blocked_tools: list[str] = field(default_factory=list)
    
    # Permissions granted to user
    granted_permissions: list[str] = field(default_factory=list)
    
    # Auto-approval for safe operations
    auto_approve_read_only: bool = True
    
    # Interactive mode
    interactive_approval: bool = True
    
    # Approval timeout (seconds)
    approval_timeout: int = 300
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            'allowed_tools': self.allowed_tools,
            'blocked_tools': self.blocked_tools,
            'granted_permissions': self.granted_permissions,
            'auto_approve_read_only': self.auto_approve_read_only,
            'interactive_approval': self.interactive_approval,
            'approval_timeout': self.approval_timeout,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> UserPermissionConfig:
        """Deserialize from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class PermissionManager:
    """Manages tool execution permissions."""
    
    # Safe commands that are auto-approved
    SAFE_COMMANDS = {
        'docker_list_containers',
        'docker_inspect_container',
        'docker_container_logs',
        'docker_container_stats',
        'mongodb_server_status',
        'mongodb_list_databases',
        'mongodb_current_operations',
    }
    
    def __init__(
        self,
        registry: ToolRegistry,
        config: Optional[UserPermissionConfig] = None,
        config_file: Optional[Path] = None,
    ):
        """
        Initialize permission manager.
        
        Args:
            registry: Tool registry for metadata
            config: User permission configuration
            config_file: Optional path to load/save config from/to
        """
        self.registry = registry
        self.config = config or UserPermissionConfig()
        self.config_file = config_file
        
        # Load config from file if provided
        if config_file and config_file.exists():
            self.load_config(config_file)
    
    def check_permission(
        self,
        tool_name: str,
        parameters: Optional[dict] = None,
    ) -> PermissionResult:
        """
        Check if a tool can be executed.
        
        Returns permission result with reason and source.
        Priority:
        1. Check blocklist (deny)
        2. Check if tool is safe (auto-approve if configured)
        3. Check explicit allowlist
        4. Check permission grants
        5. Deny by default
        """
        # 1. Check if tool exists
        if not self.registry.exists(tool_name):
            return PermissionResult(
                allowed=False,
                reason=f"Tool '{tool_name}' not found in registry",
                source="unknown",
            )
        
        # 2. Check blocklist (highest priority)
        if tool_name in self.config.blocked_tools:
            return PermissionResult(
                allowed=False,
                reason=f"Tool '{tool_name}' is blocked",
                source="blocklist",
            )
        
        # 3. Check safe commands (auto-approve if configured)
        if tool_name in self.SAFE_COMMANDS:
            if self.config.auto_approve_read_only:
                return PermissionResult(
                    allowed=True,
                    reason=f"Tool '{tool_name}' is safe (read-only)",
                    source="safe_command",
                )
        
        # 4. Check explicit allowlist
        if tool_name in self.config.allowed_tools:
            return PermissionResult(
                allowed=True,
                reason=f"Tool '{tool_name}' is in allowlist",
                source="config",
            )
        
        # 5. Check if user has required permissions
        tool_meta = self.registry.get(tool_name)
        if tool_meta:
            missing_perms = [
                p for p in tool_meta.required_permissions
                if p not in self.config.granted_permissions
            ]
            
            if not missing_perms:
                return PermissionResult(
                    allowed=True,
                    reason=f"User has all required permissions: {tool_meta.required_permissions}",
                    source="permissions",
                )
        
        # 6. Deny by default
        return PermissionResult(
            allowed=False,
            reason=f"No permission to execute '{tool_name}'",
            source="denied",
        )
    
    def grant_permission(self, tool_name: str) -> None:
        """Add tool to allowlist."""
        if tool_name not in self.config.allowed_tools:
            self.config.allowed_tools.append(tool_name)
    
    def revoke_permission(self, tool_name: str) -> None:
        """Remove tool from allowlist."""
        if tool_name in self.config.allowed_tools:
            self.config.allowed_tools.remove(tool_name)
    
    def block_tool(self, tool_name: str) -> None:
        """Add tool to blocklist."""
        if tool_name not in self.config.blocked_tools:
            self.config.blocked_tools.append(tool_name)
    
    def unblock_tool(self, tool_name: str) -> None:
        """Remove tool from blocklist."""
        if tool_name in self.config.blocked_tools:
            self.config.blocked_tools.remove(tool_name)
    
    def grant_user_permission(self, permission: str) -> None:
        """Grant a permission to user."""
        if permission not in self.config.granted_permissions:
            self.config.granted_permissions.append(permission)
    
    def revoke_user_permission(self, permission: str) -> None:
        """Revoke a permission from user."""
        if permission in self.config.granted_permissions:
            self.config.granted_permissions.remove(permission)
    
    def get_allowed_tools(self) -> list[str]:
        """Get list of tools user can execute."""
        allowed = []
        for tool_meta in self.registry.get_enabled_tools():
            result = self.check_permission(tool_meta.name)
            if result.allowed:
                allowed.append(tool_meta.name)
        return allowed
    
    def get_blocked_tools(self) -> list[str]:
        """Get list of tools user cannot execute."""
        return self.config.blocked_tools.copy()
    
    def save_config(self, config_file: Optional[Path] = None) -> None:
        """Save configuration to file."""
        path = config_file or self.config_file
        if not path:
            raise ValueError("No config file path provided")
        
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(self.config.to_dict(), f, indent=2)
    
    def load_config(self, config_file: Path) -> None:
        """Load configuration from file."""
        with open(config_file, 'r') as f:
            data = json.load(f)
        
        self.config = UserPermissionConfig.from_dict(data)
        self.config_file = config_file
    
    def get_status_summary(self) -> dict:
        """Get summary of permission status."""
        return {
            'allowed_tools': len(self.config.allowed_tools),
            'blocked_tools': len(self.config.blocked_tools),
            'granted_permissions': len(self.config.granted_permissions),
            'auto_approve_read_only': self.config.auto_approve_read_only,
            'interactive_approval': self.config.interactive_approval,
            'approval_timeout': self.config.approval_timeout,
        }
