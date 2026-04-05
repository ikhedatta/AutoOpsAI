# Reference Features Analysis — Prioritized for AutoOps AI

Patterns extracted from **claude-code-sourcemap** (TypeScript) and **claw-code** (Python)
reference projects, mapped to AutoOps AI with implementation priority.

## Priority Legend

| Priority | Meaning | Effort | Impact |
|----------|---------|--------|--------|
| **P0** | Implement now — core to prompt + tool work | Low–Med | High |
| **P1** | Implement soon — significant reliability/quality gain | Medium | High |
| **P2** | Implement later — production hardening | Medium | Medium |
| **P3** | Future — advanced features after core is stable | High | Medium |

---

## P0 — Implement Now

### 1. Composable System Prompt (claude-code `constants/prompts.ts`)
**Source:** System prompt built as array of blocks, concatenated. Each block independently testable.
**Apply to:** `agent/llm/prompts.py` — replace monolithic `SYSTEM_PROMPT` with composable blocks:
`_identity_block()`, `_reasoning_block()`, `_capabilities_block()`, `_safety_block()`, `_output_discipline_block()`.
**Why:** Current prompt is generic; small models (4B) need explicit structure to reason well. Zero latency cost.

### 2. Tool-Specific Sub-Prompts (claude-code `tools/*/prompt.ts`)
**Source:** Each tool has a dedicated `prompt.ts` explaining when/how the LLM should use it, with examples and constraints.
**Apply to:** `agent/llm/prompts.py` — add `_tool_instructions_block()` to chat prompts with per-tool usage rules.
**Why:** Without explicit guidance, small models call tools randomly or not at all.

### 3. Frozen Dataclass Tool Definitions (claw-code `tools.py`)
**Source:** `@dataclass(frozen=True)` for immutable tool definitions with `@lru_cache` registry. Clean separation of schema from execution.
**Apply to:** New `agent/llm/tools.py` — define 7 read-only chat tools as frozen dataclasses.
**Why:** Immutability prevents accidental mutation; caching avoids repeated schema construction.

### 4. Structured ToolResult (claw-code `tools.py` + claude-code `query.ts`)
**Source:** Separate `ToolResult` dataclass with `success`, `output`, `error` fields. Model sees structured result, not raw exception.
**Apply to:** New `agent/llm/tool_executor.py` — all tool outputs wrapped in `ToolResult`.
**Why:** Raw exceptions crash the agent loop; structured errors let the LLM reason about failures.

### 5. Agent Loop for Tool Calling (claude-code `query.ts` + POC `agent.py`)
**Source:** Recursive: send messages+tools → handle tool_calls → feed results back → loop until text response. Max iterations enforced.
**Apply to:** `agent/llm/client.py` — new `chat_with_tools()` method.
**Why:** Current chat is pure text inference on a static snapshot. Tool-calling lets it query live data.

### 6. Chain-of-Thought Scaffolding in Prompts
**Source:** claude-code `ArchitectTool/prompt.ts` — explicit reasoning steps: "1. Analyze requirements, 2. Define approach, 3. Break down into steps."
**Apply to:** `agent/llm/prompts.py` — rewrite `diagnosis_prompt()` and `novel_issue_prompt()` with explicit reasoning steps.
**Why:** Small models need step-by-step scaffolding to produce coherent multi-step reasoning.

### 7. Action Type Constraint in Prompts
**Source:** claude-code BashTool prompt bans commands (`BANNED_COMMANDS`), constraining LLM output to valid options only.
**Apply to:** `agent/llm/prompts.py` — constrain `recommended_actions` to the actual executor action types: `restart_service`, `scale_service`, `exec_command`, `collect_logs`, `health_check`, `escalate`, `wait`.
**Why:** Currently the LLM hallucinates free-text actions that the executor can't parse.

### 8. Few-Shot Example in Prompts
**Source:** Common practice for small models; claude-code includes inline examples in tool prompts.
**Apply to:** `agent/llm/prompts.py` — add `FEW_SHOT_DIAGNOSIS` constant (~150 tokens).
**Why:** 4B models improve dramatically with even one example of ideal output.

---

## P1 — Implement Soon

### 9. Multi-Level Tool Validation Pipeline (claude-code `query.ts`)
**Source:** Three-stage validation: Zod schema parse → custom `validateInput()` → permission `canUseTool()`. Invalid inputs caught before execution.
**Apply to:** `agent/llm/tool_executor.py` — validate tool name exists → validate argument types → check permission deny-list → execute.
**Why:** Prevents the executor from crashing on malformed tool calls from the LLM.

### 10. Permission Deny-List (claw-code `permissions.py`)
**Source:** `ToolPermissionContext` with `deny_names: frozenset` and `deny_prefixes: tuple`. Case-insensitive matching.
**Apply to:** `agent/llm/tool_executor.py` — ensure write tools (`restart_service`, `scale_service`, `exec_command`) are never callable from chat.
**Why:** Safety boundary: chat must not bypass the approval flow.

