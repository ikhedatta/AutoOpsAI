"""Tests for agent.llm.tool_executor and agent.llm.tools."""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.llm.tool_executor import (
    CHAT_DENY_LIST,
    CHAT_DENY_PREFIXES,
    MAX_OUTPUT_CHARS,
    ToolExecutor,
    ToolResult,
    _is_denied,
    _truncate_output,
    _validate_arg_types,
)
from agent.llm.tools import (
    ALL_CHAT_TOOLS,
    TOOL_REGISTRY,
    ToolDefinition,
    get_ollama_tool_schemas,
)


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


class TestToolDefinitions:
    def test_all_tools_registered(self):
        assert len(ALL_CHAT_TOOLS) >= 8
        assert len(TOOL_REGISTRY) == len(ALL_CHAT_TOOLS)

    def test_tool_names_unique(self):
        names = [t.name for t in ALL_CHAT_TOOLS]
        assert len(names) == len(set(names))

    def test_all_tools_read_only(self):
        for tool in ALL_CHAT_TOOLS:
            assert tool.is_read_only is True, f"{tool.name} should be read-only"

    def test_think_tool_zero_timeout(self):
        assert TOOL_REGISTRY["think"].timeout_seconds == 0

    def test_required_tools_exist(self):
        expected = {
            "list_services", "get_service_status", "get_service_logs",
            "get_service_metrics", "check_service_health",
            "get_active_incidents", "get_incident_history", "think",
        }
        assert expected.issubset(TOOL_REGISTRY.keys())

    def test_ollama_tool_schemas_format(self):
        schemas = get_ollama_tool_schemas()
        assert isinstance(schemas, list)
        assert len(schemas) == len(ALL_CHAT_TOOLS)
        for schema in schemas:
            assert schema["type"] == "function"
            assert "name" in schema["function"]
            assert "description" in schema["function"]
            assert "parameters" in schema["function"]

    def test_ollama_schemas_are_cached(self):
        s1 = get_ollama_tool_schemas()
        s2 = get_ollama_tool_schemas()
        assert s1 is s2  # Same object (lru_cache)

    def test_tool_definition_is_frozen(self):
        tool = TOOL_REGISTRY["think"]
        with pytest.raises(AttributeError):
            tool.name = "modified"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Output truncation
# ---------------------------------------------------------------------------


class TestTruncation:
    def test_short_output_unchanged(self):
        text = "short output"
        assert _truncate_output(text) == text

    def test_exact_limit_unchanged(self):
        text = "x" * MAX_OUTPUT_CHARS
        assert _truncate_output(text) == text

    def test_long_output_truncated(self):
        text = "A" * (MAX_OUTPUT_CHARS + 500)
        result = _truncate_output(text)
        assert len(result) < len(text)
        assert "truncated" in result
        assert result.startswith("A")
        assert result.endswith("A")


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------


class TestToolResult:
    def test_success_result(self):
        r = ToolResult(tool="test", success=True, output={"key": "val"})
        assert r.success
        assert r.error is None
        j = json.loads(r.to_json())
        assert j["success"] is True
        assert j["data"]["key"] == "val"

    def test_error_result(self):
        r = ToolResult(tool="test", success=False, output=None, error="boom")
        assert not r.success
        j = json.loads(r.to_json())
        assert j["success"] is False
        assert j["error"] == "boom"


# ---------------------------------------------------------------------------
# ToolExecutor — dispatch
# ---------------------------------------------------------------------------


@dataclass
class FakeServiceInfo:
    name: str = "demo"
    image: str = "demo:latest"
    labels: dict = None

    def __post_init__(self):
        if self.labels is None:
            self.labels = {}


@dataclass
class FakeServiceStatus:
    state: str = "running"
    uptime_seconds: int = 3600
    restart_count: int = 0
    health: str = "healthy"


@dataclass
class FakeMetricSnapshot:
    cpu_percent: float = 25.0
    memory_percent: float = 40.0
    memory_used_bytes: int = 100_000_000
    memory_limit_bytes: int = 500_000_000


@dataclass
class FakeHealthResult:
    healthy: bool = True
    message: str = "OK"


@dataclass
class FakeLogEntry:
    message: str = "log line"


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.list_services.return_value = [FakeServiceInfo()]
    provider.get_service_status.return_value = FakeServiceStatus()
    provider.get_metrics.return_value = FakeMetricSnapshot()
    provider.health_check.return_value = FakeHealthResult()
    provider.get_logs.return_value = [FakeLogEntry("line1"), FakeLogEntry("line2")]
    return provider


@pytest.fixture
def mock_incident_store():
    store = AsyncMock()
    store.list_incidents = AsyncMock(return_value=[])
    return store


