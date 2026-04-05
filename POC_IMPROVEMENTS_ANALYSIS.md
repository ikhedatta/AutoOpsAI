# POC Improvements Analysis: Tool Execution Enhancement Roadmap

## Executive Summary

The current **tool_execution POC** provides a basic tool-calling loop with Ollama, but lacks several critical features present in the **claude-code-sourcemap** codebase. This document outlines key improvements to enhance security, reliability, auditability, and user experience.

---

## Current POC Architecture

### ✅ What's Working
- **Basic tool schema definition** (name, description, parameters)
- **Async tool calling loop** (request tools → execute → feedback loop)
- **Simple tool execution** (Docker, MongoDB)
- **Result formatting** (ToolResult dataclass)

### ❌ What's Missing
1. **Permission system** - No pre-execution permission checks
2. **Tool safety classification** - No risk assessment or categorization
3. **User approval workflow** - No interactive permission prompts
4. **Audit trail** - No logging of tool execution decisions
5. **Tool filtering/constraints** - No allowed tools allowlist
6. **Error handling** - Minimal error context propagation
7. **Tool introspection** - No tool metadata or availability checks
8. **Command safety validation** - No injection detection or sanitization

---

## Key Improvements by Category

### 1. **Permission & Approval System** ⚠️ HIGH PRIORITY

#### Claude-Code-Sourcemap Implementation
```typescript
// Permission types
export type PermissionResult = {
  result: boolean
  message?: string
}

// Tool-specific permission checks
export const bashToolHasPermission = async (
  tool: Tool,
  command: string,
  context: ToolUseContext,
  allowedTools: string[],
): Promise<PermissionResult>

// Exact match checking for safe commands
const SAFE_COMMANDS = new Set(['git status', 'git diff', 'pwd', ...])
```

#### POC Gaps
- No allowlist/blocklist for tools
- No distinction between "safe" vs "dangerous" operations
- No interactive user confirmation workflow
- No permission caching/persistence

#### Recommended Implementation
```python
# Add permission layer to POC
class PermissionManager:
    SAFE_TOOLS = {
        'docker_list_containers',
        'docker_inspect_container',
        'docker_container_logs',
        'mongodb_server_status',
        'mongodb_list_databases',
    }
    
    DESTRUCTIVE_TOOLS = {
        'docker_restart_container',  # High risk
        'docker_stop_container',
        'docker_remove_container',
    }
    
    async def check_permission(
        self,
        tool_name: str,
        parameters: dict,
        user_config: dict
    ) -> PermissionResult:
        """Check if user has approved this tool"""
        # 1. Check safe commands - auto-approve
        # 2. Check allowed_tools allowlist
        # 3. Ask user interactively (if interactive mode)
        pass
```

---

### 2. **Tool Metadata & Classification** 🏷️ MEDIUM PRIORITY

#### Claude-Code-Sourcemap Pattern
```typescript
export class Tool {
  name: string
  description: (input: unknown) => Promise<string>
  isReadOnly: () => boolean
  isEnabled: () => Promise<boolean>
  canProvideFeedback: () => boolean
  supportsApprovals: () => boolean
}

// Tool filtering based on capability
export const getReadOnlyTools = async (): Promise<Tool[]> => {
  return tools.filter(tool => tool.isReadOnly())
}
```

#### POC Enhancement
```python
from enum import Enum
from dataclasses import dataclass

class ToolRiskLevel(Enum):
    READ_ONLY = "read_only"        # Safe, informational
    LOW_RISK = "low_risk"           # May modify non-critical state
    HIGH_RISK = "high_risk"         # Destructive, requires approval
    BLOCKED = "blocked"             # Not allowed in this context

@dataclass
class ToolMetadata:
    name: str
    description: str
    risk_level: ToolRiskLevel
    required_permissions: list[str]
    tags: list[str]  # e.g., ['docker', 'monitoring', 'remediation']
    dry_run_capable: bool = False
    
    # New properties
    is_read_only: bool = False
    is_enabled: bool = True
    supportsApprovals: bool = True
    
class ToolRegistry:
    """Central registry for tool metadata"""
    
    TOOLS: dict[str, ToolMetadata] = {
        'docker_list_containers': ToolMetadata(
            name='docker_list_containers',
            description='List all Docker containers',
            risk_level=ToolRiskLevel.READ_ONLY,
            required_permissions=['docker:read'],
            tags=['docker', 'monitoring'],
            is_read_only=True,
        ),
        'docker_restart_container': ToolMetadata(
            name='docker_restart_container',
            description='Restart a container',
            risk_level=ToolRiskLevel.HIGH_RISK,
            required_permissions=['docker:write', 'docker:restart'],
            tags=['docker', 'remediation'],
            dry_run_capable=True,
            supportsApprovals=True,
        ),
    }
```

