# POC Quick Start Guide

This guide shows how to set up and run the feature POCs before production implementation.

---

## Setup

### 1. Install Dependencies

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pip install -r POCs/requirements.txt
```

**requirements.txt** should include:
```
pytest>=7.0
pyyaml>=6.0
asyncio
```

### 2. Verify POC Structure

```bash
tree POCs/
├── FEATURES_POC_PLAN.md
├── permission_system_poc/
│   ├── __init__.py
│   ├── permission_checker.py
│   └── test_permissions.py
├── timeout_management_poc/
│   ├── __init__.py
│   ├── timeout_executor.py
│   └── test_timeouts.py
├── audit_logging_poc/
│   ├── __init__.py
│   ├── audit_log.py
│   └── test_audit_log.py
├── configuration_state_poc/
│   ├── __init__.py
│   ├── config_manager.py
│   └── test_config.py
├── incident_history_poc/
│   ├── __init__.py
│   ├── incident_history.py
│   └── test_history.py
└── integration_tests/
    ├── __init__.py
    ├── test_scenarios.py
    └── conftest.py
```

---

## Running Individual POCs

### POC #1: Permission System

```bash
cd POCs/permission_system_poc
python -m pytest test_permissions.py -v

# Expected output:
# test_low_risk_auto_execute PASSED
# test_medium_risk_requires_approval PASSED
# test_prefix_matching PASSED
```

**What it tests**:
- ✓ LOW risk auto-executes
- ✓ MEDIUM/HIGH require approval
- ✓ Whitelist + prefix matching work
- ✓ Config overrides function

### POC #3: Timeout Management

```bash
cd POCs/timeout_management_poc
python -m pytest test_timeouts.py -v

# Expected output:
# test_execute_within_timeout PASSED
# test_timeout_triggers_rollback PASSED
# test_sla_tracking PASSED
```

**What it tests**:
- ✓ Actions complete within timeout
- ✓ Timeout triggers rollback
- ✓ SLA tracking works (P1/P2/P3/P4)
- ✓ Escalation on SLA breach

### POC #6: Audit Logging

```bash
cd POCs/audit_logging_poc
python -m pytest test_audit_log.py -v

# Expected output:
# test_audit_entry_creation PASSED
# test_error_categorization PASSED
# test_compliance_export PASSED
```

**What it tests**:
- ✓ Audit entries capture all events
- ✓ Error categorization works
- ✓ Session tracking
- ✓ Export for compliance

### POC #4: Configuration Management

```bash
cd POCs/configuration_state_poc
python -m pytest test_config.py -v

# Expected output:
# test_load_defaults PASSED
# test_environment_override PASSED
# test_approval_policy PASSED
```

**What it tests**:
- ✓ Hierarchical config loading
- ✓ Environment-specific overrides
- ✓ Safe defaults
- ✓ Policy lookup

### POC #5: Incident History

```bash
cd POCs/incident_history_poc
python -m pytest test_history.py -v

# Expected output:
# test_add_incident PASSED
# test_find_similar PASSED
# test_playbook_stats PASSED
```

**What it tests**:
- ✓ Store incidents
- ✓ Semantic search
- ✓ Playbook statistics
- ✓ Memory management (LRU)

---

## Running Integration Tests

### All Scenarios Together

```bash
cd POCs/integration_tests
python -m pytest test_scenarios.py -v

# Runs:
# - test_scenario_1_low_risk_auto_execution
# - test_scenario_2_medium_risk_with_approval
# - test_scenario_3_config_override_blocks
# - test_scenario_4_history_based_playbook_match
# - test_scenario_5_timeout_with_rollback
# - test_scenario_6_mcp_tool_execution
```

### Specific Scenario

```bash
python -m pytest test_scenarios.py::TestIntegrationScenarios::test_scenario_1_low_risk_auto_execution -v
```

---

## Example: Using POCs in Code

### Simple Permission Check

```python
from permission_system_poc.permission_checker import PermissionChecker, RiskLevel

checker = PermissionChecker()

# Check if action is safe
result = checker.check_permission(
    action="redis_memory_purge",
    risk_level=RiskLevel.LOW,
)

if result.result:
    print(f"✓ {result.reason}")
else:
    print(f"✗ {result.reason} - need approval")
```

### Execute with Timeout

```python
import asyncio
from timeout_management_poc.timeout_executor import TimeoutExecutor

async def main():
    executor = TimeoutExecutor()
    
    async def dummy_action():
        await asyncio.sleep(0.5)
        return "Action completed"
    
    result = await executor.execute_with_timeout(
        action_id="action-001",
        execute_fn=dummy_action,
        timeout_seconds=2,
        risk_level="MEDIUM",
    )
    
    print(f"Status: {result.status}")
    print(f"Elapsed: {result.elapsed_seconds:.2f}s")

asyncio.run(main())
```

### Audit Logging

```python
import asyncio
from audit_logging_poc.audit_log import AuditLogger, AuditAction

