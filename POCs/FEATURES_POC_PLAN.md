# POC Development Plan: Claude Code Integration Features

**Timeline**: 1-2 weeks for all POCs  
**Goal**: Validate each feature works in isolation before production integration

---

## POC Structure

```
POCs/
├── FEATURES_POC_PLAN.md              # This file
├── permission_system_poc/            # POC #1: Tiered Permissions
├── timeout_management_poc/           # POC #3: Timeout Enforcement
├── configuration_state_poc/          # POC #4: Config Management
├── incident_history_poc/             # POC #5: History & Context
├── audit_logging_poc/                # POC #6: Error Handling & Observability
├── approval_dialogs_poc/             # POC #2: Approval UI (dashboard integration)
├── mcp_provider_poc/                 # POC #7: MCP Integration
├── feedback_loop_poc/                # POC #8: Binary Feedback
├── permission_rules_poc/             # POC #9: Constraint Checking
└── integration_tests/                # Cross-feature integration tests
```

---

## 1. Permission System POC

**Goal**: Test safe operation whitelisting + auto-execute logic

**Location**: `POCs/permission_system_poc/`

**Key Components**:
- `safe_operations.yaml` - Whitelist of safe operations per risk level
- `permission_checker.py` - Core permission check logic
- `test_permissions.py` - Unit tests

**Tests**:
- ✓ LOW risk actions auto-execute
- ✓ MEDIUM risk actions require approval
- ✓ HIGH risk actions require explicit approval
- ✓ Prefix matching works (e.g., "docker_restart_*")
- ✓ Config override allows/blocks specific actions

**Integration Points**:
- Feeds into `RemediationExecutor` decision logic
- Used by `ApprovalRouter` to classify actions

---

## 2. Approval Dialog UI POC

**Goal**: Test approval card UI component with rich context

**Location**: `POCs/approval_dialogs_poc/`

**Key Components**:
- `ApprovalCard.tsx` - React component (adapted from claude-code)
- `approval_card_data.py` - Python dataclass for card payload
- `test_approval_card.tsx` - Component tests

**Tests**:
- ✓ Card renders with title, description, risk badge
- ✓ Action buttons (Approve/Deny/Investigate) work
- ✓ Timeout countdown displays for MEDIUM risk
- ✓ Rich details panel shows remediation steps
- ✓ WebSocket sends approval decision to backend

**Integration Points**:
- Dashboard receives card from `ApprovalRouter`
- User action sends back via WebSocket
- Backend processes decision and executes/denies action

---

## 3. Timeout Management POC

**Goal**: Test timeout enforcement with graceful rollback

**Location**: `POCs/timeout_management_poc/`

**Key Components**:
- `timeout_executor.py` - Async execution with timeout
- `rollback_strategy.py` - Rollback handlers per action type
- `test_timeouts.py` - Unit + integration tests

**Tests**:
- ✓ Action completes within timeout
- ✓ Action times out and triggers rollback
- ✓ Timeout is configurable per risk level
- ✓ SLA tracking (elapsed vs target MTTR)
- ✓ Escalation if SLA exceeded

**Integration Points**:
- Used by `RemediationExecutor` to run all actions
- Logs timeout events to `AuditLogger`
- Updates `IncidentStore` with timing info

---

## 4. Configuration State Management POC

**Goal**: Test hierarchical config loading (defaults → env → playbook)

**Location**: `POCs/configuration_state_poc/`

**Key Components**:
- `config/defaults.yaml` - Global defaults
- `config/staging.yaml` - Staging overrides
- `config/production.yaml` - Production overrides
- `config_manager.py` - Hierarchical config loader
- `test_config.py` - Unit tests

**Tests**:
- ✓ Load defaults
- ✓ Override with environment config
- ✓ Override with playbook-specific config
- ✓ Per-playbook approval policies
- ✓ Safe defaults prevent accidents

**Integration Points**:
- Loaded at startup and cached
- Used by `ApprovalRouter` for approval policies
- Used by `RemediationExecutor` for timeout values
- Used by `PermissionChecker` for safe operations

---

## 5. Incident History & Context POC

**Goal**: Test searchable history + semantic matching for playbook lookup

**Location**: `POCs/incident_history_poc/`

**Key Components**:
- `incident_history.py` - In-memory incident store
- `history_search.py` - Semantic search for similar incidents
- `test_history.py` - Unit tests