---

### 3. **User Approval Workflow** 📋 HIGH PRIORITY

#### Claude-Code-Sourcemap Pattern
```typescript
export type ToolUseConfirm = {
  assistantMessage: AssistantMessage
  tool: Tool
  description: string
  input: Record<string, unknown>
  commandPrefix: CommandSubcommandPrefix | null
  riskScore: number | null
  onAbort: () => void
  onApprove: () => void
}

// Interactive permission prompt with risk assessment
const useCanUseTool = async (tool, input, context) => {
  const result = await hasPermissionsToUseTool(...)
  if (!result.result) {
    // Show interactive dialog to user
    setToolUseConfirm({...})
  }
}
```

#### POC Enhancement
```python
from typing import Callable

class ApprovalWorkflow:
    """Interactive user approval system"""
    
    def __init__(self, interactive: bool = True):
        self.interactive = interactive
        self.approval_history = []
    
    async def request_approval(
        self,
        tool_name: str,
        parameters: dict,
        risk_level: ToolRiskLevel,
        reason: str = None
    ) -> bool:
        """Request user approval for tool execution"""
        
        approval_request = {
            'tool_name': tool_name,
            'parameters': parameters,
            'risk_level': risk_level.value,
            'timestamp': datetime.now(),
            'reason': reason,
        }
        
        if self.interactive and risk_level in [
            ToolRiskLevel.HIGH_RISK,
            ToolRiskLevel.LOW_RISK,
        ]:
            # Show interactive prompt
            approved = await self._prompt_user(approval_request)
        else:
            # Auto-approve read-only operations
            approved = risk_level == ToolRiskLevel.READ_ONLY
        
        # Log approval decision
        self.approval_history.append({
            **approval_request,
            'approved': approved,
        })
        
        return approved
    
    async def _prompt_user(self, request: dict) -> bool:
        """Interactive console prompt"""
        print(f"\n🔐 Permission Request")
        print(f"   Tool: {request['tool_name']}")
        print(f"   Risk: {request['risk_level']}")
        print(f"   Params: {request['parameters']}")
        
        response = input("\nAllow? (y/n/always): ").lower()
        return response in ['y', 'yes', 'always']
    
    def get_approval_report(self) -> dict:
        """Generate audit report of approvals"""
        return {
            'total_requests': len(self.approval_history),
            'approved': sum(1 for h in self.approval_history if h['approved']),
            'rejected': sum(1 for h in self.approval_history if not h['approved']),
            'history': self.approval_history,
        }
```

---

### 4. **Audit Trail & Logging** 📊 MEDIUM-HIGH PRIORITY

#### Claude-Code-Sourcemap Pattern
```typescript
logEvent('tengu_tool_use_granted_in_config', {
  messageID: assistantMessage.message.id,
  toolName: tool.name,
})

logEvent('tengu_tool_use_rejected_in_prompt', {
  messageID: assistantMessage.message.id,
  toolName: tool.name,
})
```

#### POC Enhancement
```python
import logging
from datetime import datetime
import json

class AuditLogger:
    """Comprehensive audit logging for tool execution"""
    
    def __init__(self, log_file: str = "tool_audit.jsonl"):
        self.log_file = log_file
        self.logger = logging.getLogger("tool_audit")
        handler = logging.FileHandler(log_file)
        handler.setFormatter(
            logging.Formatter('%(message)s')
        )
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)
    
    def log_tool_request(
        self,
        tool_name: str,
        parameters: dict,
        user_id: str = None,
        reason: str = None,
    ):
        """Log when tool is requested"""
        event = {
            'type': 'tool_request',
            'timestamp': datetime.utcnow().isoformat(),
            'tool_name': tool_name,
            'parameters': parameters,
            'user_id': user_id,
            'reason': reason,
        }
        self.logger.info(json.dumps(event))
    
    def log_permission_granted(
        self,
        tool_name: str,
        source: str,  # "config", "user_approval", "auto"
        approval_method: str = None,
    ):
        """Log permission grant"""
        event = {
            'type': 'permission_granted',
            'timestamp': datetime.utcnow().isoformat(),
            'tool_name': tool_name,
            'source': source,
            'approval_method': approval_method,
        }
        self.logger.info(json.dumps(event))
    
    def log_tool_execution(
        self,
        tool_name: str,
        parameters: dict,
        result: ToolResult,
        duration_ms: float,
    ):
        """Log tool execution and result"""
        event = {
            'type': 'tool_execution',
            'timestamp': datetime.utcnow().isoformat(),
            'tool_name': tool_name,
            'parameters': parameters,
            'success': result.success,
            'error': result.error,
            'duration_ms': duration_ms,
        }
        self.logger.info(json.dumps(event))
    
    def log_permission_denied(
        self,
        tool_name: str,
        reason: str,
        user_action: str = None,  # "rejected", "timeout", "config_blocked"
    ):
        """Log permission denial"""
        event = {
            'type': 'permission_denied',
            'timestamp': datetime.utcnow().isoformat(),
            'tool_name': tool_name,
            'reason': reason,
            'user_action': user_action,
        }
        self.logger.info(json.dumps(event))
```