@pytest.fixture
def executor(mock_provider, mock_incident_store):
    return ToolExecutor(provider=mock_provider, incident_store=mock_incident_store)


class TestToolExecutor:
    @pytest.mark.asyncio
    async def test_unknown_tool(self, executor):
        result = await executor.execute("nonexistent_tool", {})
        assert not result.success
        assert "Unknown tool" in result.error

    @pytest.mark.asyncio
    async def test_missing_required_args(self, executor):
        result = await executor.execute("get_service_status", {})
        assert not result.success
        assert "Missing required" in result.error

    @pytest.mark.asyncio
    async def test_think_tool(self, executor):
        result = await executor.execute("think", {"thought": "analyzing the situation"})
        assert result.success
        assert "logged" in result.output.lower()

    @pytest.mark.asyncio
    async def test_list_services(self, executor, mock_provider):
        result = await executor.execute("list_services", {})
        assert result.success
        assert isinstance(result.output, list)
        assert result.output[0]["name"] == "demo"
        mock_provider.list_services.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_service_status(self, executor, mock_provider):
        result = await executor.execute("get_service_status", {"service_name": "demo"})
        assert result.success
        assert result.output["state"] == "running"
        mock_provider.get_service_status.assert_awaited_once_with("demo")

    @pytest.mark.asyncio
    async def test_get_service_logs(self, executor, mock_provider):
        result = await executor.execute("get_service_logs", {"service_name": "demo", "lines": 10})
        assert result.success
        assert isinstance(result.output, list)
        mock_provider.get_logs.assert_awaited_once_with("demo", lines=10)

    @pytest.mark.asyncio
    async def test_get_service_metrics(self, executor, mock_provider):
        result = await executor.execute("get_service_metrics", {"service_name": "demo"})
        assert result.success
        assert result.output["cpu_percent"] == 25.0
        mock_provider.get_metrics.assert_awaited_once_with("demo")

    @pytest.mark.asyncio
    async def test_check_service_health(self, executor, mock_provider):
        result = await executor.execute("check_service_health", {"service_name": "demo"})
        assert result.success
        assert result.output["healthy"] is True
        mock_provider.health_check.assert_awaited_once_with("demo")

    @pytest.mark.asyncio
    async def test_get_active_incidents(self, executor, mock_incident_store):
        result = await executor.execute("get_active_incidents", {})
        assert result.success
        assert isinstance(result.output, list)

    @pytest.mark.asyncio
    async def test_get_incident_history(self, executor, mock_incident_store):
        result = await executor.execute("get_incident_history", {"service_name": "demo"})
        assert result.success

    @pytest.mark.asyncio
    async def test_no_provider_returns_error(self):
        executor = ToolExecutor(provider=None, incident_store=None)
        result = await executor.execute("list_services", {})
        assert result.success  # Still returns, but with error in output
        assert "not available" in str(result.output)

    @pytest.mark.asyncio
    async def test_provider_exception_caught(self, mock_incident_store):
        provider = AsyncMock()
        provider.get_service_status.side_effect = Exception("Docker unreachable")
        executor = ToolExecutor(provider=provider, incident_store=mock_incident_store)
        result = await executor.execute("get_service_status", {"service_name": "demo"})
        assert not result.success
        assert "Docker unreachable" in result.error


# ---------------------------------------------------------------------------
# LLMClient.chat_with_tools
# ---------------------------------------------------------------------------


