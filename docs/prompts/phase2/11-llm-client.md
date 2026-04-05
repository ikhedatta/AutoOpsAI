# [Step 11] — Ollama LLM Client

## Context

Steps 01-10 are complete. The following exist:
- `agent/models.py` — `Anomaly`, `Diagnosis`, `MetricSnapshot`, `LogEntry`, `RiskLevel`
- `agent/knowledge/schemas.py` — `PlaybookMatch`, `PlaybookEntry`
- `agent/config.py` — `ollama_host`, `ollama_model`, `ollama_timeout_seconds`
- `agent/llm/__init__.py` — package exists

## Objective

Produce an Ollama Python SDK wrapper with structured JSON output, exponential backoff retry, graceful fallback when Ollama is unreachable, and typed prompt template functions.

## Files to Create

- `agent/llm/client.py` — `OllamaClient` class.
- `agent/llm/prompts.py` — Prompt template functions (typed arguments, return strings).
- `tests/test_llm_client.py` — Unit tests with mocked ollama SDK responses.

## Files to Modify

None.

## Key Requirements

**ALL LLM INFERENCE IS LOCAL VIA OLLAMA. No calls to OpenAI, Anthropic, or any external LLM service. This is a hard constraint.**

**agent/llm/client.py:**

```python
class OllamaClient:
    def __init__(self, host: str, model: str, timeout_seconds: int = 30):
        self.host = host
        self.model = model
        self.timeout = timeout_seconds
        self._client = ollama.AsyncClient(host=host)

    async def warm_up(self) -> bool:
        """
        Send a minimal prompt to pre-load the model into GPU/CPU memory.
        Returns True if successful, False if Ollama is unreachable.
        Called once at startup.
        """

    async def diagnose(
        self,
        anomaly: Anomaly,
        snapshots: list[MetricSnapshot],
        playbook_match: Optional[PlaybookMatch],
        logs: list[LogEntry],
    ) -> Diagnosis:
        """
        Ask the LLM to diagnose an anomaly.
        Uses format="json" for structured output.
        Falls back to playbook diagnosis if Ollama is unreachable.
        """

    async def explain_for_human(self, diagnosis: Diagnosis, incident_title: str) -> str:
        """
        Generate a concise plain-language explanation of the diagnosis.
        Suitable for Teams/dashboard approval card.
        Returns a single paragraph string.
        Falls back to diagnosis.summary if Ollama unreachable.
        """

    async def reason_novel_issue(
        self,
        service_name: str,
        snapshots: list[MetricSnapshot],
        logs: list[LogEntry],
        prometheus_context: list[dict],
    ) -> Diagnosis:
        """
        For issues with no playbook match — LLM reasons from raw metrics and logs.
        Returns a Diagnosis with lower confidence (0.4–0.6 range).
        Falls back to a minimal Diagnosis if Ollama unreachable.
        """

    async def generate_incident_summary(
        self,
        incident_title: str,
        service: str,
        diagnosis: Diagnosis,
        actions_taken: list[str],
        resolution_time_seconds: Optional[float],
    ) -> str:
        """
        Generate a one-paragraph incident summary for Teams notification and audit log.
        Falls back to a template string if Ollama unreachable.
        """

    async def _chat_with_retry(
        self,
        messages: list[dict],
        use_json_format: bool = True,
        max_retries: int = 3,
    ) -> Optional[str]:
        """
        Internal method: call ollama.AsyncClient.chat() with exponential backoff.
        Returns the message content string, or None if all retries fail.
        Exponential backoff: wait 1s, 2s, 4s between retries.
        """
```

**Ollama SDK usage:**
```python
import ollama

response = await self._client.chat(
    model=self.model,
    messages=messages,
    format="json",    # structured JSON output
    options={"temperature": 0.1, "num_predict": 500},
)
content = response["message"]["content"]
```

**JSON parsing for `diagnose()`:**
The LLM returns JSON. Parse it with `json.loads(content)`. Expected JSON schema from the LLM:
```json
{
  "summary": "string",
  "confidence": 0.0-1.0,
  "root_cause": "string",
  "recommended_actions": ["string"],
  "llm_reasoning": "string"
}
```
If parsing fails, log a warning and return a `Diagnosis` with `confidence=0.3` and `summary` set to the raw content.

