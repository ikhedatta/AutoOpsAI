# 🔐 POC 7: Permission & Approval System - Quick Start Guide

## Overview

**POC 7** implements critical permission and approval infrastructure for safe autonomous tool execution in AutoOpsAI. It directly addresses the two highest-priority improvements identified in the analysis:

1. ✅ **Permission & Approval System** - Allowlist/blocklist with interactive workflows
2. ✅ **User Approval Workflow** - Risk-based interactive prompts with timeouts

## 🚀 Quick Start (5 minutes)

### 1. Run the Demo

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
source .venv/bin/activate
uv run python -m POCs.permission_approval_system.demo
```

**What you'll see:**
- Tool registry with 11 registered tools
- Permission checking tests
- Interactive approval workflow simulation
- Audit logging in JSONL format
- Configuration persistence

### 2. Run the Integration Example

```bash
uv run python -m POCs.permission_approval_system.integration_example
```

**What you'll see:**
- Example agent execution loop
- Permission checks on each tool call
- Approval decisions
- Complete audit trail

### 3. Explore the Code

Start with these files in order:

1. **`tool_registry.py`** - Tool metadata (11 tools, 5 risk levels)
2. **`permission_manager.py`** - Permission checking (allowlist/blocklist)
3. **`approval_workflow.py`** - Interactive approval (async prompts, timeouts)
4. **`audit_logger.py`** - Audit trail (JSONL compliance logging)
5. **`integration_example.py`** - How to use it with your agent

## 📁 File Structure

```
permission_approval_system/
├── tool_registry.py           # Tool metadata & registry (200 lines)
├── permission_manager.py      # Permission checking logic (250 lines)
├── approval_workflow.py       # Interactive approval system (300 lines)
├── audit_logger.py            # JSONL audit logging (180 lines)
├── integration_example.py     # Reference implementation (200 lines)
├── demo.py                    # 5-part comprehensive demo (250 lines)
├── README.md                  # Full documentation (400 lines)
├── INTEGRATION_GUIDE.md       # Step-by-step integration (300 lines)
└── IMPLEMENTATION_SUMMARY.md  # This implementation (300 lines)
```

## 🎯 Core Concepts

### 1. Tool Registry

Every tool has metadata with risk level and permissions:

```python
from permission_approval_system.tool_registry import get_registry

registry = get_registry()

# Check if tool exists
if registry.exists('docker_restart_container'):
    tool = registry.get('docker_restart_container')
    print(tool.risk_level)  # ToolRiskLevel.HIGH_RISK
    print(tool.is_read_only)  # False
```

**Risk Levels:**
- 🟢 **READ_ONLY** (7 tools) - Auto-approved monitoring commands
- 🟡 **LOW_RISK** (0 tools) - Non-critical modifications
- 🟠 **MEDIUM_RISK** (1 tool) - Significant impact (mongodb_kill_operation)
- 🔴 **HIGH_RISK** (3 tools) - Destructive (docker_restart, stop, remove)
- 🚫 **BLOCKED** - Explicitly forbidden

### 2. Permission Manager

Check if a user can execute a tool:

```python
from permission_approval_system.permission_manager import PermissionManager

manager = PermissionManager(registry)

# Check permission (returns PermissionResult)
result = manager.check_permission('docker_restart_container')
print(result.allowed)  # False (by default)
print(result.reason)   # "No permission to execute..."
print(result.source)   # "denied"

# Grant permission
manager.grant_permission('docker_restart_container')

# Check again
result = manager.check_permission('docker_restart_container')
print(result.allowed)  # True
print(result.source)   # "config"
```

**Permission Sources:**
- `safe_command` - Auto-approved read-only
- `config` - In allowlist
- `permissions` - User has required permissions
- `blocklist` - Explicitly blocked
- `denied` - No permission (default)

### 3. Approval Workflow

Request interactive user approval for risky operations:

```python
from permission_approval_system.approval_workflow import ApprovalWorkflow
import asyncio

workflow = ApprovalWorkflow(interactive=True, auto_approve_read_only=True)

async def test():
    # Auto-approve read-only
    decision = await workflow.request_approval(
        tool_name='docker_list_containers',
        tool_meta=registry.get('docker_list_containers'),
        parameters={},
    )
    print(decision.status)  # ApprovalStatus.APPROVED
    print(decision.method)  # ApprovalMethod.AUTO
    
    # Request user approval for destructive operation
    decision = await workflow.request_approval(
        tool_name='docker_restart_container',
        tool_meta=registry.get('docker_restart_container'),
        parameters={'container_name': 'flask-app'},
    )
    print(decision.status)  # USER_INTERACTIVE (will show prompt)