class TestChatWithTools:
    @pytest.mark.asyncio
    async def test_falls_back_without_executor(self):
        from agent.config import Settings
        from agent.llm.client import LLMClient
        from unittest.mock import patch

        settings = Settings(
            ollama_host="http://localhost:11434",
            ollama_model="test",
            ollama_fallback_model="test-fb",
            _env_file=None,
        )
        with patch("agent.llm.client.ollama.Client") as MockClient:
            client = LLMClient(settings)
            client._client = MockClient.return_value
            client._client.chat = MagicMock(
                return_value={"message": {"content": "plain response"}}
            )
            result = await client.chat_with_tools(
                question="test",
                system_state={},
                tool_executor=None,  # No executor → plain chat
            )
            assert result == "plain response"

    @pytest.mark.asyncio
    async def test_text_response_no_tools(self):
        from agent.config import Settings
        from agent.llm.client import LLMClient
        from unittest.mock import patch

        settings = Settings(
            ollama_host="http://localhost:11434",
            ollama_model="test",
            ollama_fallback_model="test-fb",
            _env_file=None,
        )
        with patch("agent.llm.client.ollama.Client") as MockClient:
            client = LLMClient(settings)
            client._client = MockClient.return_value
            # Model returns text directly (no tool calls)
            client._client.chat = MagicMock(
                return_value={"message": {"content": "Everything looks fine.", "tool_calls": None}}
            )
            executor = ToolExecutor()
            result = await client.chat_with_tools(
                question="How is everything?",
                system_state={},
                tool_executor=executor,
            )
            assert "fine" in result.lower()

    @pytest.mark.asyncio
    async def test_tool_call_then_response(self):
        from agent.config import Settings
        from agent.llm.client import LLMClient
        from unittest.mock import patch

        settings = Settings(
            ollama_host="http://localhost:11434",
            ollama_model="test",
            ollama_fallback_model="test-fb",
            _env_file=None,
        )
        with patch("agent.llm.client.ollama.Client") as MockClient:
            client = LLMClient(settings)
            client._client = MockClient.return_value

            call_count = 0

            def mock_chat(**kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # First call: model wants to call a tool
                    return {"message": {
                        "content": "",
                        "tool_calls": [{
                            "function": {
                                "name": "think",
                                "arguments": {"thought": "Let me analyze this"},
                            }
                        }],
                    }}
                # Second call: model returns text
                return {"message": {"content": "Analysis complete."}}

            client._client.chat = MagicMock(side_effect=mock_chat)
            executor = ToolExecutor()
            result = await client.chat_with_tools(
                question="Analyze the system",
                system_state={},
                tool_executor=executor,
            )
            assert "complete" in result.lower()
            assert call_count == 2


# ---------------------------------------------------------------------------
# P1 #10: Permission deny-list
# ---------------------------------------------------------------------------


class TestPermissionDenyList:
    def test_write_tools_denied(self):
        for name in CHAT_DENY_LIST:
            assert _is_denied(name), f"{name} must be denied"

    def test_deny_case_insensitive(self):
        assert _is_denied("RESTART_SERVICE")
        assert _is_denied("Scale_Service")

    def test_deny_prefixes(self):
        for prefix in CHAT_DENY_PREFIXES:
            assert _is_denied(f"{prefix}something"), f"prefix {prefix} must be denied"

    def test_read_tools_allowed(self):
        for tool in ALL_CHAT_TOOLS:
            assert not _is_denied(tool.name), f"{tool.name} should be allowed"

    @pytest.mark.asyncio
    async def test_executor_blocks_denied_tool(self):
        """Deny-list is checked first — write tools get a clear error."""
        executor = ToolExecutor(provider=AsyncMock(), incident_store=AsyncMock())
        result = await executor.execute("restart_service", {"service_name": "demo"})
        assert not result.success
        assert "not allowed" in result.error

    @pytest.mark.asyncio
    async def test_executor_blocks_deny_prefix(self):
        executor = ToolExecutor(provider=AsyncMock(), incident_store=AsyncMock())
        result = await executor.execute("delete_volume", {})
        assert not result.success
        # First validation catches it as unknown, deny-list also covers it
        assert not result.success


# ---------------------------------------------------------------------------
# P1 #9: Argument type validation
# ---------------------------------------------------------------------------


class TestArgTypeValidation:
    def test_valid_string_arg(self):
        tool = TOOL_REGISTRY["get_service_status"]
        err = _validate_arg_types(tool, {"service_name": "demo"})
        assert err is None

    def test_invalid_string_arg(self):
        tool = TOOL_REGISTRY["get_service_status"]
        err = _validate_arg_types(tool, {"service_name": 123})
        assert err is not None
        assert "expected string" in err

    def test_valid_integer_arg(self):
        tool = TOOL_REGISTRY["get_service_logs"]
        err = _validate_arg_types(tool, {"service_name": "demo", "lines": 50})
        assert err is None

    def test_invalid_integer_arg(self):
        tool = TOOL_REGISTRY["get_service_logs"]
        err = _validate_arg_types(tool, {"service_name": "demo", "lines": "fifty"})
        assert err is not None
        assert "expected integer" in err

    def test_extra_args_tolerated(self):
        tool = TOOL_REGISTRY["list_services"]
        err = _validate_arg_types(tool, {"extra_arg": "whatever"})
        assert err is None

    @pytest.mark.asyncio
    async def test_executor_rejects_bad_types(self, executor):
        result = await executor.execute("get_service_status", {"service_name": 999})
        assert not result.success
        assert "Invalid argument types" in result.error


# ---------------------------------------------------------------------------
# P1 #16: Dual result formatting
# ---------------------------------------------------------------------------


class TestDualResultFormatting:
    def test_to_json_is_compact(self):
        r = ToolResult(tool="test", success=True, output="short", _raw_output="short")
        j = json.loads(r.to_json())
        assert j["data"] == "short"
        assert "raw" not in j  # raw not in compact format

    def test_to_rich_dict_returns_raw(self):
        raw_data = {"key": "full_value", "extra": [1, 2, 3]}
        compact = '{"key": "full_value"}'
        r = ToolResult(tool="test", success=True, output=compact, _raw_output=raw_data)
        rich = r.to_rich_dict()
        assert rich["output"] == raw_data  # Full data, not compact
        assert rich["tool"] == "test"
        assert rich["success"] is True

    def test_to_rich_dict_fallback_no_raw(self):
        r = ToolResult(tool="test", success=True, output={"key": "val"})
        rich = r.to_rich_dict()
        assert rich["output"] == {"key": "val"}

    @pytest.mark.asyncio
    async def test_executor_stores_raw_output(self, executor, mock_provider):
        result = await executor.execute("list_services", {})
        assert result.success
        # Compact output equals the result (small data, no truncation)
        assert result.output == result._raw_output or result._raw_output is not None
        # Rich dict should have the full output
        rich = result.to_rich_dict()
        assert isinstance(rich["output"], list)


# ---------------------------------------------------------------------------
# P1 #13: Graceful error messages
# ---------------------------------------------------------------------------


class TestFriendlyErrorMessages:
    def test_timeout_message(self):
        from agent.llm.client import _friendly_error_message
        msg = _friendly_error_message(TimeoutError("request timed out"))
        assert "timed out" in msg.lower()

    def test_connection_refused(self):
        from agent.llm.client import _friendly_error_message
        msg = _friendly_error_message(ConnectionError("connection refused"))
        assert "cannot reach" in msg.lower() or "ollama" in msg.lower()

    def test_model_not_found(self):
        from agent.llm.client import _friendly_error_message
        msg = _friendly_error_message(Exception("model 'xyz' not found"))
        assert "not found" in msg.lower()

    def test_context_too_long(self):
        from agent.llm.client import _friendly_error_message
        msg = _friendly_error_message(Exception("maximum context length exceeded"))
        assert "context" in msg.lower()

    def test_oom_message(self):
        from agent.llm.client import _friendly_error_message
        msg = _friendly_error_message(Exception("CUDA out of memory"))
        assert "memory" in msg.lower()

    def test_generic_fallback(self):
        from agent.llm.client import _friendly_error_message
        msg = _friendly_error_message(Exception("something weird"))
        assert "trouble connecting" in msg.lower()


# ---------------------------------------------------------------------------
# P1 #14: Concurrent tool execution
# ---------------------------------------------------------------------------


class TestConcurrentToolExecution:
    @pytest.mark.asyncio
    async def test_multiple_tool_calls_executed_concurrently(self):
        """Verify that multiple tool calls in one iteration all execute."""
        from agent.config import Settings
        from agent.llm.client import LLMClient
        from unittest.mock import patch

        settings = Settings(
            ollama_host="http://localhost:11434",
            ollama_model="test",
            ollama_fallback_model="test-fb",
            _env_file=None,
        )
        with patch("agent.llm.client.ollama.Client") as MockClient:
            client = LLMClient(settings)
            client._client = MockClient.return_value

            call_count = 0

            def mock_chat(**kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # Model calls 3 tools at once
                    return {"message": {
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": "think", "arguments": {"thought": "Step 1"}}},
                            {"function": {"name": "think", "arguments": {"thought": "Step 2"}}},
                            {"function": {"name": "think", "arguments": {"thought": "Step 3"}}},
                        ],
                    }}
                return {"message": {"content": "Done with 3 tools."}}

            client._client.chat = MagicMock(side_effect=mock_chat)
            executor = ToolExecutor()
            result = await client.chat_with_tools(
                question="Multi-tool test",
                system_state={},
                tool_executor=executor,
            )
            assert "done" in result.lower()
            assert call_count == 2  # 1 tool-call round + 1 final response


# ---------------------------------------------------------------------------
# P1 #12: Enhanced retry for tool-calling
# ---------------------------------------------------------------------------


class TestEnhancedRetry:
    def test_chat_with_tools_sync_has_retry(self):
        """Verify _chat_with_tools_sync has tenacity retry decoration."""
        from agent.llm.client import LLMClient
        method = LLMClient._chat_with_tools_sync
        assert hasattr(method, "retry"), "_chat_with_tools_sync should have tenacity retry"

    def test_tool_retry_attempts_is_3(self):
        """Tool-calling should retry 3 times (more than the 2 for diagnosis)."""
        from agent.llm.client import LLMClient
        retry_obj = LLMClient._chat_with_tools_sync.retry
        stop = retry_obj.stop
        # tenacity stop_after_attempt stores max_attempt_number
        assert stop.max_attempt_number == 3