async def main():
    logger = AuditLogger("test.log")
    
    await logger.log(
        incident_id="INC-001",
        action=AuditAction.INCIDENT_DETECTED,
        user_id="system",
        details={"symptom": "High CPU"},
    )
    
    # Export for compliance
    logger.export_for_compliance("audit_export.json")

asyncio.run(main())
```

### Configuration Loading

```python
from configuration_state_poc.config_manager import ConfigManager

manager = ConfigManager()

# Get staging config
staging = manager.get_config("staging")
print(f"Approval required: {staging.approval_policy['MEDIUM']['requires_approval']}")

# Get production config
prod = manager.get_config("production")
print(f"Safe ops in prod: {prod.auto_execute_operations['LOW']}")

# Check if action is safe in environment
is_safe = manager.is_operation_safe(
    environment="production",
    operation="redis_memory_purge",
    risk_level="LOW",
)
print(f"Safe to execute: {is_safe}")
```

### Incident History Search

```python
from incident_history_poc.incident_history import IncidentHistory, ResolvedIncident, IncidentContext, SimilarIncidentMatcher
from datetime import datetime

history = IncidentHistory()

# Add a resolved incident
incident = ResolvedIncident(
    incident_id="INC-001",
    context=IncidentContext(
        incident_id="INC-001",
        detected_at=datetime.now(),
        symptom="MongoDB connection timeout",
        service="api",
    ),
    playbook_id="mongo_restart",
    playbook_name="Restart MongoDB",
    remediation_steps=["Stop MongoDB", "Wait 5s", "Start MongoDB"],
    status="resolved",
    resolved_at=datetime.now(),
    resolution_time_seconds=45.0,
)
history.add(incident)

# Search for similar incidents
similar = history.find_similar(
    symptom="MongoDB connection timeout",
    service="api",
)

# Get AI-assisted suggestion
matcher = SimilarIncidentMatcher()
match = matcher.match_and_suggest_playbook(
    current_symptom="MongoDB unreachable",
    history=history,
    service="api",
)

if match:
    incident, confidence = match
    print(f"Suggested playbook: {incident.playbook_name} ({confidence:.2%} confidence)")
```

---

## Test Output Examples

### Permission System Test Run

```
========================= test session starts ==========================
collected 7 items

test_permissions.py::TestPermissionChecks::test_low_risk_auto_execute PASSED
test_permissions.py::TestPermissionChecks::test_medium_risk_requires_approval PASSED
test_permissions.py::TestPermissionChecks::test_high_risk_requires_approval PASSED
test_permissions.py::TestPermissionChecks::test_prefix_matching PASSED
test_permissions.py::TestPermissionChecks::test_config_override_blocks_action PASSED
test_permissions.py::TestApprovalRequirements::test_low_risk_no_approval PASSED
test_permissions.py::TestApprovalRequirements::test_medium_risk_requires_approval PASSED

========================= 7 passed in 0.15s ===========================
```

### Timeout Test Run

```
========================= test session starts ==========================
collected 5 items

test_timeouts.py::TestTimeoutExecution::test_execute_within_timeout PASSED
test_timeouts.py::TestTimeoutExecution::test_timeout_triggers_rollback PASSED
test_timeouts.py::TestTimeoutExecution::test_failure_triggers_rollback PASSED
test_timeouts.py::TestSLATracking::test_sla_on_track PASSED
test_timeouts.py::TestSLATracking::test_sla_breach PASSED

========================= 5 passed in 0.42s ===========================
```

---

## Troubleshooting

### ImportError: No module named 'pytest'

```bash
pip install pytest
```

### YAML parsing errors in config tests

```bash
pip install pyyaml
```

### Async test issues

```bash
pip install pytest-asyncio
```

Then add to test file:
```python
import pytest
pytest_plugins = ('pytest_asyncio',)
```

---

## Next Steps After POC Validation

1. **Get team feedback** on POC implementations
2. **Identify integration points** with existing AutoOpsAI code
3. **Plan production migration**:
   - Port POC modules to `agent/` directory
   - Adapt data structures for real incident store
   - Integrate with existing `RemediationExecutor` + `ApprovalRouter`
4. **Create production tests** (same logic, more comprehensive)

---

## File Locations

All POC code is in: `/Users/dattaikhe/LLM/AutoOpsAI/POCs/`

Key files:
- **Plan**: `POCs/FEATURES_POC_PLAN.md`
- **Permission System**: `POCs/permission_system_poc/permission_checker.py`
- **Timeout Management**: `POCs/timeout_management_poc/timeout_executor.py`
- **Audit Logging**: `POCs/audit_logging_poc/audit_log.py`
- **Configuration**: `POCs/configuration_state_poc/config_manager.py`
- **Incident History**: `POCs/incident_history_poc/incident_history.py`
- **Integration Tests**: `POCs/integration_tests/test_scenarios.py`

---

**Status**: Ready to validate  
**Estimated Time**: 1-2 weeks for all POCs + validation