**Fallback behavior when Ollama is unreachable:**
- `diagnose()`: if `playbook_match` is provided, return `Diagnosis(summary=playbook_match.playbook.diagnosis, confidence=0.7, matched_playbook=playbook_match.playbook.id)`
- If no playbook match either: return `Diagnosis(summary=f"Anomaly detected: {anomaly.message}", confidence=0.3)`
- `explain_for_human()`: return `diagnosis.summary`
- `reason_novel_issue()`: return `Diagnosis(summary=f"Novel issue detected on {service_name}. Manual investigation recommended.", confidence=0.3)`
- `generate_incident_summary()`: return `f"{incident_title} on {service} — {diagnosis.summary}"`

**agent/llm/prompts.py:**

```python
def system_prompt() -> str:
    """System prompt establishing the agent's role and output requirements."""
    # Returns a prompt that:
    # - Establishes role: "You are AutoOps AI, a virtual DevOps engineer..."
    # - Specifies output format: JSON only, no markdown, no explanation outside JSON
    # - Specifies tone: technical but plain-language, suitable for ops engineers
    # - Includes safety: "Never recommend deleting data or destroying infrastructure without escalation"

def diagnosis_prompt(
    anomaly: Anomaly,
    snapshots: list[MetricSnapshot],
    playbook_context: Optional[str],    # playbook.diagnosis text or None
    recent_logs: list[str],             # last N log lines as strings
) -> str:
    """
    Build the user message for diagnose().
    Includes: anomaly details, top 3 most relevant metric snapshots, last 20 log lines,
    and playbook context if available.
    Specifies the exact JSON output schema.
    Keeps total prompt under ~800 tokens for small models.
    """

def novel_issue_prompt(
    service_name: str,
    snapshots: list[MetricSnapshot],
    recent_logs: list[str],
    prometheus_context: list[dict],
) -> str:
    """
    Build the user message for reason_novel_issue().
    No playbook context. Asks LLM to reason from raw data.
    """

def summary_prompt(
    incident_title: str,
    service: str,
    diagnosis_summary: str,
    actions_taken: list[str],
    resolution_time_seconds: Optional[float],
) -> str:
    """
    Build the user message for generate_incident_summary().
    Asks for a plain-language paragraph suitable for a Teams notification.
    """
```

All prompt functions must return plain strings (not lists of dicts). The `_chat_with_retry` method assembles the messages list from `[{"role": "system", "content": system_prompt()}, {"role": "user", "content": <specific_prompt>}]`.

**tests/test_llm_client.py:**

Use `unittest.mock.AsyncMock` to patch `ollama.AsyncClient.chat`. All tests `@pytest.mark.asyncio`.

Required test cases:
1. `test_diagnose_success` — mock returns valid JSON, assert `Diagnosis` object with correct confidence.
2. `test_diagnose_invalid_json_fallback` — mock returns non-JSON string, assert `Diagnosis` returned with `confidence=0.3`.
3. `test_diagnose_connection_error_with_playbook_fallback` — mock raises exception, playbook_match provided, assert uses playbook diagnosis.
4. `test_diagnose_connection_error_no_playbook` — mock raises, no playbook, assert minimal Diagnosis returned.
5. `test_retry_on_failure` — mock fails twice then succeeds on third call, assert success and that chat was called 3 times.
6. `test_explain_for_human_fallback` — mock raises, assert `diagnosis.summary` is returned.
7. `test_warm_up_unreachable` — mock raises, assert `warm_up()` returns `False` without crashing.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_llm_client.py -v
# Expected: all 7 tests pass

# Verify imports
python -c "
from agent.llm.client import OllamaClient
from agent.llm.prompts import system_prompt, diagnosis_prompt, novel_issue_prompt, summary_prompt
print('LLM client imports OK')
# Verify system_prompt is non-empty
assert len(system_prompt()) > 100
print('system_prompt has content OK')
"
```

## Dependencies

- Step 01 (ollama Python SDK installed)
- Step 02 (core models — `Anomaly`, `Diagnosis`, `MetricSnapshot`, `LogEntry`)
- Step 10 (playbook schemas — `PlaybookMatch`)
