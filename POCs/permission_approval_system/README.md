# POC 7: Permission & Approval System

Implements **critical permission and approval infrastructure** for safe tool execution in AutoOpsAI.

## Architecture

```
┌─────────────────────┐
│  Agent/User         │
│  (wants to execute) │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────────────┐
│ 1. Tool Registry                    │
│    - Metadata for all tools         │
│    - Risk classification            │
│    - Required permissions           │
└──────────┬────────────────────────┬─┘
           │                        │
           ▼                        ▼
┌──────────────────────┐  ┌──────────────────────┐
│ 2. Permission       │  │ 3. Approval         │
│    Manager          │  │    Workflow         │
│    - Allowlist      │  │    - Interactive    │
│    - Blocklist      │  │      prompts        │
│    - Auto-approve   │  │    - Risk-based     │
│                     │  │      timeouts       │
└──────────┬──────────┘  └──────────┬──────────┘
           │                        │
           └────────┬───────────────┘
                    │
                    ▼
         ┌──────────────────────┐
         │ 4. Audit Logger      │
         │    - JSONL audit     │
         │      trail           │
         │    - Compliance      │
         │      reports         │
         └──────────────────────┘
```

## Key Features

### 1. Tool Registry (`tool_registry.py`)
- **Centralized tool metadata** - Name, description, category, risk level
- **Risk classification** - READ_ONLY, LOW_RISK, MEDIUM_RISK, HIGH_RISK, BLOCKED
- **Permission requirements** - Granular permission model (e.g., `docker:write`, `docker:restart`)
- **Execution constraints** - Timeout, retry limits, dry-run capability
- **Safe parameter whitelist** - Restrict parameter values per tool

```python
from permission_approval_system.tool_registry import get_registry

registry = get_registry()
tool = registry.get('docker_restart_container')
print(tool.risk_level)  # HIGH_RISK
print(tool.required_permissions)  # ['docker:write', 'docker:restart']
```

### 2. Permission Manager (`permission_manager.py`)
- **Allowlist/blocklist** - Explicit tool permissions
- **Auto-approve safe commands** - Fast path for read-only operations
- **Permission grants** - Fine-grained user permissions
- **Configuration persistence** - Save/load user permissions to JSON

```python
from permission_approval_system.permission_manager import PermissionManager

manager = PermissionManager(registry)

# Check permission (returns PermissionResult)
result = manager.check_permission('docker_restart_container')
print(result.allowed)  # False
print(result.reason)   # "No permission to execute 'docker_restart_container'"

# Grant permission
manager.grant_permission('docker_restart_container')

# Save/load config
manager.save_config(Path('permissions.json'))
```

### 3. Approval Workflow (`approval_workflow.py`)
- **Interactive approval prompts** - Rich console UI with timeout
- **Risk-based timeouts** - More critical operations get longer approval windows
- **Auto-approval for safe ops** - Skip prompts for read-only tools
- **Custom handlers** - Pluggable approval logic (for testing/integration)
- **Audit trail** - Track all approval decisions

```python
from permission_approval_system.approval_workflow import ApprovalWorkflow

workflow = ApprovalWorkflow(
    interactive=True,
    auto_approve_read_only=True,
    timeout_seconds=300,
)

# Request approval
decision = await workflow.request_approval(
    tool_name='docker_restart_container',
    tool_meta=registry.get('docker_restart_container'),
    parameters={'container_name': 'flask-app'},
    reason='Restart stalled service',
)

print(decision.status)   # APPROVED, REJECTED, TIMEOUT, etc.
print(decision.method)   # USER_INTERACTIVE, AUTO, CONFIG, etc.

# Get audit report
report = workflow.get_audit_report()
```

### 4. Audit Logger (`audit_logger.py`)
- **JSONL-based audit trail** - Append-only, compliance-friendly
- **Event types** - Permission checks, approval requests, decisions, executions
- **Rich context** - User ID, session ID, risk level, parameters
- **Audit reports** - Summary statistics and detailed event history

```python
from permission_approval_system.audit_logger import AuditLogger

logger = AuditLogger(log_file=Path('audit.jsonl'))

logger.log_permission_check(
    tool_name='docker_restart_container',
    allowed=True,
    reason='Approved by user',
    source='user_interactive',
    user_id='user1',
    session_id='session1',
)

report = logger.get_report()
```

## Risk Levels & Approval Flow

| Risk Level | Description | Auto-Approval | Approval Timeout | Action Path |
|-----------|-------------|----------------|------------------|------------|
| **READ_ONLY** | Safe, informational only | ✅ Yes (if configured) | 60s | Execute immediately |
| **LOW_RISK** | Non-critical modifications | ❌ No | 120s | Interactive prompt |
| **MEDIUM_RISK** | Significant impact | ❌ No | 300s | Interactive prompt |
| **HIGH_RISK** | Destructive operations | ❌ No | 600s | Interactive prompt |
| **BLOCKED** | Not allowed | ❌ No | N/A | Reject immediately |

