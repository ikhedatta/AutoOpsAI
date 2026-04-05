# Integration Guide: Permission & Approval System

This guide shows how to integrate **POC 7 (Permission & Approval System)** with the existing **POC 3 (Tool Execution)** agent to add granular permission control and interactive approval workflows.

## Overview

The permission & approval system sits between the agent's tool-calling loop and actual tool execution, providing:

1. **Permission Checks** - Verify user has access to tool
2. **Risk Assessment** - Classify tool by risk level
3. **User Approval** - Interactive prompts for dangerous operations
4. **Audit Trail** - Complete JSONL logging of decisions

## Integration Steps

### Step 1: Add Imports to agent.py

```python
# At top of POCs/tool_execution/agent.py
from permission_approval_system.tool_registry import get_registry
from permission_approval_system.permission_manager import PermissionManager
from permission_approval_system.approval_workflow import ApprovalWorkflow, ApprovalStatus
from permission_approval_system.audit_logger import AuditLogger
```

### Step 2: Initialize Permission System

```python
# In run_agent() function, before starting the loop:

async def run_agent(
    user_message: str,
    max_iterations: int = 10,
    interactive: bool = True,  # NEW: Enable interactive approval
) -> AgentRun:
    """
    Run the tool-calling agent loop with permission checking.
    """
    run = AgentRun(user_message=user_message)
    
    # NEW: Initialize permission system
    registry = get_registry()
    permission_manager = PermissionManager(registry)
    approval_workflow = ApprovalWorkflow(
        interactive=interactive,
        auto_approve_read_only=True,
    )
    audit_logger = AuditLogger()  # Optional: log_file=Path('audit.jsonl')
    
    # Rest of agent initialization...
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    
    # ... continue with agent loop
```

### Step 3: Add Permission Checking to Tool Execution

```python
# In the tool execution loop (where we process tool_calls):

for tc in tool_calls:
    func = tc["function"]
    tool_name = func["name"]
    tool_args = func.get("arguments", {})
    
    # ========== NEW: Permission & Approval Logic ==========
    
    # 1. Check if tool exists in registry
    if not registry.exists(tool_name):
        messages.append({
            "role": "tool",
            "content": json.dumps({
                "success": False,
                "error": f"Tool '{tool_name}' not found in registry"
            })
        })
        continue
    
    # 2. Check user permissions
    perm_result = permission_manager.check_permission(tool_name)
    
    audit_logger.log_permission_check(
        tool_name,
        perm_result.allowed,
        perm_result.reason,
        perm_result.source,
    )
    
    if not perm_result.allowed:
        messages.append({
            "role": "tool",
            "content": json.dumps({
                "success": False,
                "error": f"Permission denied: {perm_result.reason}"
            })
        })
        continue
    
    # 3. Request user approval if needed
    tool_meta = registry.get(tool_name)
    
    audit_logger.log_approval_requested(
        tool_name,
        tool_meta.risk_level.value,
        tool_args,
    )
    
    approval_decision = await approval_workflow.request_approval(
        tool_name,
        tool_meta,
        tool_args,
        reason="Agent requested tool execution",
    )
    
    audit_logger.log_approval_decision(approval_decision)
    
    if approval_decision.status != ApprovalStatus.APPROVED:
        messages.append({
            "role": "tool",
            "content": json.dumps({
                "success": False,
                "error": f"Tool execution rejected: {approval_decision.reason}"
            })
        })
        run.tools_called.append(f"[REJECTED] {tool_name}")
        continue
    
    # ========== END: Permission & Approval Logic ==========
    
    # 4. Execute tool (existing logic)
    result = execute_tool(tool_name, tool_args)
    run.tools_called.append(tool_name)
    
    # 5. Log execution
    audit_logger.log_tool_execution(
        tool_name,
        tool_args,
        success=result.success,
        error=result.error,
    )
    
    # 6. Add result to messages (existing logic)
    tool_step = AgentStep(...)
    run.steps.append(tool_step)
    messages.append({...})
```

### Step 4: Update SYSTEM_PROMPT

Optionally update the system prompt to instruct the agent about permission requirements:

```python
SYSTEM_PROMPT = """\
You are AutoOps AI, a DevOps operations agent with access to Docker and MongoDB tools.

You can inspect infrastructure, diagnose issues, and take remediation actions.

IMPORTANT: The following tools require explicit user approval:
- docker_restart_container (HIGH_RISK)
- docker_stop_container (HIGH_RISK)
- docker_remove_container (HIGH_RISK)
- mongodb_kill_operation (MEDIUM_RISK)

Read-only tools are auto-approved:
- docker_list_containers
- docker_inspect_container
- docker_container_logs
- docker_container_stats
- mongodb_server_status
- mongodb_list_databases
- mongodb_current_operations

When a user asks about infrastructure:
1. Use the available tools to gather real data
2. Analyze the results
3. Provide a clear diagnosis and recommendation

Rules:
- Always gather data before making claims
- For destructive actions, explain what you're about to do first
- State risk levels for any remediation actions
- Explain your reasoning concisely
"""
```