**Tests**:
- ✓ Add incident to history
- ✓ Search for similar incidents by symptom
- ✓ Auto-suggest matching playbook
- ✓ LRU cache prevents memory bloat
- ✓ Export history for analytics

**Integration Points**:
- Used by `AgentEngine` to find matching playbooks
- Used by dashboard to show incident timeline
- Used by `FeedbackLoop` to track playbook effectiveness

---

## 6. Audit Logging & Error Handling POC

**Goal**: Test audit log capture + error categorization

**Location**: `POCs/audit_logging_poc/`

**Key Components**:
- `audit_log.py` - AuditLogEntry + AuditLogger classes
- `error_categories.py` - ErrorCategory enum
- `test_audit_log.py` - Unit tests

**Tests**:
- ✓ Capture incident detected event
- ✓ Capture approval requested/granted/denied events
- ✓ Capture action executed/failed events
- ✓ Categorize errors (not found, failed, timeout, etc.)
- ✓ Export audit trail for compliance
- ✓ Session tracking (SESSION_ID per incident)

**Integration Points**:
- Every component logs events to `AuditLogger`
- Dashboard shows audit trail for each incident
- Compliance team exports for regulatory requirements

---

## 7. MCP Provider POC

**Goal**: Test dynamic tool registration from external MCP servers

**Location**: `POCs/mcp_provider_poc/`

**Key Components**:
- `mcp_provider.py` - MCPProvider class (implements InfrastructureProvider)
- `mcp_tool_registry.py` - Tool discovery + caching
- `test_mcp.py` - Unit tests with mock MCP servers

**Tests**:
- ✓ Discover MCP servers from config
- ✓ List available remediation tools
- ✓ Execute tool with parameters
- ✓ Handle tool approval flow
- ✓ Fallback if MCP server unavailable

**Integration Points**:
- Extends existing `InfrastructureProvider` interface
- `RemediationExecutor` can use MCP tools
- Config defines available MCP servers
- Approval system checks MCP tool permissions

---

## 8. Binary Feedback Loop POC

**Goal**: Test learning from approval/denial patterns

**Location**: `POCs/feedback_loop_poc/`

**Key Components**:
- `feedback_loop.py` - PlaybookLearner + feedback collection
- `playbook_stats.py` - Track approval rates per playbook
- `test_feedback.py` - Unit tests

**Tests**:
- ✓ Collect approval feedback
- ✓ Track approval rate per playbook
- ✓ Lower confidence on denials
- ✓ Suggest better playbook if denied
- ✓ Update playbook ranking over time

**Integration Points**:
- `ApprovalRouter` captures user decision
- Feedback sent to `PlaybookLearner`
- `AgentEngine` uses updated playbook rankings
- Dashboard shows playbook stats

---

## 9. Permission Enforcement Rules POC

**Goal**: Test playbook step constraint checking

**Location**: `POCs/permission_rules_poc/`

**Key Components**:
- `playbook_constraints.py` - Constraint checker
- `constraints.yaml` - Forbidden sequences + required fields
- `test_constraints.py` - Unit tests

**Tests**:
- ✓ Detect forbidden step sequences
- ✓ Require rollback plan for dangerous actions
- ✓ Prevent execution if constraints violated
- ✓ Suggest safe alternative sequences

**Integration Points**:
- Used by `RemediationExecutor` to validate playbook before execution
- Blocks dangerous playbook sequences
- Logs constraint violations to audit log

---

## Integration Test Strategy

**Location**: `POCs/integration_tests/`

**Test Scenarios** (end-to-end):