## Usage Examples

### Example 1: Basic Permission Check
```python
from permission_approval_system.tool_registry import get_registry
from permission_approval_system.permission_manager import PermissionManager

registry = get_registry()
manager = PermissionManager(registry)

# Safe commands are auto-approved
result = manager.check_permission('docker_list_containers')
assert result.allowed == True

# Dangerous commands are denied by default
result = manager.check_permission('docker_restart_container')
assert result.allowed == False

# Grant permission
manager.grant_permission('docker_restart_container')
result = manager.check_permission('docker_restart_container')
assert result.allowed == True
```

### Example 2: Interactive Approval Workflow
```python
import asyncio
from permission_approval_system.approval_workflow import ApprovalWorkflow

workflow = ApprovalWorkflow(interactive=True)

async def main():
    decision = await workflow.request_approval(
        tool_name='docker_restart_container',
        tool_meta=registry.get('docker_restart_container'),
        parameters={'container_name': 'mongodb'},
        reason='Restart failed MongoDB instance',
    )
    
    if decision.status.value == 'approved':
        print("✓ Tool execution approved!")
    else:
        print("✗ Tool execution rejected")

asyncio.run(main())
```

### Example 3: Persistent Configuration
```python
from pathlib import Path

# Save user permissions
manager = PermissionManager(registry)
manager.grant_permission('docker_restart_container')
manager.grant_user_permission('docker:write')
manager.save_config(Path('permissions.json'))

# Load in new session
manager2 = PermissionManager(registry, config_file=Path('permissions.json'))
# Permissions are preserved!
```

### Example 4: Audit Logging
```python
from permission_approval_system.audit_logger import AuditLogger

logger = AuditLogger(log_file=Path('audit.jsonl'))

# Log permission check
logger.log_permission_check(
    tool_name='docker_restart_container',
    allowed=True,
    reason='User approved',
    source='user_interactive',
)

# Generate compliance report
report = logger.get_report()
print(f"Total tool executions: {report['total_tools_executed']}")
print(f"Tools used: {report['unique_tools']}")
```

## Integration with Tool Execution

To integrate with the **tool_execution POC**, add permission checks before tool execution:

```python
# In agent.py
from permission_approval_system.permission_manager import PermissionManager
from permission_approval_system.tool_registry import get_registry

registry = get_registry()
permission_manager = PermissionManager(registry)
approval_workflow = ApprovalWorkflow(interactive=True)

async def run_agent(user_message: str):
    for tc in tool_calls:
        tool_name = tc["function"]["name"]
        tool_args = tc["function"].get("arguments", {})
        
        # 1. Check permissions
        perm_result = permission_manager.check_permission(tool_name, tool_args)
        if not perm_result.allowed:
            print(f"Permission denied: {perm_result.reason}")
            continue
        
        # 2. Request approval if needed
        tool_meta = registry.get(tool_name)
        decision = await approval_workflow.request_approval(
            tool_name,
            tool_meta,
            tool_args,
        )
        
        if decision.status != ApprovalStatus.APPROVED:
            print(f"Tool rejected: {decision.reason}")
            continue
        
        # 3. Execute tool
        result = execute_tool(tool_name, tool_args)
        
        # 4. Log execution
        audit_logger.log_tool_execution(
            tool_name,
            tool_args,
            success=result.success,
        )
```

## Demo

Run the complete demo:

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
uv run python -m POCs.permission_approval_system.demo
```

The demo covers:
1. **Tool Registry** - Explore all tools and their metadata
2. **Permission Manager** - Test allowlist/blocklist logic
3. **Approval Workflow** - Simulate user approvals
4. **Audit Logger** - View audit trail
5. **Configuration Persistence** - Save/load permissions

## Files

- `tool_registry.py` - Tool metadata and centralized registry
- `permission_manager.py` - Permission checking and configuration
- `approval_workflow.py` - Interactive approval system
- `audit_logger.py` - JSONL audit trail
- `demo.py` - Comprehensive demonstration

## Next Steps

### Integration Points
- ✅ Connect to **tool_execution** POC for agent-level approval
- ✅ Connect to **tiered_autonomy** POC for risk-based routing
- ✅ Connect to **approval_flow** POC for escalation workflows
- ✅ Connect to **playbook_matching** POC for playbook-level permissions

### Future Enhancements
- [ ] Role-based access control (RBAC)
- [ ] Time-based permission expiration
- [ ] Approval delegation and chains
- [ ] Risk scoring from tool parameters
- [ ] Integration with external identity providers
- [ ] Webhook support for external approval systems

## References

- Inspired by: `claude-code-sourcemap/src/permissions.ts`
- Risk classification: `tiered_autonomy/risk_classifier.py`
- Tool execution: `tool_execution/agent.py`