### Step 5: Update Demo to Show Permissions

```python
# In POCs/tool_execution/demo.py

async def run_scenario_with_permissions(scenario: dict, interactive: bool = True):
    """Run scenario with permission checking."""
    console.print(f"\n[bold cyan]Scenario: {scenario['title']}[/bold cyan]")
    console.print(f"Request: {scenario['message']}\n")
    
    run = await run_agent(
        scenario['message'],
        interactive=interactive,
    )
    
    print_run(run)
    
    # NEW: Show permission results
    console.print("\n[bold]Permission & Approval Summary[/bold]")
    for step in run.steps:
        if step.role == "tool" and step.tool_result:
            tool_name = step.tool_name
            result = step.tool_result
            
            if result.success:
                console.print(f"  ✓ {tool_name} — Executed")
            elif "[REJECTED]" in tool_name:
                console.print(f"  ✗ {tool_name.replace('[REJECTED] ', '')} — Permission/Approval Denied")
            elif "Permission denied" in str(result.error):
                console.print(f"  ✗ {tool_name} — Permission Denied: {result.error}")
```

## Configuration

### Permission Config File

Users can save and load permission configurations:

```python
from pathlib import Path
from permission_approval_system.permission_manager import PermissionManager

# Save permissions
manager = PermissionManager(registry)
manager.grant_permission('docker_restart_container')
manager.grant_user_permission('docker:write')
manager.save_config(Path('~/.autoops/permissions.json').expanduser())

# Load permissions in future sessions
manager = PermissionManager(registry, config_file=Path('~/.autoops/permissions.json'))
```

### Disable Interactive Mode

For non-interactive environments (CI/CD, headless):

```python
approval_workflow = ApprovalWorkflow(
    interactive=False,
    auto_approve_read_only=True,  # Auto-approve safe operations
)

# Will auto-approve read-only, reject others
```

### Custom Approval Handlers

For testing or external approval systems:

```python
async def external_approval(request):
    """Approve via external system."""
    response = await some_external_service.approve(
        tool=request.tool_name,
        params=request.parameters,
        risk=request.risk_level,
    )
    return response['approved']

approval_workflow.set_custom_handler(external_approval)
```

## Audit Trail

The system generates a JSONL audit log with every permission check and approval decision:

```bash
# View audit log
tail -f audit.jsonl | jq .

# Parse specific events
jq 'select(.event_type == "approval_decided")' audit.jsonl

# Generate report
python -c "
from pathlib import Path
from permission_approval_system.audit_logger import AuditLogger

logger = AuditLogger(log_file=Path('audit.jsonl'))
print(logger.get_report())
"
```

## Security Considerations

### 1. Permission Grants

Permissions are additive - once granted, they persist in the config:

```python
# Grant specific tool permission
manager.grant_permission('docker_restart_container')

# Grant fine-grained permission
manager.grant_user_permission('docker:restart')
```

### 2. Blocklist Override

Blocklist has higher priority than allowlist:

```python
# User can't execute even if in allowlist
manager.block_tool('docker_remove_container')
```

### 3. Approval Timeouts

Different risk levels have different approval timeouts:

| Risk Level | Timeout | Auto-Approval |
|-----------|---------|---------------|
| READ_ONLY | 60s | Yes (configurable) |
| LOW_RISK | 120s | No |
| MEDIUM_RISK | 300s | No |
| HIGH_RISK | 600s | No |

## Troubleshooting

### Permission Denied for Safe Commands

By default, read-only tools auto-approve. To disable:

```python
approval_workflow = ApprovalWorkflow(auto_approve_read_only=False)
```

### Tool Not in Registry

Ensure tool is registered before checking permissions:

```python
registry = get_registry()
if not registry.exists(tool_name):
    # Tool not registered
    pass
```

### Approval Timeout Issues

Increase timeout or disable interactive mode:

```python
# Increase timeout for all levels
workflow.timeout_seconds = 600

# Or set interactive=False to auto-deny
approval_workflow = ApprovalWorkflow(interactive=False)
```

## Full Example

See `integration_example.py` for a complete working example that shows:

1. Initializing `SafeToolExecutor`
2. Simulating LLM tool calls
3. Permission checking
4. Approval workflow
5. Audit logging
6. Full audit report

```bash
uv run python -m POCs.permission_approval_system.integration_example
```

## Next Steps

After integration:

1. ✅ Add POC 7 permission system to POC 3 agent
2. ✅ Test with mock LLM tool calls
3. ✅ Verify audit logging works
4. ✅ Set up permission config for your environment
5. ⏭️ Integrate with **tiered_autonomy** POC for risk-based routing
6. ⏭️ Integrate with **approval_flow** POC for escalation workflows
7. ⏭️ Add RBAC (role-based access control)
8. ⏭️ Connect to external identity providers

## Files Modified

When integrating, you'll modify:

- `POCs/tool_execution/agent.py` - Add permission checks to tool loop
- `POCs/tool_execution/demo.py` - Show permission results
- `POCs/tool_execution/tools.py` - Add tool metadata if needed

No breaking changes to existing functionality!