### 11. Output Truncation / Middle-Elision (claude-code `query.ts`)
**Source:** Tool output >10KB truncated: `[first N chars]... (X chars truncated) ...[last N chars]`.
**Apply to:** `agent/llm/tool_executor.py` — truncate at 2KB (appropriate for 4B model context windows).
**Why:** Large log outputs would consume the entire context window, degrading reasoning quality.

### 12. Exponential Retry with Backoff (claude-code `services/claude.ts`)
**Source:** `500ms × 2^(attempt-1)`, max 32s, max 10 retries. Honors server `retry-after` header. Retries on 408/429/5xx.
**Apply to:** `agent/llm/client.py` — current retry uses tenacity with 2 attempts. Increase to 3 attempts for tool-calling, keep 2 for diagnosis.
**Why:** Tool-calling loops are more latency-tolerant; retrying prevents transient Ollama failures from killing the interaction.

### 13. Graceful Error Messages by Type (claude-code `services/claude.ts`)
**Source:** `getAssistantMessageFromError()` maps error types to user-friendly messages: "prompt too long", "credit balance low", "invalid key".
**Apply to:** `agent/llm/client.py` — current fallback returns generic "trouble connecting". Add specific messages for timeout, model not found, context too long.
**Why:** Better error UX for operators.

### 14. Concurrent Read-Only / Serial Write Execution (claude-code `query.ts`)
**Source:** Read-only tools run in parallel (max 10 concurrent). Write tools execute sequentially.
**Apply to:** `agent/llm/client.py` — in `chat_with_tools()`, since all chat tools are read-only, execute tool_calls concurrently with `asyncio.gather()`.
**Why:** If the LLM calls 2-3 tools at once, concurrent execution saves 1-3s vs sequential.

### 15. ThinkTool — Reasoning Scratchpad (claude-code `tools/ThinkTool`)
**Source:** No-op tool that accepts a `thought` string, logs it, returns "Your thought has been logged." Zero execution cost.
**Apply to:** Add a `think` tool to chat tool schemas. The model can use it to reason before answering.
**Why:** Improves reasoning quality on complex questions at zero execution cost. Especially useful for small models.

### 16. Dual Result Formatting (claude-code tool pattern)
**Source:** Each tool has `renderResultForAssistant()` (compact for LLM) and `renderToolResultMessage()` (rich for UI).
**Apply to:** `agent/llm/tool_executor.py` — format tool results compactly for LLM (JSON summary), but store full details in chat history for the dashboard.
**Why:** LLM sees concise data (saves tokens); operators see full data in UI.

---

## P2 — Implement Later

### 17. Context Snapshot Memoization (claude-code `context.ts`)
**Source:** `getContext = memoize(async () => {...})` — git status, directory structure, README all cached once per conversation, not re-collected per query.
**Apply to:** Cache `collector.collect_once()` results for ~30s in the chat endpoint. Avoid re-collecting metrics for rapid chat exchanges.
**Why:** If operator asks 5 questions in 2 minutes, no need to re-poll Docker 5 times.

### 18. Token/Cost Tracking (claude-code `cost-tracker.ts`, claw-code `cost_tracker.py`)
**Source:** In-memory accumulator: `total_cost += per_request_cost`. Per-request telemetry: TTFT, duration, cache breakdowns.
**Apply to:** Track `input_tokens`, `output_tokens`, `total_requests` per chat session. Store in incident timeline for audit.
**Why:** Visibility into LLM usage costs and latency for production monitoring.

### 19. Turn Limits and Token Budgets (claw-code `QueryEngine.py`)
**Source:** `max_turns: 8`, `max_budget_tokens: 2000`. Early return if exceeded. Prevents runaway loops.
**Apply to:** `agent/llm/client.py` — config-driven `chat_max_tool_iterations` (already planned). Add optional token budget check per chat session.
**Why:** Prevents a chat session from consuming excessive resources.

### 20. Session Persistence and Replay (claw-code `session_store.py`)
**Source:** Store session as JSON: `{session_id, messages, input_tokens, output_tokens}`. Enable full replay.
**Apply to:** Already partially done (chat history in MongoDB). Extend to store tool calls and results in the timeline.
**Why:** Audit trail for debugging + compliance.

### 21. Transcript Compaction / Sliding Window (claw-code `QueryEngine.py` + `transcript.py`)
**Source:** `compact_messages_if_needed()` — keep only last N turns in context, discard older ones.
**Apply to:** `agent/llm/client.py` — for multi-turn chat sessions, keep last 10 messages in context to avoid context overflow on 4B models.
**Why:** 4B models have ~8K context. Long chat sessions will overflow without compaction.

### 22. MCP Server Integration Pattern (claude-code `services/mcpClient.ts`)
**Source:** External tools loaded dynamically via MCP protocol. Tool names namespaced: `mcp__{server}__{tool}`. 5s connection timeout. `Promise.allSettled()` for fault tolerance.
**Apply to:** Future: allow external tool servers (Prometheus query API, Grafana API) via MCP-like plugin system.
**Why:** Extensibility for adding new data sources without code changes.