---

### 5. **Tool Execution Context & Safety** 🛡️ MEDIUM PRIORITY

#### Claude-Code-Sourcemap Pattern
```typescript
export type ToolUseContext = {
  abortController: AbortController
  signal: AbortSignal
  isRetry: boolean
  toolIndex: number
  totalTools: number
}

export type ToolUseRequest = {
  tool: Tool
  input: unknown
  context: ToolUseContext
}
```

#### POC Enhancement
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class ExecutionContext:
    """Rich execution context for tool calls"""
    
    tool_name: str
    started_at: datetime = field(default_factory=datetime.utcnow)
    approval_method: str = None  # "auto", "user", "config"
    dry_run: bool = False
    timeout_seconds: int = 300
    can_retry: bool = True
    max_retries: int = 3
    
    # For safety
    sandbox_enabled: bool = True
    resource_limits: dict = field(default_factory=dict)  # cpu, memory, timeout
    
    # For tracking
    invocation_id: str = None
    user_id: str = None
    session_id: str = None

class SafeToolExecutor(ABC):
    """Abstract base for safe tool execution"""
    
    @abstractmethod
    async def execute(
        self,
        tool_name: str,
        parameters: dict,
        context: ExecutionContext,
    ) -> ToolResult:
        """Execute tool with safety guardrails"""
        pass
    
    async def execute_with_timeout(
        self,
        tool_name: str,
        parameters: dict,
        timeout_seconds: int = 300,
    ) -> ToolResult:
        """Execute tool with timeout protection"""
        try:
            # Implementation with asyncio.wait_for
            pass
        except asyncio.TimeoutError:
            return ToolResult(
                tool=tool_name,
                success=False,
                output=None,
                error=f"Tool execution timed out after {timeout_seconds}s"
            )
    
    async def validate_parameters(
        self,
        tool_name: str,
        parameters: dict,
    ) -> tuple[bool, str]:
        """Validate tool parameters for safety"""
        # Check for injection attempts
        # Validate parameter types
        # Check for dangerous patterns
        pass
```

---

### 6. **Dry-Run / Preview Mode** 🔍 LOW-MEDIUM PRIORITY

#### POC Enhancement
```python
class DryRunCapability:
    """Support for previewing tool execution without side effects"""
    
    @dataclass
    class DryRunResult:
        would_succeed: bool
        predicted_output: Any
        side_effects: list[str]
        warnings: list[str]
    
    async def dry_run_docker_restart(
        self,
        container_name: str,
    ) -> DryRunResult:
        """Preview what would happen without actually restarting"""
        client = _get_docker_client()
        try:
            container = client.containers.get(container_name)
            return DryRunResult(
                would_succeed=True,
                predicted_output=f"Would restart container: {container.name}",
                side_effects=[
                    f"Container {container.name} would be stopped",
                    f"Container would be started again",
                    "Brief service interruption (~5-10 seconds)",
                ],
                warnings=[
                    "Running operations in container would be interrupted",
                    "Stateful data not persisted to disk would be lost",
                ]
            )
        except Exception as e:
            return DryRunResult(
                would_succeed=False,
                predicted_output=None,
                side_effects=[],
                warnings=[f"Container not found: {str(e)}"]
            )
```

---

### 7. **Tool Result Enhancement** 📦 LOW PRIORITY

#### Enhancement
```python
@dataclass
class EnhancedToolResult:
    tool: str
    success: bool
    output: Any
    error: str | None = None
    
    # New fields
    execution_time_ms: float = None
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    related_tools: list[str] = field(default_factory=list)  # Suggest follow-up tools
    severity_level: str = None  # "info", "warning", "error", "critical"
    
    def to_dict(self) -> dict:
        """Serialize for response to LLM"""
        return {
            'tool': self.tool,
            'success': self.success,
            'output': self.output,
            'error': self.error,
            'warnings': self.warnings,
            'recommendations': self.recommendations,
            'execution_time_ms': self.execution_time_ms,
        }