asyncio.run(test())
```

**Approval Methods:**
- `AUTO` - Auto-approved (read-only operations)
- `USER_INTERACTIVE` - User prompted
- `CONFIG` - Pre-approved in config
- `SAFE_COMMAND` - Pre-approved safe command

### 4. Audit Logger

Log all permission and approval decisions for compliance:

```python
from permission_approval_system.audit_logger import AuditLogger
from pathlib import Path

logger = AuditLogger(log_file=Path('audit.jsonl'))

# Log permission check
logger.log_permission_check(
    tool_name='docker_restart_container',
    allowed=False,
    reason='No permission',
    source='denied',
    user_id='user1',
    session_id='session1',
)

# Get audit report
report = logger.get_report()
print(f"Total events: {report['total_events']}")
print(f"Permission checks: {report['by_type']['permission_check']}")
```

## 💡 Common Usage Patterns

### Pattern 1: Check Permission Before Executing

```python
manager = PermissionManager(registry)
result = manager.check_permission('docker_restart_container')

if result.allowed:
    # Execute tool
    pass
else:
    # Reject with reason
    print(f"Permission denied: {result.reason}")
```

### Pattern 2: Request User Approval

```python
workflow = ApprovalWorkflow(interactive=True)

decision = await workflow.request_approval(
    tool_name='docker_restart_container',
    tool_meta=registry.get('docker_restart_container'),
    parameters={'container_name': 'mongodb'},
    reason='Restart failed MongoDB instance',
)

if decision.status == ApprovalStatus.APPROVED:
    # Execute tool
    pass
else:
    print(f"Approval {decision.status.value}: {decision.reason}")
```

### Pattern 3: Full Safe Execution

```python
from permission_approval_system.integration_example import SafeToolExecutor

executor = SafeToolExecutor(
    interactive=True,
    auto_approve_read_only=True,
)

# Check if tool can be executed
request = ToolExecutionRequest(
    tool_name='docker_restart_container',
    parameters={'container_name': 'flask-app'},
    reason='Restart stalled service',
)

decision = await executor.can_execute(request)

if decision.allowed:
    # Execute tool...
    executor.log_tool_execution(
        'docker_restart_container',
        {'container_name': 'flask-app'},
        success=True,
    )
```

### Pattern 4: Save/Load Permissions

```python
from pathlib import Path

# Save user permissions
manager = PermissionManager(registry)
manager.grant_permission('docker_restart_container')
manager.save_config(Path('permissions.json'))

# Load in new session
manager2 = PermissionManager(
    registry,
    config_file=Path('permissions.json')
)
# Permissions preserved!
```

## 📊 Approval Timeouts by Risk Level

| Risk Level | Timeout | Use Case |
|-----------|---------|----------|
| READ_ONLY | 60s | `docker_list_containers`, `mongodb_server_status` |
| LOW_RISK | 120s | Non-critical modifications |
| MEDIUM_RISK | 300s (5 min) | `mongodb_kill_operation` |
| HIGH_RISK | 600s (10 min) | `docker_restart`, `docker_stop`, `docker_remove` |

## 🔐 Permission Check Hierarchy

When checking permissions, the system checks in this order:

1. **Blocklist** - If blocked, immediately deny ❌
2. **Safe Commands** - If safe AND auto_approve enabled, approve ✅
3. **Allowlist** - If in allowlist, approve ✅
4. **User Permissions** - If user has required perms, approve ✅
5. **Default Deny** - Otherwise deny ❌

## 📈 Integration with Tool Execution

To add to your agent loop:

```python
# In POCs/tool_execution/agent.py

from permission_approval_system.permission_manager import PermissionManager
from permission_approval_system.approval_workflow import ApprovalWorkflow

async def run_agent(...):
    manager = PermissionManager(registry)
    workflow = ApprovalWorkflow(interactive=True)
    
    for tc in tool_calls:
        tool_name = tc["function"]["name"]
        tool_args = tc.get("arguments", {})
        
        # 1. Check permission
        perm = manager.check_permission(tool_name)
        if not perm.allowed:
            # Reject
            continue
        
        # 2. Request approval
        decision = await workflow.request_approval(
            tool_name,
            registry.get(tool_name),
            tool_args,
        )
        if decision.status != ApprovalStatus.APPROVED:
            # Reject
            continue
        
        # 3. Execute tool
        result = execute_tool(tool_name, tool_args)
