"""
Tool Registry & Metadata

Centralized registry of all available tools with their safety characteristics,
permissions requirements, and risk classification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolRiskLevel(str, Enum):
    """Risk level classification for tools."""
    READ_ONLY = "read_only"        # Safe, informational only
    LOW_RISK = "low_risk"           # May modify non-critical state
    MEDIUM_RISK = "medium_risk"     # Significant impact, needs review
    HIGH_RISK = "high_risk"         # Destructive, requires explicit approval
    BLOCKED = "blocked"             # Not allowed in this context


@dataclass
class ToolMetadata:
    """Complete metadata for a tool."""
    
    # Basic info
    name: str
    description: str
    category: str  # e.g., 'docker', 'mongodb', 'kubernetes'
    
    # Safety & Risk
    risk_level: ToolRiskLevel
    tags: list[str] = field(default_factory=list)
    
    # Permissions
    required_permissions: list[str] = field(default_factory=list)
    
    # Capabilities
    is_read_only: bool = False
    is_enabled: bool = True
    dry_run_capable: bool = False
    supports_approval: bool = True
    
    # Execution constraints
    timeout_seconds: int = 300
    max_retries: int = 0
    
    # Safety
    safe_parameters: dict[str, list[str]] = field(default_factory=dict)
    """Whitelisted parameter values per argument. e.g., {'container': ['redis', 'postgres']}"""
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            'name': self.name,
            'description': self.description,
            'category': self.category,
            'risk_level': self.risk_level.value,
            'tags': self.tags,
            'required_permissions': self.required_permissions,
            'is_read_only': self.is_read_only,
            'dry_run_capable': self.dry_run_capable,
            'timeout_seconds': self.timeout_seconds,
        }


class ToolRegistry:
    """Central registry for all tools and their metadata."""
    
    def __init__(self):
        self._tools: dict[str, ToolMetadata] = {}
        self._register_default_tools()
    
    def _register_default_tools(self):
        """Register default Docker and MongoDB tools."""
        
        # Docker tools - READ_ONLY
        self.register(ToolMetadata(
            name='docker_list_containers',
            description='List all Docker containers with their status, image, and ports.',
            category='docker',
            risk_level=ToolRiskLevel.READ_ONLY,
            tags=['docker', 'monitoring', 'read-only'],
            required_permissions=['docker:read'],
            is_read_only=True,
        ))
        
        self.register(ToolMetadata(
            name='docker_inspect_container',
            description='Get detailed info about a specific Docker container (state, config, network).',
            category='docker',
            risk_level=ToolRiskLevel.READ_ONLY,
            tags=['docker', 'monitoring', 'read-only'],
            required_permissions=['docker:read'],
            is_read_only=True,
        ))
        
        self.register(ToolMetadata(
            name='docker_container_logs',
            description='Retrieve recent logs from a Docker container.',
            category='docker',
            risk_level=ToolRiskLevel.READ_ONLY,
            tags=['docker', 'monitoring', 'read-only'],
            required_permissions=['docker:read'],
            is_read_only=True,
        ))
        
        self.register(ToolMetadata(
            name='docker_container_stats',
            description='Get CPU, memory, and network stats for a running Docker container.',
            category='docker',
            risk_level=ToolRiskLevel.READ_ONLY,
            tags=['docker', 'monitoring', 'read-only'],
            required_permissions=['docker:read'],
            is_read_only=True,
        ))
        
        # Docker tools - HIGH_RISK (destructive)
        self.register(ToolMetadata(
            name='docker_restart_container',
            description='Restart a Docker container. Use when remediation requires a container restart.',
            category='docker',
            risk_level=ToolRiskLevel.HIGH_RISK,
            tags=['docker', 'remediation', 'destructive'],
            required_permissions=['docker:write', 'docker:restart'],
            dry_run_capable=True,
            supports_approval=True,
        ))
        
        self.register(ToolMetadata(
            name='docker_stop_container',
            description='Stop a Docker container.',
            category='docker',
            risk_level=ToolRiskLevel.HIGH_RISK,
            tags=['docker', 'remediation', 'destructive'],
            required_permissions=['docker:write', 'docker:stop'],
            dry_run_capable=True,
            supports_approval=True,
        ))
        
        self.register(ToolMetadata(
            name='docker_remove_container',
            description='Remove a Docker container.',
            category='docker',
            risk_level=ToolRiskLevel.HIGH_RISK,
            tags=['docker', 'remediation', 'destructive'],
            required_permissions=['docker:write', 'docker:remove'],
            dry_run_capable=True,
            supports_approval=True,
        ))
        
        # MongoDB tools - READ_ONLY
        self.register(ToolMetadata(
            name='mongodb_server_status',
            description='Get MongoDB server status including connections, opcounters, memory, and uptime.',
            category='mongodb',
            risk_level=ToolRiskLevel.READ_ONLY,
            tags=['mongodb', 'monitoring', 'read-only'],
            required_permissions=['mongodb:read'],
            is_read_only=True,
        ))
        
        self.register(ToolMetadata(
            name='mongodb_list_databases',
            description='List all MongoDB databases with their sizes.',
            category='mongodb',
            risk_level=ToolRiskLevel.READ_ONLY,
            tags=['mongodb', 'monitoring', 'read-only'],
            required_permissions=['mongodb:read'],
            is_read_only=True,
        ))
        
        self.register(ToolMetadata(
            name='mongodb_current_operations',
            description='List currently running MongoDB operations. Useful for finding slow or stuck queries.',
            category='mongodb',
            risk_level=ToolRiskLevel.READ_ONLY,
            tags=['mongodb', 'monitoring', 'read-only'],
            required_permissions=['mongodb:read'],
            is_read_only=True,
        ))
        
        # MongoDB tools - MEDIUM_RISK
        self.register(ToolMetadata(
            name='mongodb_kill_operation',
            description='Kill a running MongoDB operation.',
            category='mongodb',
            risk_level=ToolRiskLevel.MEDIUM_RISK,
            tags=['mongodb', 'remediation', 'moderate-risk'],
            required_permissions=['mongodb:write', 'mongodb:killOp'],
            dry_run_capable=True,
            supports_approval=True,
        ))
    
    def register(self, metadata: ToolMetadata) -> None:
        """Register a tool in the registry."""
        self._tools[metadata.name] = metadata
    
    def get(self, tool_name: str) -> ToolMetadata | None:
        """Get tool metadata by name."""
        return self._tools.get(tool_name)
    
    def get_all(self) -> dict[str, ToolMetadata]:
        """Get all registered tools."""
        return self._tools.copy()
    
    def get_enabled_tools(self) -> list[ToolMetadata]:
        """Get all enabled tools."""
        return [t for t in self._tools.values() if t.is_enabled]
    
    def get_by_category(self, category: str) -> list[ToolMetadata]:
        """Get tools by category."""
        return [t for t in self._tools.values() if t.category == category]
    
    def get_by_risk_level(self, risk_level: ToolRiskLevel) -> list[ToolMetadata]:
        """Get tools by risk level."""
        return [t for t in self._tools.values() if t.risk_level == risk_level]
    
    def get_read_only_tools(self) -> list[ToolMetadata]:
        """Get all read-only tools."""
        return [t for t in self._tools.values() if t.is_read_only]
    
    def exists(self, tool_name: str) -> bool:
        """Check if tool is registered."""
        return tool_name in self._tools
    
    def is_safe_command(self, tool_name: str) -> bool:
        """Check if tool is a safe (read-only) command."""
        tool = self.get(tool_name)
        return tool is not None and tool.risk_level == ToolRiskLevel.READ_ONLY


# Global registry instance
_registry = None


def get_registry() -> ToolRegistry:
    """Get or create global tool registry."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