```

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1-2)
- [ ] **ToolRegistry & ToolMetadata** - Centralized tool definitions
- [ ] **ToolRiskLevel classification** - Categorize tools by safety
- [ ] **AuditLogger** - Basic execution logging

### Phase 2: Permission System (Week 2-3)
- [ ] **PermissionManager** - Permission checking logic
- [ ] **AllowedTools allowlist** - User configuration
- [ ] **Safe commands detection** - Pre-defined safe operations

### Phase 3: User Experience (Week 3-4)
- [ ] **ApprovalWorkflow** - Interactive approval prompts
- [ ] **CLI/UI integration** - Show approval dialogs
- [ ] **Permission caching** - Remember user decisions

### Phase 4: Safety & Observability (Week 4-5)
- [ ] **ExecutionContext** - Rich context for executions
- [ ] **Timeout/resource limits** - Execution guardrails
- [ ] **Enhanced ToolResult** - Better feedback to LLM

### Phase 5: Advanced Features (Week 5-6)
- [ ] **Dry-run mode** - Preview tool execution
- [ ] **Command injection detection** - Validate parameters
- [ ] **Tool recommendations** - Suggest follow-up tools

---

## Code Organization

### Suggested Directory Structure
```
POCs/tool_execution/
├── agent.py              # Core agent loop (enhanced)
├── tools.py              # Tool definitions & executors
├── demo.py               # Demo scenarios
├── README.md             # POC documentation
│
├── permissions/
│   ├── __init__.py
│   ├── manager.py        # Permission checking
│   ├── workflow.py       # User approval workflow
│   └── approved_tools_config.py
│
├── safety/
│   ├── __init__.py
│   ├── executor.py       # SafeToolExecutor base class
│   ├── validator.py      # Parameter validation
│   └── context.py        # ExecutionContext
│
├── audit/
│   ├── __init__.py
│   ├── logger.py         # AuditLogger
│   └── reporters.py      # Audit report generation
│
└── registry/
    ├── __init__.py
    ├── metadata.py       # ToolMetadata, ToolRiskLevel
    └── catalog.py        # ToolRegistry
```

---

## Key Design Patterns from Claude-Code-Sourcemap

| Feature | Pattern | Benefits |
|---------|---------|----------|
| **Tool Abstraction** | Base `Tool` class with methods (`isReadOnly()`, `isEnabled()`) | Consistent interface, easy extension |
| **Permission Composition** | Multiple permission layers (exact match → prefix → full path) | Flexible, granular control |
| **Risk Assessment** | `riskScore` field in approval request | Inform user of danger level |
| **Event Logging** | Structured event logs with context | Auditability, debugging |
| **Async Patterns** | Async/await with cancellation support | Non-blocking, responsive UI |
| **Config Persistence** | Save allowed tools in project config | Per-project approval settings |

---

## Security Considerations

1. **Command Injection Prevention**
   - Validate parameters against schema
   - Sanitize string inputs
   - Use parameter passing, not shell interpolation

2. **Approval Bypass Prevention**
   - Log all execution attempts
   - Require explicit approval for dangerous operations
   - Don't cache sensitive decisions indefinitely

3. **Sandboxing**
   - Limit resource consumption (CPU, memory, timeout)
   - Restrict file access to safe directories
   - Use Docker/container isolation where possible

4. **Audit Trail Integrity**
   - Append-only audit logs
   - Include timestamps and user context
   - Regular backup/export

---

## Integration Points with AutoOpsAI

These improvements enable:
- ✅ **Autonomy levels** (tiered_autonomy POC) - Different approval workflows per tier
- ✅ **Approval flows** (approval_flow POC) - Structured approval requests
- ✅ **Remediation loops** (remediation_loop POC) - Safety gates on auto-remediation
- ✅ **Playbook execution** (playbook_matching POC) - Pre-approved playbook tool sets

---

## Conclusion

The enhanced tool execution framework transforms the POC from a simple LLM interface into a **production-ready, secure tool-calling system** with:
- **Granular permission control**
- **Full audit trail**
- **User oversight & approval**
- **Risk assessment & safety gates**
- **Rich execution context**

This foundation enables AutoOpsAI to safely scale autonomous operations across diverse infrastructure environments.