### 23. Warm-Up / Prefetch (claw-code `prefetch.py`, existing `warm_up()`)
**Source:** Trust-gated prefetch at startup: model load, keychain, project scan.
**Apply to:** Current `llm.warm_up()` already pre-loads model. Extend to prefetch tool schemas and validate provider connectivity at startup.
**Why:** Avoids cold-start latency on first chat request.

### 24. Command History Deduplication (claude-code `history.ts`)
**Source:** `if (history[0] === command) return;` — simple FIFO with dedup.
**Apply to:** Chat history endpoint — deduplicate identical consecutive messages (prevents double-submit bugs).
**Why:** UX cleanup.

---

## P3 — Future

### 25. Sub-Agent Delegation (claude-code `AgentTool`)
**Source:** Spawns a nested agent with restricted tool access (read-only). Tracks tool use count, token stats, duration. Results flattened back to parent.
**Apply to:** For complex incidents, spawn a diagnostic sub-agent that runs multiple tool calls autonomously, then reports back to the main agent. The main agent decides on remediation.
**Why:** Separates investigation (safe, parallelizable) from action (needs approval).

### 26. Architect / Planner Tool (claude-code `ArchitectTool`)
**Source:** Separate planning mode: "Analyze requirements → Define approach → Break into steps. Do NOT implement, just plan."
**Apply to:** Add a `plan_remediation` tool that creates a step-by-step remediation plan before execution. Operator reviews plan before approving.
**Why:** More transparent decision-making; gives operators a preview of what the agent intends to do.

### 27. Prompt Caching / Cache Breakpoints (claude-code `services/claude.ts`)
**Source:** Last 3 messages get `cache_control: { type: 'ephemeral' }`. System prompt blocks split for cache optimization. 92% cost savings on cache reads.
**Apply to:** Not directly applicable to Ollama (local inference). But if AutoOps moves to cloud LLM (OpenAI, Anthropic), implement prompt caching.
**Why:** Massive cost savings for cloud LLM deployments.

### 28. VCR Test Fixtures (claude-code `services/vcr.ts`)
**Source:** Hash message content → filename. Record LLM responses as fixtures. Dehydrate paths/durations. Deterministic testing without API calls.
**Apply to:** Record Ollama responses during integration tests. Replay for CI without requiring running Ollama.
**Why:** Faster, deterministic CI; no GPU required for test runs.

### 29. Execution Registry Pattern (claw-code `execution_registry.py`)
**Source:** Centralized registry: `@dataclass(frozen=True) class ExecutionRegistry` with `command()` and `tool()` lookup methods. Case-insensitive.
**Apply to:** Future: if tool count grows beyond 10, create a formal registry with dynamic registration, filtering, and search.
**Why:** Currently 7 tools can be managed with a simple dict. Registry pattern is overkill until tool count grows.

### 30. Streaming Events for Tool Execution (claw-code `QueryEngine.py`)
**Source:** Yield-based event emission: `message_start → command_match → tool_match → message_delta → message_stop`.
**Apply to:** Extend the SSE chat stream to emit tool execution events: `tool_call_start`, `tool_call_result`, `thinking`, `final_response`.
**Why:** Real-time feedback in dashboard during tool-augmented chat.

### 31. Deferred/Trust-Gated Initialization (claw-code `deferred_init.py`)
**Source:** Trust level controls subsystem initialization. `DeferredInitResult` flags which features are enabled.
**Apply to:** Feature flags for tool-calling, auto-remediation tiers, etc. Controlled by config.
**Why:** Gradual rollout of new capabilities without code changes.

---

## Implementation Order Summary

```
Sprint 1 (P0 — Now):
  ├─ 1. Composable system prompt blocks
  ├─ 6. Chain-of-thought diagnosis scaffolding
  ├─ 7. Action type constraint
  ├─ 8. Few-shot example
  ├─ 2. Tool-specific sub-prompts for chat
  ├─ 3. Frozen dataclass tool definitions
  ├─ 4. Structured ToolResult
  └─ 5. Agent loop (chat_with_tools)

Sprint 2 (P1 — Soon):
  ├─ 9.  Multi-level validation pipeline
  ├─ 10. Permission deny-list
  ├─ 11. Output truncation
  ├─ 12. Retry improvements
  ├─ 13. Graceful error messages
  ├─ 14. Concurrent tool execution
  ├─ 15. ThinkTool
  └─ 16. Dual result formatting

Sprint 3 (P2 — Later):
  ├─ 17. Context memoization
  ├─ 18. Token/cost tracking
  ├─ 19. Turn limits + budgets
  ├─ 20. Session persistence
  ├─ 21. Transcript compaction
  ├─ 22. MCP integration
  ├─ 23. Enhanced warm-up
  └─ 24. History deduplication

Backlog (P3 — Future):
  ├─ 25. Sub-agent delegation
  ├─ 26. Architect/planner tool
  ├─ 27. Prompt caching (cloud LLM)
  ├─ 28. VCR test fixtures
  ├─ 29. Execution registry
  ├─ 30. Streaming tool events
  └─ 31. Deferred initialization
```