### Scenario 1: LOW Risk Auto-Execution
```
Incident Detected → Permission Check (LOW) → Auto-Execute 
→ Verify → Audit Log → Incident Resolved
```
- Tests: Permission System (#1) + Timeout (#3) + Audit Logging (#6)

### Scenario 2: MEDIUM Risk with Approval
```
Incident Detected → Permission Check (MEDIUM) → Approval Card Shown
→ User Approves → Execute → Verify → Audit Log → Resolved
```
- Tests: Permission System (#1) + Approval UI (#2) + Timeout (#3) + Audit Logging (#6)

### Scenario 3: Config Override Blocks Auto-Execution
```
Incident Detected → Config Check (prod: no auto-execute) → Approval Card
→ User Denies → Escalate → Audit Log
```
- Tests: Config Management (#4) + Permission System (#1) + Approval UI (#2) + Audit Logging (#6)

### Scenario 4: History-Based Playbook Matching
```
Incident Detected → Search History (similar incident found)
→ Use Matched Playbook → Execute → Feedback Captured
```
- Tests: Incident History (#5) + Feedback Loop (#8) + Permission System (#1)

### Scenario 5: Timeout + Rollback
```
Incident → Execute Action → Timeout Triggered → Rollback Executed
→ Error Categorized → Escalated → Audit Log
```
- Tests: Timeout Management (#3) + Error Handling (#6) + Permission System (#1)

### Scenario 6: MCP Tool Execution
```
Incident → Check MCP Tools → Discover Tool → Approval Card → Execute
→ MCP Provider Handles → Verify → Audit Log
```
- Tests: MCP Provider (#7) + Approval UI (#2) + Timeout (#3)

---

## POC Testing Checklist

For each POC, verify:

- [ ] **Unit Tests Pass** - 80%+ coverage for core logic
- [ ] **Integration Points** - Correct data flow to dependent components
- [ ] **Error Handling** - Graceful failure, proper logging
- [ ] **Config Loading** - Respects environment + overrides
- [ ] **Async Operations** - Timeouts, cancellation work
- [ ] **Audit Trail** - All events logged with context
- [ ] **API Contracts** - Data structures match frontend expectations

---

## Development Order

**Week 1**:
1. Permission System POC (#1) - 2 hours
2. Timeout Management POC (#3) - 2 hours
3. Audit Logging POC (#6) - 2 hours
4. Configuration POC (#4) - 2 hours

**Week 2**:
5. Incident History POC (#5) - 2 hours
6. Approval Dialog POC (#2) - 3 hours (with frontend)
7. Permission Rules POC (#9) - 2 hours
8. Feedback Loop POC (#8) - 2 hours
9. MCP Provider POC (#7) - 2 hours

**Week 2 (Late)**:
10. Integration Tests - Run all 6 scenarios - 3 hours
11. Validation & Refinement - 2 hours

---

## Validation Criteria

**Each POC is "done" when**:
- ✓ Core logic is tested and works in isolation
- ✓ Integration points to dependent components are validated
- ✓ Error cases are handled gracefully
- ✓ Audit/logging captures all important events
- ✓ Config loading/overrides work as expected
- ✓ Code is documented and ready to port to production

---

## Files to Create

### Python POCs
```
permission_system_poc/
├── __init__.py
├── safe_operations.yaml
├── permission_checker.py
├── test_permissions.py
└── README.md

timeout_management_poc/
├── __init__.py
├── timeout_executor.py
├── rollback_strategy.py
├── test_timeouts.py
└── README.md

configuration_state_poc/
├── __init__.py
├── config/
│   ├── defaults.yaml
│   ├── staging.yaml
│   └── production.yaml
├── config_manager.py
├── test_config.py
└── README.md

incident_history_poc/
├── __init__.py
├── incident_history.py
├── history_search.py
├── test_history.py
└── README.md

audit_logging_poc/
├── __init__.py
├── audit_log.py
├── error_categories.py
├── test_audit_log.py
└── README.md

permission_rules_poc/
├── __init__.py
├── playbook_constraints.py
├── constraints.yaml
├── test_constraints.py
└── README.md

mcp_provider_poc/
├── __init__.py
├── mcp_provider.py
├── mcp_tool_registry.py
├── test_mcp.py
└── README.md

feedback_loop_poc/
├── __init__.py
├── feedback_loop.py
├── playbook_stats.py
├── test_feedback.py
└── README.md

integration_tests/
├── __init__.py
├── conftest.py
├── test_scenario_1_low_risk.py
├── test_scenario_2_medium_risk.py
├── test_scenario_3_config_override.py
├── test_scenario_4_history_matching.py
├── test_scenario_5_timeout_rollback.py
├── test_scenario_6_mcp_execution.py
└── README.md
```

### React POCs
```
approval_dialogs_poc/
├── __init__.py
├── ApprovalCard.tsx
├── ApprovalCard.test.tsx
├── approval_card_data.py
└── README.md
```

---

## Next Steps

1. **Create each POC** following the structure above
2. **Write unit tests** for core logic
3. **Run integration tests** to validate end-to-end flows
4. **Get team feedback** on API design + data structures
5. **Document lessons learned** for production implementation
6. **Identify dependency order** for production build

---

**Status**: Ready to implement  
**Owner**: AutoOps AI Team  
**Start Date**: [To be scheduled]  
**Target Completion**: 2 weeks