```

See `INTEGRATION_GUIDE.md` for detailed step-by-step instructions.

## 🧪 Testing Without Interactive Prompts

For automated testing, use a custom handler:

```python
workflow = ApprovalWorkflow(interactive=False)

async def auto_approve_handler(request):
    # Auto-approve everything for testing
    return True

workflow.set_custom_handler(auto_approve_handler)

# Now requests won't prompt, just use the handler
decision = await workflow.request_approval(...)
```

## 📝 Audit Log Format

Audit logs are written in JSONL (JSON Lines) format:

```json
{"event_type": "permission_check", "timestamp": "2026-04-02T02:54:54.306975", "tool_name": "docker_restart_container", "user_id": "user1", "session_id": "session1", "details": {"allowed": false, "reason": "No permission", "source": "denied"}}
{"event_type": "approval_requested", "timestamp": "2026-04-02T02:54:54.307108", "tool_name": "docker_restart_container", "user_id": "user1", "session_id": "session1", "details": {"risk_level": "HIGH_RISK", "parameters": {"container_name": "flask-app"}}}
{"event_type": "approval_decided", "timestamp": "2026-04-02T02:54:54.307153", "tool_name": "docker_restart_container", "user_id": "user1", "session_id": "session1", "details": {"status": "approved", "method": "user_interactive"}}
{"event_type": "tool_executed", "timestamp": "2026-04-02T02:54:54.307180", "tool_name": "docker_restart_container", "user_id": "user1", "session_id": "session1", "details": {"parameters": {"container_name": "flask-app"}, "success": true, "duration_ms": 125.5}}
```

Parse with:
```bash
jq 'select(.event_type == "approval_decided")' audit.jsonl
```

## 🚀 Next Steps

1. ✅ **Review** - Read `README.md` and `IMPLEMENTATION_SUMMARY.md`
2. ✅ **Understand** - Study the code in this order:
   - tool_registry.py
   - permission_manager.py
   - approval_workflow.py
   - audit_logger.py
3. ✅ **Test** - Run demo and integration example
4. ⏭️ **Integrate** - Follow `INTEGRATION_GUIDE.md` to add to tool_execution POC
5. ⏭️ **Connect** - Integrate with tiered_autonomy and approval_flow POCs

## 📚 Documentation Map

| Document | Purpose | Audience |
|----------|---------|----------|
| **README.md** | Feature overview and examples | Users |
| **IMPLEMENTATION_SUMMARY.md** | What was built and why | Developers |
| **INTEGRATION_GUIDE.md** | How to add to tool_execution | Integrators |
| **Docstrings** | Code documentation | Developers |
| **demo.py** | Runnable examples | Everyone |
| **integration_example.py** | Reference implementation | Integrators |

## ❓ FAQ

**Q: Why 5 risk levels?**
A: Matches the operational profile:
- READ_ONLY: Safe monitoring (auto-approve)
- LOW_RISK: Fast remediation (user can approve)
- MEDIUM_RISK: Careful remediation (longer timeout)
- HIGH_RISK: Destructive actions (requires explicit approval)
- BLOCKED: Administrative override

**Q: Can I customize risk levels?**
A: Yes! Modify `tool_registry.py` to register tools with custom risk levels.

**Q: Can I use external approval systems?**
A: Yes! Use `workflow.set_custom_handler()` to connect to external approval APIs.

**Q: How do I audit compliance?**
A: All decisions are logged to JSONL. Use `audit_logger.get_report()` for summaries.

**Q: Can I make this non-interactive?**
A: Yes! Use `ApprovalWorkflow(interactive=False)` for headless environments.

## 🆘 Troubleshooting

**Problem:** Tool not found in registry
```python
# Solution: Check registry
if not registry.exists('my_tool'):
    print("Tool not registered")
```

**Problem:** Permission always denied
```python
# Solution: Grant permission or check safe_command list
manager.grant_permission('my_tool')  # Or
# Check if tool is in SAFE_COMMANDS
```

**Problem:** Approval timeout not working
```python
# Solution: Increase timeout
workflow.timeout_seconds = 600  # 10 minutes
```

---

**Ready to start?** Run the demo:
```bash
uv run python -m POCs.permission_approval_system.demo
```

**Questions?** See the full documentation in README.md and INTEGRATION_GUIDE.md
