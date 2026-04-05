# Claude Code Sourcemap → AutoOps AI Integration Analysis

**Date**: April 2, 2026  
**Purpose**: Identify high-value features from claude-code-sourcemap that can accelerate AutoOps AI development

---

## Executive Summary

The **claude-code-sourcemap** repository is an advanced agentic coding tool that integrates Claude API with code editing, execution, and approval workflows. **10 major features** from this codebase are directly applicable to AutoOps AI's architecture:

| Feature | Claude Code Use | AutoOps AI Adaptation |
|---------|-----------------|----------------------|
| **1. Tiered Permission System** | Grants/denies tool use based on risk level | Pre-approve LOW risk actions, prompt for MEDIUM/HIGH |
| **2. Tool Use Approval Dialogs** | Interactive permission requests with user context | Adapt UI components for approval cards in dashboard |
| **3. Execution Timeout Management** | Persistent shell with timeout enforcement | Prevent runaway remediation jobs, enforce SLAs |
| **4. Configuration State Management** | Project + global config with git integration | Per-environment playbook and approval policy management |
| **5. Command History & Context** | Tracks command history, caches project context | Incident history timeline, playbook search/reuse |
| **6. Error Handling & Observability** | Sentry integration, error categorization | Audit logs, error classification, compliance reporting |
| **7. Model Context Protocol (MCP)** | Extensible tool interface via MCP | Dynamic remediation tool registration, vendor support |
| **8. Binary Feedback Loop** | Learns from user accept/reject signals | Learn from approval patterns, improve playbook matching |
| **9. Permission Enforcement Rules** | Command whitelist, prefix matching, safe defaults | Enforce playbook step safeguards, detect risky actions |
| **10. Cost Tracking & Budgeting** *(Deferred)* | Monitors API spend per session | Track remediation costs, compliance spend (internal use) |

---

## 1. Tiered Permission System

### Current State (Claude Code)
- **Permission model**: EXACT_MATCH → PREFIX_MATCH → PROMPT_USER
- **Safe commands**: Whitelist of known-safe commands (git status, pwd, tree)
- **Per-tool enforcement**: BashTool, FileEditTool, NotebookEditTool have different rules
- **Source**: [src/permissions.ts](https://github.com/anthropics/claude-code/blob/main/src/permissions.ts#L23-L35)

```typescript
const SAFE_COMMANDS = new Set([
  'git status',
  'git diff',
  'git log',
  'git branch',
  'pwd',
  'tree',
  'date',
  'which',
])
```

### AutoOps AI Adaptation
AutoOps AI **already has this pattern** (`LOW/MEDIUM/HIGH` risk classification), but claude-code's implementation provides:

**What to steal**:
- **Exact match + prefix matching logic** for remediation steps
  - Define safe playbook operations (e.g., "docker restart postgres" matches "docker restart" prefix)
  - Auto-allow matching operations without re-prompting
- **Configurable whitelist per environment** (similar to `SAFE_COMMANDS`)
  - Store in playbooks as `auto_execute_operations: []`
  - Pre-approved actions per production environment

**Implementation example for AutoOps AI**:
```python
# playbooks/safe_operations.yaml
AUTO_EXECUTE_OPERATIONS:
  LOW:
    - "redis_memory_purge"
    - "log_rotation"
    - "cache_clear"
    - "dns_cache_flush"
  MEDIUM:
    - "docker_restart_stateless_services"
    - "scale_up_replicas"

def can_auto_execute(action: str, risk_level: str) -> bool:
    """Check if action matches approved prefix for risk level."""
    approved = AUTO_EXECUTE_OPERATIONS.get(risk_level, [])
    return any(action.startswith(prefix) for prefix in approved)
```

**File to adapt**: [src/permissions/toolUseOptions.ts](https://github.com/anthropics/claude-code/blob/main/src/components/permissions/toolUseOptions.ts) → `playbooks/permissions.yaml`

---

## 2. Tool Use Approval Dialogs

### Current State (Claude Code)
- **Component**: `PermissionRequest` + tool-specific dialogs (Bash, FileEdit, FileWrite)
- **Features**:
  - Context-aware descriptions (what tool does + specific input)
  - Risk scoring (shows severity to user)
  - Description fetching before prompting
  - Command preview (bash prefix parsing)
- **Source**: [src/components/permissions/](https://github.com/anthropics/claude-code/blob/main/src/components/permissions/)

### AutoOps AI Adaptation
AutoOps AI needs approval cards in the **dashboard chat**, not terminal prompts.

**What to steal**:
- **Description generation pipeline**: Before asking for approval, fetch/generate rich context
  ```typescript
  // From useCanUseTool.ts
  const [description, commandPrefix] = await Promise.all([
    tool.description(input),
    getCommandSubcommandPrefix(command, abortSignal),
  ])
  ```
  
- **Reusable approval card structure**:
  - Title (e.g., "Restart MongoDB")
  - Description (what + why + risk)
  - Details panel (remediation steps, estimated duration)
  - Action buttons (Approve/Deny/Investigate)
  - Timeout countdown (if MEDIUM risk)

**Implementation for AutoOps AI**:
```python
@dataclass
class ApprovalCard:
    """Rich approval request for dashboard UI."""
    incident_id: str
    title: str  # e.g., "Restart MongoDB container"
    description: str  # LLM-generated diagnosis
    risk_level: RiskLevel  # LOW, MEDIUM, HIGH
    details: Dict[str, Any]  # Remediation steps, estimated duration, rollback
    timeout_seconds: int  # 0 for HIGH risk, 300+ for MEDIUM
    created_at: datetime
    ui_variant: str  # "primary", "warning", "danger"
```

**React components to extract**:
- [MCPServerApprovalDialog.tsx](https://github.com/anthropics/claude-code/blob/main/src/components/MCPServerApprovalDialog.tsx) → Adapt for incident approval
- [BashPermissionRequest](https://github.com/anthropics/claude-code/blob/main/src/components/permissions/BashPermissionRequest/) → Adapt for remediation steps
- Rich text + diff display (see [StructuredDiff.tsx](https://github.com/anthropics/claude-code/blob/main/src/components/StructuredDiff.tsx))

---



## 3. Execution Timeout Management

### Current State (Claude Code)
- **Model**: PersistentShell with timeout enforcement
- **Features**:
  - Default timeout (30 min), configurable per command
  - AbortController for cancellation
  - Timeout polling in exec loop
  - Graceful degradation on timeout
- **Source**: [src/utils/PersistentShell.ts](https://github.com/anthropics/claude-code/blob/main/src/utils/PersistentShell.ts#L26-L27)

```typescript
const DEFAULT_TIMEOUT = 30 * 60 * 1000  // 30 minutes

private async exec_(
  command: string,
  timeout?: number,
): Promise<ExecResult> {
  const commandTimeout = timeout || DEFAULT_TIMEOUT
  // ... polling loop checks: Date.now() - start > commandTimeout
}
```

### AutoOps AI Adaptation
Remediation actions must have **hard timeouts** to prevent hanging infrastructure changes.

**What to steal**:
- **Timeout enforcement pattern**:
  ```python
  class RemediationExecutor:
      async def execute_action(
          self,
          action: str,
          timeout_seconds: int = 60,  # Default 60s for remediation
      ) -> ActionResult:
          try:
              result = await asyncio.wait_for(
                  self._do_remediate(action),
                  timeout=timeout_seconds,
              )
          except asyncio.TimeoutError:
              # Rollback automatically
              await self._execute_rollback(action)
              return ActionResult(status="failed", reason="timeout")
  ```

- **AbortController pattern** for graceful cancellation:
  ```python
  # In approval router
  abort_controller = asyncio.Event()  # Python equivalent
  
  async def wait_for_approval(request: ApprovalRequest):
      approval_resolved = await asyncio.wait_for(
          abort_controller.wait(),
          timeout=request.timeout_seconds,
      )
  ```

- **SLA enforcement**: Track if remediation actions exceed incident SLA
  ```python
  @dataclass
  class IncidentSLA:
      target_mttr_minutes: int  # 5 min for P1, 15 min for P2
      
  if elapsed_time > incident.sla.target_mttr_minutes:
      escalate(incident, reason="SLA exceeded")
  ```

**Python pattern to adopt**:
```python
# In agents/engine.py
class ActionTimeout:
    LOW = 30  # 30 seconds for cache clear
    MEDIUM = 120  # 2 min for restart
    HIGH = 300  # 5 min for failover
    
    @staticmethod
    def get_timeout(risk_level: str, action_type: str) -> int:
        """Get timeout for action, configurable per environment."""
        config = load_timeout_config()
        return config.get(risk_level, {}).get(action_type, ActionTimeout.MEDIUM)
```

---

## 4. Configuration State Management

### Current State (Claude Code)
- **Model**: Hierarchical config (global + project-level)
- **Features**:
  - Project config (per-directory)
  - Global config (system-wide)
  - MCP server config (separate)
  - Git-aware (project detection)
  - Type-safe config keys
- **Source**: [src/utils/config.ts](https://github.com/anthropics/claude-code/blob/main/src/utils/config.ts#L28-L48)

```typescript
export type ProjectConfig = {
  allowedTools: string[]
  context: Record<string, string>
  hasTrustDialogAccepted: boolean
  history: string[]
  mcpServers?: Record<string, McpServerConfig>
  ...
}

export type GlobalConfig = {
  projects?: Record<string, ProjectConfig>
  autoUpdaterStatus: ConfigStatusValue
  ...
}
```

### AutoOps AI Adaptation
AutoOps AI needs **environment-specific playbook configs** (dev/staging/prod) with hierarchical overrides.

**What to steal**:
- **Hierarchical config pattern**:
  ```python
  @dataclass
  class EnvironmentConfig:
      # Global defaults
      approval_policy: ApprovalPolicy  # Defaults
      playbooks_dir: str
      
      @staticmethod
      def load() -> Dict[str, EnvironmentConfig]:
          """Load config hierarchy: defaults → global → environment → playbook."""
          config = {}
          config['global'] = load_global_config()
          config['staging'] = load_environment_config('staging')
          config['production'] = load_environment_config('production')
          return config
  ```

- **Per-environment policy overrides**:
  ```yaml
  # config/production.yaml
  approval_policy:
    HIGH_RISK:
      requires_approval: true
      timeout_seconds: 0  # Never auto-timeout HIGH risk in production
    MEDIUM_RISK:
      requires_approval: true
      timeout_seconds: 600  # 10 min timeout
    
  playbooks:
    - db_restart:
        auto_execute: false  # Even if LOW risk, require approval in prod
  ```

- **Config key safety** (type-safe):
  ```python
  ENVIRONMENT_CONFIG_KEYS = [
      'approval_policy',
      'auto_execute_operations',
      'playbooks_dir',
      'incident_store_path',
  ]
  
  def is_valid_config_key(key: str) -> bool:
      return key in ENVIRONMENT_CONFIG_KEYS
  ```

**File structure to adopt**:
```
config/
├── defaults.yaml         # Global defaults
├── production.yaml       # Production overrides
├── staging.yaml          # Staging overrides
└── .envrc               # Environment variables (like .mcprc)
```

---

## 5. Command History & Context

### Current State (Claude Code)
- **Model**: Per-project command history + dynamic context gathering
- **Features**:
  - Tracks last 100 commands per project
  - Caches project README, git status, directory structure
  - Auto-fetches CLAUDE.md files for instructions
  - Memoized context fetch (avoids re-computing)
- **Source**: [src/history.ts](https://github.com/anthropics/claude-code/blob/main/src/history.ts) + [src/context.ts](https://github.com/anthropics/claude-code/blob/main/src/context.ts#L35-L45)

```typescript
const MAX_HISTORY_ITEMS = 100

export function addToHistory(command: string): void {
  const projectConfig = getCurrentProjectConfig()
  const history = projectConfig.history ?? []
  history.unshift(command)
  saveCurrentProjectConfig({
    ...projectConfig,
    history: history.slice(0, MAX_HISTORY_ITEMS),
  })
}

export const getClaudeFiles = memoize(async (): Promise<string | null> => {
  // Auto-find CLAUDE.md files for context
})
```

### AutoOps AI Adaptation
AutoOps AI needs **incident resolution history** + playbook matching context.

**What to steal**:
- **Incident history search**:
  ```python
  class IncidentHistory:
      MAX_HISTORY_ITEMS = 1000
      
      def add_to_history(self, incident: Incident) -> None:
          """Add resolved incident to history."""
          history = load_incident_history()
          history.insert(0, incident)
          save_incident_history(history[:self.MAX_HISTORY_ITEMS])
      
      async def find_similar_incidents(
          self,
          current_symptom: str,
          limit: int = 5,
      ) -> List[Incident]:
          """Search history for similar incidents (for playbook matching)."""
          history = load_incident_history()
          return semantic_search(current_symptom, history, limit)
  ```

- **Auto-discover instructions** (like CLAUDE.md):
  ```python
  # Auto-load README or OPERATIONS.md from project root
  async def get_operations_context(self) -> Optional[str]:
      """Find OPERATIONS.md for environment-specific guidance."""
      for filename in ['OPERATIONS.md', 'README.md', 'RUNBOOKS.md']:
          if exists(f"/app/{filename}"):
              return read_file(f"/app/{filename}")
  ```

- **Memoized context fetch**:
  ```python
  from functools import lru_cache
  
  @lru_cache(maxsize=1)
  async def get_project_context(environment: str) -> str:
      """Cache project context (git status, README) to avoid re-fetching."""
      return await gather_context(environment)
  ```

**Implementation**:
- Port [src/history.ts](https://github.com/anthropics/claude-code/blob/main/src/history.ts) → `agents/incident_history.py`
- Port [src/context.ts](https://github.com/anthropics/claude-code/blob/main/src/context.ts) → `agents/context.py`

---

## 6. Error Handling & Observability

### Current State (Claude Code)
- **Model**: Sentry integration + error categorization
- **Features**:
  - Automatic exception capture with context
  - Session tracking (SESSION_ID)
  - Rich metadata (environment, node version, git status, user)
  - Error categorization (API errors, timeout, permissions, etc.)
  - Feature flag integration (Statsig gates)
- **Source**: [src/services/sentry.ts](https://github.com/anthropics/claude-code/blob/main/src/services/sentry.ts) + [src/utils/log.ts](https://github.com/anthropics/claude-code/blob/main/src/utils/log.js)

```typescript
export async function captureException(error: unknown): Promise<void> {
  Sentry.setExtras({
    nodeVersion: env.nodeVersion,
    platform: env.platform,
    cwd: getCwd(),
    isCI: env.isCI,
    isGit,
    packageVersion: MACRO.VERSION,
    sessionId: SESSION_ID,
    statsigGates: getGateValues(),
  })
}
```

### AutoOps AI Adaptation
AutoOps AI must track **incident resolution outcomes** + compliance audits.

**What to steal**:
- **Session-based error tracking**:
  ```python
  import uuid
  
  SESSION_ID = str(uuid.uuid4())
  
  class ErrorContext:
      """Rich context for every error."""
      incident_id: str
      session_id: str
      environment: str
      action_type: str
      remediation_step: int
      user_id: str
      timestamp: datetime
      
      def capture(self, error: Exception) -> None:
          """Send to audit log + Sentry."""
          audit_log.error({
              'session_id': self.session_id,
              'incident_id': self.incident_id,
              'error': str(error),
              'context': self.__dict__,
          })
  ```

- **Error categorization** (for compliance):
  ```python
  class ErrorCategory(Enum):
      PLAYBOOK_NOT_FOUND = "playbook_not_found"
      REMEDIATION_FAILED = "remediation_failed"
      APPROVAL_TIMEOUT = "approval_timeout"
      INSUFFICIENT_PERMISSIONS = "insufficient_permissions"
      LLM_INFERENCE_ERROR = "llm_inference_error"
      INFRASTRUCTURE_ERROR = "infrastructure_error"
      VERIFICATION_FAILED = "verification_failed"
  ```

- **Feature flag integration** (for gradual rollout):
  ```python
  # Use statsig/feature flags for A/B testing new playbooks
  if feature_flag_enabled('auto_restart_mongodb'):
      allow_auto_execution = True
  ```

**Implementation**:
- Adapt [src/services/sentry.ts](https://github.com/anthropics/claude-code/blob/main/src/services/sentry.ts) → `agent/observability.py`
- Add audit log schema:
  ```python
  @dataclass
  class AuditLogEntry:
      incident_id: str
      action: str  # "approved", "denied", "escalated", "executed", "failed"
      user_id: str
      timestamp: datetime
      context: Dict[str, Any]
      result: str  # "success", "failure", "timeout"
  ```

---

## 7. Model Context Protocol (MCP) Integration

### Current State (Claude Code)
- **Model**: Extensible tool interface via MCP
- **Features**:
  - Dynamic tool registration (stdio + SSE transports)
  - MCP server config management (project + global scope)
  - Tool listing + caching
  - Error handling for unavailable servers
  - Approval dialogs for MCP tools
- **Source**: [src/services/mcpClient.ts](https://github.com/anthropics/claude-code/blob/main/src/services/mcpClient.ts) + [src/tools/MCPTool/MCPTool.ts](https://github.com/anthropics/claude-code/blob/main/src/tools/MCPTool/MCPTool.ts)

```typescript
export async function getMCPTools(): Promise<Tool[]> {
  const mcpServers = getMcprcConfig()
  const tools: Tool[] = []
  
  for (const [name, config] of Object.entries(mcpServers)) {
    const client = new Client({
      name: `claude-code-${name}`,
      version: '1.0.0',
    })
    
    const transport = config.type === 'stdio'
      ? new StdioClientTransport(config)
      : new SSEClientTransport(config)
    
    const toolList = await client.listTools()
    tools.push(...toolList.tools)
  }
  
  return tools
}
```

### AutoOps AI Adaptation
AutoOps AI can dynamically register **remediation tools** from external services (cloud providers, monitoring systems).

**What to steal**:
- **Dynamic tool registration pattern**:
  ```python
  class MCPRemediationServer:
      """External service offering remediation actions via MCP."""
      
      async def list_remediations(self) -> List[RemediationTool]:
          """Fetch available remediations from server."""
          # E.g., AWS Systems Manager, Kubernetes operators, custom tools
          tools = []
          
          # Kubernetes MCP server
          k8s_tools = await self.fetch_k8s_remediations()
          # Azure automation runbook MCP server
          azure_tools = await self.fetch_azure_remediations()
          # Custom tools
          custom_tools = await self.fetch_custom_remediations()
          
          return tools
  ```

- **Config scopes** (project/global/environment):
  ```python
  # .autoopsrc
  remediation_servers:
    kubernetes:
      type: stdio
      command: python -m mcp_kubernetes_server
      scope: project
    aws_ssm:
      type: sse
      url: http://localhost:3001/sse
      scope: global
  ```

- **Tool approval** (similar to claude-code):
  ```python
  class RemediationToolApprovalRequest:
      """Request user approval to use external remediation tool."""
      tool_name: str  # "kubernetes:pod_restart"
      server_name: str  # "kubernetes"
      description: str
      risk_level: str
  ```

**Implementation**:
- AutoOps AI already has abstract `InfrastructureProvider`, but can extend to MCP-based providers
- Create `MCPProvider(InfrastructureProvider)` that discovers tools dynamically
- Adapt [MCPServerApprovalDialog.tsx](https://github.com/anthropics/claude-code/blob/main/src/components/MCPServerApprovalDialog.tsx) for remediation tool approval

---

## 8. Binary Feedback Loop

### Current State (Claude Code)
- **Model**: User accept/reject signals improve model behavior
- **Features**:
  - Tracks accept vs reject patterns
  - Feeds back to feature flags (Statsig)
  - Used for A/B testing
  - Correlates user feedback with model decisions
- **Source**: [src/components/binary-feedback/](https://github.com/anthropics/claude-code/blob/main/src/components/binary-feedback/) + [src/query.ts](https://github.com/anthropics/claude-code/blob/main/src/query.ts#L72-L90)

```typescript
const messagePairValidForBinaryFeedback = (
  m1: AssistantMessage,
  m2: AssistantMessage,
): boolean => {
  // Check if user accepted or rejected the assistant's code edits
  return m1.canAccept && m2.feedbackType !== 'none'
}
```

### AutoOps AI Adaptation
AutoOps AI can learn from **approval/denial patterns** to improve playbook matching.

**What to steal**:
- **Feedback collection**:
  ```python
  @dataclass
  class ApprovalFeedback:
      incident_id: str
      action: ApprovalAction  # APPROVE, DENY, INVESTIGATE
      confidence_before: float
      confidence_after: float
      user_id: str
      timestamp: datetime
      playbook_id: str  # If denied, why didn't the playbook apply?
      reasoning: str  # User-provided reasoning
  ```

- **Learning loop** (update playbooks based on denials):
  ```python
  class PlaybookLearner:
      async def learn_from_feedback(
          self,
          feedback: ApprovalFeedback,
      ) -> None:
          """Update playbook confidence based on user feedback."""
          if feedback.action == ApprovalAction.DENY:
              # Lower confidence of this playbook match
              playbook = load_playbook(feedback.playbook_id)
              playbook.confidence -= 0.1
              save_playbook(playbook)
              
              # Suggest better playbook
              better = find_better_playbook(feedback.incident_id)
              if better:
                  create_feedback_ticket(
                      f"Playbook {feedback.playbook_id} failed. "
                      f"Consider using {better.id} instead."
                  )
  ```

- **Statistical tracking**:
  ```python
  @dataclass
  class PlaybookStats:
      playbook_id: str
      total_matches: int
      approved_matches: int
      denied_matches: int
      avg_confidence: float
      
      @property
      def approval_rate(self) -> float:
          if self.total_matches == 0:
              return 0.0
          return self.approved_matches / self.total_matches
  ```

**Implementation**:
- Create [agents/feedback_loop.py](agents/feedback_loop.py) for learning
- Adapt [binary-feedback components](https://github.com/anthropics/claude-code/blob/main/src/components/binary-feedback/) for approval analytics in dashboard

---

## 9. Permission Enforcement Rules

### Current State (Claude Code)
- **Model**: Multi-level permission checks (exact match → prefix → user prompt)
- **Features**:
  - Whitelist-based approach
  - Prefix matching for commands
  - Subcommand parsing (e.g., git + status = "git status")
  - Tool-specific rules (bash ≠ file edit)
  - Config-based overrides
- **Source**: [src/permissions.ts](https://github.com/anthropics/claude-code/blob/main/src/permissions.ts) + [src/components/permissions/](https://github.com/anthropics/claude-code/blob/main/src/components/permissions/)

```typescript
export const bashToolCommandHasPermission = (
  tool: Tool,
  command: string,
  prefix: string | null,
  allowedTools: string[],
): boolean => {
  // Check exact match first
  if (bashToolCommandHasExactMatchPermission(tool, command, allowedTools)) {
    return true
  }
  // Check prefix match
  return allowedTools.includes(getPermissionKey(tool, { command }, prefix))
}
```

### AutoOps AI Adaptation
AutoOps AI needs **playbook step safeguards** to prevent dangerous sequences.

**What to steal**:
- **Execution constraint checking**:
  ```python
  class PlaybookStepConstraint:
      """Enforce safety rules on playbook steps."""
      
      FORBIDDEN_SEQUENCES = [
          # Don't allow db stop → db restart without health check
          ['database_stop', 'database_restart'],
          # Don't allow scale_down without scale_up verification
          ['scale_down_replicas', 'kill_connection'],
      ]
      
      REQUIRES_ROLLBACK = [
          'database_failover',
          'traffic_reroute',
          'certificate_renewal',
      ]
      
      @staticmethod
      def validate_step_sequence(
          playbook: Playbook,
          step_index: int,
      ) -> PermissionResult:
          """Check if step sequence is safe."""
          current_step = playbook.steps[step_index]
          
          # Check forbidden sequences
          if step_index > 0:
              prev_step = playbook.steps[step_index - 1]
              if [prev_step.action, current_step.action] in FORBIDDEN_SEQUENCES:
                  return PermissionResult(
                      result=False,
                      reason=f"Dangerous sequence: {prev_step} → {current_step}"
                  )
          
          # Check rollback requirements
          if current_step.action in REQUIRES_ROLLBACK:
              if not playbook.rollback_plan:
                  return PermissionResult(
                      result=False,
                      reason="Rollback plan required for this action"
                  )
          
          return PermissionResult(result=True)
  ```

- **Prefix-based action matching** (like command prefixes):
  ```python
  SAFE_PLAYBOOK_ACTIONS = {
      'cache_': ['redis_flush', 'memcache_purge'],  # All cache_* actions
      'log_': ['log_rotate', 'log_compress'],  # All log_* actions
      'metrics_': ['prometheus_reload', 'grafana_restart'],  # Stateless
  }
  
  def is_safe_action(action: str) -> bool:
      """Check if action matches safe prefix."""
      for prefix, actions in SAFE_PLAYBOOK_ACTIONS.items():
          if action.startswith(prefix):
              return True
      return False
  ```

- **Permission override config** (like allowedTools):
  ```yaml
  # playbooks/permissions.yaml
  allowed_dangerous_actions:
    production:
      - database_failover  # Only in prod, with HIGH approval
    staging:
      - database_snapshot
      - traffic_reroute
      
  forbidden_actions:
    all:
      - delete_database
      - purge_backups
  ```

**Implementation**:
- Create [agents/playbook_constraints.py](agents/playbook_constraints.py)
- Store constraint rules in `playbooks/constraints.yaml`

---

## Integration Priority & Timeline

### Phase 1 (Immediate - Week 1)
**High-impact, low-effort features:**

1. **Permission system** (#1) → Playbook whitelist + safe operations
   - Add `playbooks/safe_operations.yaml` with approved actions
   - Implement `can_auto_execute()` function
   - **Effort**: 2 hours

2. **Error handling** (#6) → Audit logging + error categorization
   - Integrate audit log store
   - Add error categorization enum
   - **Effort**: 3 hours

3. **Timeout management** (#3) → Enforce SLAs
   - Add timeout enforcement to remediation executor
   - Implement rollback on timeout
   - **Effort**: 2 hours

### Phase 2 (Short-term - Week 2-3)
**Medium-impact, moderate-effort features:**

4. **Configuration management** (#4) → Environment-specific configs
   - Implement hierarchical config loading
   - Add `config/` directory structure
   - **Effort**: 4 hours

5. **Approval dialogs** (#2) → Rich approval cards for dashboard
   - Adapt React components from claude-code
   - Create ApprovalCard dataclass
   - **Effort**: 6 hours

### Phase 3 (Medium-term - Week 4-5)
**High-impact, higher-effort features:**

6. **Incident history** (#5) → Searchable history + context caching
   - Implement IncidentHistory class
   - Add semantic search for similar incidents
   - **Effort**: 5 hours

7. **MCP integration** (#7) → Dynamic remediation tools
   - Create MCPProvider class
   - Add tool discovery + approval flow
   - **Effort**: 8 hours

8. **Binary feedback loop** (#8) → Learn from approvals/denials
   - Implement PlaybookLearner class
   - Add approval/denial tracking
   - **Effort**: 6 hours

### Phase 4 (Long-term - Week 6+)
**Research & advanced features:**

9. **Permission enforcement rules** (#9) → Playbook step constraints
    - Implement forbidden sequence detection
    - Add constraint YAML schema
    - **Effort**: 4 hours

### Phase 5 (Deferred)
**Internal team usage (lower priority):**

10. **Cost tracking** (#10) → Monitor remediation costs
    - Create `RemediationCost` dataclass (internal use only)
    - Track per-action costs in incident store
    - **Effort**: 2 hours

---

## Specific Files to Port/Adapt

| Claude Code File | Purpose | Target AutoOps AI File |
|---|---|---|
| [src/permissions.ts](https://github.com/anthropics/claude-code/blob/main/src/permissions.ts) | Permission check logic | `agents/playbook_constraints.py` |
| [src/history.ts](https://github.com/anthropics/claude-code/blob/main/src/history.ts) | Command history | `agents/incident_history.py` |
| [src/context.ts](https://github.com/anthropics/claude-code/blob/main/src/context.ts) | Context gathering | `agents/context.py` |
| [src/services/sentry.ts](https://github.com/anthropics/claude-code/blob/main/src/services/sentry.ts) | Error tracking | `agent/observability.py` |
| [src/utils/config.ts](https://github.com/anthropics/claude-code/blob/main/src/utils/config.ts) | Config management | `agent/config_manager.py` |
| [src/utils/PersistentShell.ts](https://github.com/anthropics/claude-code/blob/main/src/utils/PersistentShell.ts) | Timeout enforcement | `agent/remediation_executor.py` |
| [src/components/permissions/](https://github.com/anthropics/claude-code/blob/main/src/components/permissions/) | Approval UI dialogs | `frontend/components/ApprovalCard.tsx` |
| [src/services/mcpClient.ts](https://github.com/anthropics/claude-code/blob/main/src/services/mcpClient.ts) | MCP integration | `agent/mcp_provider.py` |
| [src/components/binary-feedback/](https://github.com/anthropics/claude-code/blob/main/src/components/binary-feedback/) | Feedback UI | `frontend/components/ApprovalAnalytics.tsx` |

---

## Code Examples: Quick Implementation Sketches

### Example 1: Safe Operations Whitelist
```python
# agents/safe_operations.py
from enum import Enum
from typing import Set, Dict

class RiskLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

# Define safe operations per risk level
SAFE_OPERATIONS_BY_RISK = {
    RiskLevel.LOW: {
        "redis_memory_purge",
        "log_rotation",
        "cache_clear",
        "dns_cache_flush",
        "temp_file_cleanup",
    },
    RiskLevel.MEDIUM: {
        "docker_restart_stateless_services",
        "scale_up_replicas",
        "update_configuration",
        "restart_worker_process",
    },
    RiskLevel.HIGH: {
        "database_failover",
        "primary_ip_change",
        "ssl_certificate_renewal",
    },
}

def can_auto_execute(action: str, risk_level: RiskLevel) -> bool:
    """Check if action is pre-approved for auto-execution."""
    safe_actions = SAFE_OPERATIONS_BY_RISK.get(risk_level, set())
    return action in safe_actions
```

### Example 2: Audit Logging with Error Context
```python
# agents/audit_log.py
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum

class AuditAction(Enum):
    INCIDENT_DETECTED = "incident_detected"
    PLAYBOOK_MATCHED = "playbook_matched"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    ACTION_EXECUTED = "action_executed"
    ACTION_FAILED = "action_failed"
    VERIFICATION_PASSED = "verification_passed"

@dataclass
class AuditLogEntry:
    timestamp: datetime
    incident_id: str
    action: AuditAction
    user_id: str
    session_id: str
    details: Dict[str, Any]
    error: Optional[str] = None
    
    def to_json(self) -> str:
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        data['action'] = self.action.value
        return json.dumps(data)

class AuditLogger:
    def __init__(self, log_file: str):
        self.log_file = log_file
    
    async def log(self, entry: AuditLogEntry) -> None:
        """Append audit entry to log (for compliance)."""
        with open(self.log_file, 'a') as f:
            f.write(entry.to_json() + '\n')
```

### Example 3: Timeout Enforcement with Rollback
```python
# agents/remediation_executor.py
import asyncio
from typing import Optional, Callable, Any

class RemediationExecutor:
    def __init__(self, timeout_seconds: int = 60):
        self.timeout_seconds = timeout_seconds
    
    async def execute_with_timeout(
        self,
        action: str,
        execute_fn: Callable[[], Any],
        rollback_fn: Optional[Callable[[], Any]] = None,
        timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute action with timeout, rollback on failure."""
        timeout = timeout_seconds or self.timeout_seconds
        
        try:
            result = await asyncio.wait_for(
                execute_fn(),
                timeout=timeout,
            )
            return {
                'status': 'success',
                'result': result,
                'elapsed_seconds': timeout,
            }
        
        except asyncio.TimeoutError:
            # Timeout exceeded - execute rollback
            if rollback_fn:
                try:
                    await asyncio.wait_for(rollback_fn(), timeout=timeout / 2)
                    rollback_status = 'success'
                except Exception as e:
                    rollback_status = f'failed: {str(e)}'
            else:
                rollback_status = 'no_rollback_defined'
            
            return {
                'status': 'timeout',
                'timeout_seconds': timeout,
                'rollback_status': rollback_status,
            }
        
        except Exception as e:
            return {
                'status': 'failed',
                'error': str(e),
            }
```

---

## Recommendations & Next Steps

### ✅ Do This
1. **Port permission system** → Start with safe_operations.yaml whitelist (low risk, high value)
2. **Add audit logging** → Implement AuditLogEntry + AuditLogger for compliance
3. **Integrate timeout enforcement** → Prevent runaway remediation actions
4. **Adapt approval card UI** → Use claude-code React components as template

### ⚠️ Nice-to-Have (Defer)
5. MCP integration (nice for extensibility, but complex)
6. Binary feedback loop (requires statistical analysis, not critical MVP)
7. Advanced constraint checking (start simple, iterate)
8. Cost tracking (internal team usage, lower priority)

### 🚫 Don't Do This
- Don't try to directly use TypeScript code in Python AutoOps AI (rewrite in Python)
- Don't copy UI components verbatim; adapt them for AutoOps AI's dashboard
- Don't implement all 9 critical features at once; prioritize based on MVP requirements

---

## Conclusion

The **claude-code-sourcemap** repository provides proven patterns for:
- **Approval workflows** (permission checks, approval dialogs)
- **Observability** (error tracking, cost tracking, audit logs)
- **Configuration management** (hierarchical config, environment-specific overrides)
- **Tool execution safety** (timeouts, rollback, constraints)

AutoOps AI can **immediately adopt patterns #1, #3, #4, #7** (permission, cost, timeout, observability) with **4-6 hours of focused porting work** and immediately improve **MVP reliability, auditability, and user trust**.

Features #5, #6, #8, #9, #10 are **medium-to-long term enhancements** that scale the system beyond the initial demo but are not critical for the hackathon MVP.

---

**Document Version**: 1.0  
**Last Updated**: April 2, 2026  
**Prepared for**: AutoOps AI Team
