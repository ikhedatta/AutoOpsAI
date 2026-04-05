"""Tests for agent.llm — LLM client, JSON parsing, prompts."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
import pytest_asyncio

from agent.config import Settings
from agent.llm.client import LLMClient
from agent.llm.prompts import (
    CHAT_SYSTEM_PROMPT,
    CHAT_SYSTEM_PROMPT_WITH_TOOLS,
    FEW_SHOT_DIAGNOSIS,
    SYSTEM_PROMPT,
    VALID_ACTIONS,
    _build_system_prompt,
    _capabilities_block,
    _identity_block,
    _output_discipline_block,
    _reasoning_block,
    _safety_block,
    _tool_instructions_block,
    chat_prompt,
    chat_prompt_with_tools,
    diagnosis_prompt,
    novel_issue_prompt,
    summary_prompt,
)
from agent.models import Diagnosis


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_settings():
    return Settings(
        ollama_host="http://localhost:11434",
        ollama_model="test-model",
        ollama_fallback_model="test-fallback",
        ollama_timeout=30,
        _env_file=None,
    )


@pytest.fixture
def llm_client(mock_settings):
    with patch("agent.llm.client.ollama.Client") as MockClient:
        client = LLMClient(mock_settings)
        client._client = MockClient.return_value
        return client


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


class TestParseJson:
    def test_direct_json(self, llm_client):
        raw = '{"summary": "test", "confidence": 0.9}'
        result = llm_client._parse_json(raw)
        assert result["summary"] == "test"
        assert result["confidence"] == 0.9

    def test_json_in_code_fence(self, llm_client):
        raw = 'Here is the analysis:\n```json\n{"summary": "test"}\n```'
        result = llm_client._parse_json(raw)
        assert result["summary"] == "test"

    def test_json_in_generic_code_fence(self, llm_client):
        raw = '```\n{"summary": "test"}\n```'
        result = llm_client._parse_json(raw)
        assert result["summary"] == "test"

    def test_json_embedded_in_text(self, llm_client):
        raw = 'The issue is: {"summary": "high cpu", "explanation": "cpu high"}'
        result = llm_client._parse_json(raw)
        assert result["summary"] == "high cpu"

    def test_invalid_json_returns_empty(self, llm_client):
        raw = "This is not JSON at all"
        result = llm_client._parse_json(raw)
        assert result == {}

    def test_nested_json(self, llm_client):
        raw = json.dumps({
            "summary": "test",
            "nested": {"key": "value"},
            "list": [1, 2, 3],
        })
        result = llm_client._parse_json(raw)
        assert result["nested"]["key"] == "value"
        assert result["list"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


class TestIsAvailable:
    @pytest.mark.asyncio
    async def test_available(self, llm_client):
        llm_client._client.list = MagicMock(return_value={"models": []})
        assert await llm_client.is_available() is True
        assert llm_client._available is True

    @pytest.mark.asyncio
    async def test_not_available(self, llm_client):
        llm_client._client.list = MagicMock(side_effect=ConnectionError("refused"))
        assert await llm_client.is_available() is False
        assert llm_client._available is False


# ---------------------------------------------------------------------------
# diagnose
# ---------------------------------------------------------------------------


class TestDiagnose:
    @pytest.mark.asyncio
    async def test_successful_diagnosis(self, llm_client):
        llm_response = {
            "summary": "High CPU detected",
            "explanation": "CPU usage is above threshold",
            "confidence": 0.85,
            "root_cause": "traffic spike",
            "recommended_actions": ["restart_service"],
        }
        llm_client._client.chat = MagicMock(
            return_value={"message": {"content": json.dumps(llm_response)}}
        )
        result = await llm_client.diagnose(
            anomaly={"service_name": "demo", "anomaly_type": "high_cpu"},
            metrics={"demo": {"cpu_percent": 95}},
        )
        assert isinstance(result, Diagnosis)
        assert result.summary == "High CPU detected"
        assert result.confidence == 0.85
        assert "restart_service" in result.recommended_actions

    @pytest.mark.asyncio
    async def test_diagnosis_with_playbook_context(self, llm_client):
        llm_client._client.chat = MagicMock(
            return_value={"message": {"content": '{"summary":"test","explanation":"ok","confidence":0.9}'}}
        )
        result = await llm_client.diagnose(
            anomaly={"service_name": "demo"},
            metrics={},
            playbook_context="Restart the service if CPU is high",
            logs=["error: connection refused"],
        )
        assert result.summary == "test"

    @pytest.mark.asyncio
    async def test_diagnosis_fallback_on_error(self, llm_client):
        llm_client._client.chat = MagicMock(side_effect=Exception("model not found"))
        result = await llm_client.diagnose(
            anomaly={"service_name": "demo", "anomaly_type": "high_cpu"},
            metrics={},
        )
        assert isinstance(result, Diagnosis)
        assert result.confidence == 0.3
        assert "unavailable" in result.explanation.lower() or "fallback" in result.explanation.lower()


# ---------------------------------------------------------------------------
# reason_novel_issue
# ---------------------------------------------------------------------------


class TestReasonNovelIssue:
    @pytest.mark.asyncio
    async def test_successful_novel(self, llm_client):
        llm_client._client.chat = MagicMock(
            return_value={"message": {"content": '{"summary":"Novel issue","explanation":"Unknown pattern","confidence":0.4}'}}
        )
        result = await llm_client.reason_novel_issue(metrics={"demo": {"cpu_percent": 50}})
        assert result.summary == "Novel issue"
        assert result.novel is True

    @pytest.mark.asyncio
    async def test_novel_fallback_on_error(self, llm_client):
        llm_client._client.chat = MagicMock(side_effect=Exception("timeout"))
        result = await llm_client.reason_novel_issue(metrics={})
        assert result.novel is True
        assert result.confidence == 0.1


# ---------------------------------------------------------------------------
# generate_summary
# ---------------------------------------------------------------------------


class TestGenerateSummary:
    @pytest.mark.asyncio
    async def test_successful_summary(self, llm_client):
        llm_client._client.chat = MagicMock(
            return_value={"message": {"content": "This is a summary of the incident."}}
        )
        result = await llm_client.generate_summary({"service_name": "demo", "title": "test"})
        assert "summary" in result.lower()

    @pytest.mark.asyncio
    async def test_summary_fallback_on_error(self, llm_client):
        llm_client._client.chat = MagicMock(side_effect=Exception("error"))
        result = await llm_client.generate_summary(
            {"service_name": "demo", "diagnosis_summary": "CPU high"},
        )
        assert "demo" in result


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------


class TestChat:
    @pytest.mark.asyncio
    async def test_successful_chat(self, llm_client):
        llm_client._client.chat = MagicMock(
            return_value={"message": {"content": "All services are running fine."}}
        )
        result = await llm_client.chat(
            question="How is the system?",
            system_state={"demo": {"state": "running"}},
        )
        assert "running" in result.lower()

    @pytest.mark.asyncio
    async def test_chat_with_incident_context(self, llm_client):
        llm_client._client.chat = MagicMock(
            return_value={"message": {"content": "The incident is being resolved."}}
        )
        result = await llm_client.chat(
            question="What's happening?",
            system_state={},
            incident_context={"incident_id": "inc_123", "title": "test"},
        )
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_chat_fallback_on_error(self, llm_client):
        llm_client._client.chat = MagicMock(side_effect=Exception("error"))
        result = await llm_client.chat(
            question="How are things?",
            system_state={},
        )
        assert "trouble" in result.lower()

    @pytest.mark.asyncio
    async def test_chat_passes_history_to_prompt(self, llm_client):
        """Verify chat() includes history messages in the Ollama call."""
        captured = {}

        def capture_chat(**kwargs):
            captured["messages"] = kwargs["messages"]
            return {"message": {"content": "I will investigate redis."}}

        llm_client._client.chat = MagicMock(side_effect=capture_chat)
        history = [
            {"role": "user", "content": "What is wrong with redis?"},
            {"role": "assistant", "content": "Redis CPU is at 95%. Shall I investigate?"},
        ]
        result = await llm_client.chat(
            question="yes",
            system_state={},
            history=history,
        )
        assert result == "I will investigate redis."
        msgs = captured["messages"]
        # system + 2 history + current user = 4
        assert len(msgs) == 4
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "What is wrong with redis?"
        assert msgs[2]["role"] == "assistant"
        assert "95%" in msgs[2]["content"]
        assert msgs[3]["role"] == "user"
        assert "yes" in msgs[3]["content"]


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------


class TestPrompts:
    def test_system_prompt_identity(self):
        assert "AutoOps AI" in SYSTEM_PROMPT
        assert "virtual DevOps engineer" in SYSTEM_PROMPT

    def test_system_prompt_has_reasoning_framework(self):
        assert "Observe" in SYSTEM_PROMPT
        assert "Hypothesise" in SYSTEM_PROMPT
        assert "Act" in SYSTEM_PROMPT

    def test_system_prompt_has_capabilities(self):
        assert "restart_service" in SYSTEM_PROMPT
        assert "scale_service" in SYSTEM_PROMPT
        assert "escalate" in SYSTEM_PROMPT

    def test_system_prompt_has_safety(self):
        assert "Never fabricate" in SYSTEM_PROMPT
        assert "Confidence Calibration" in SYSTEM_PROMPT

    def test_composable_blocks_are_independent(self):
        identity = _identity_block()
        reasoning = _reasoning_block()
        capabilities = _capabilities_block()
        safety = _safety_block()
        assert "AutoOps AI" in identity
        assert "Observe" in reasoning
        assert "restart_service" in capabilities
        assert "0.0" in safety and "0.9" in safety

    def test_build_system_prompt_joins_blocks(self):
        result = _build_system_prompt("block1", "block2", "block3")
        assert "block1\n\nblock2\n\nblock3" == result

    def test_chat_system_prompt_no_json(self):
        assert "NOT JSON" in CHAT_SYSTEM_PROMPT
        assert "Respond ONLY with valid JSON" not in CHAT_SYSTEM_PROMPT

    def test_chat_system_prompt_with_tools_has_instructions(self):
        assert "Tool Usage Rules" in CHAT_SYSTEM_PROMPT_WITH_TOOLS
        assert "get_service_status" in CHAT_SYSTEM_PROMPT_WITH_TOOLS
        assert "think" in CHAT_SYSTEM_PROMPT_WITH_TOOLS

    def test_valid_actions_list(self):
        assert "restart_service" in VALID_ACTIONS
        assert "escalate" in VALID_ACTIONS
        assert len(VALID_ACTIONS) >= 7

    def test_few_shot_diagnosis(self):
        assert "summary" in FEW_SHOT_DIAGNOSIS
        assert "confidence" in FEW_SHOT_DIAGNOSIS
        assert "recommended_actions" in FEW_SHOT_DIAGNOSIS

    def test_diagnosis_prompt_structure(self):
        msgs = diagnosis_prompt(
            anomaly={"service_name": "demo", "anomaly_type": "high_cpu", "metric": "cpu_percent",
                      "current_value": 95, "threshold": 90, "evidence": "CPU at 95%"},
            metrics={"demo": {"cpu_percent": 95, "memory_percent": 50}},
        )
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert "demo" in msgs[1]["content"]
        assert "high_cpu" in msgs[1]["content"]

    def test_diagnosis_prompt_has_reasoning_steps(self):
        msgs = diagnosis_prompt(
            anomaly={"service_name": "demo", "anomaly_type": "high_cpu"},
            metrics={"demo": {"cpu_percent": 95}},
        )
        content = msgs[1]["content"]
        assert "Reasoning Steps" in content
        assert "blast radius" in content.lower()

    def test_diagnosis_prompt_constrains_actions(self):
        msgs = diagnosis_prompt(
            anomaly={"service_name": "demo"},
            metrics={},
        )
        content = msgs[1]["content"]
        assert "ONLY from:" in content
        assert "restart_service" in content
        assert "escalate" in content

    def test_diagnosis_prompt_has_few_shot(self):
        msgs = diagnosis_prompt(
            anomaly={"service_name": "demo"},
            metrics={},
        )
        content = msgs[1]["content"]
        assert "Example output" in content

    def test_diagnosis_prompt_with_playbook(self):
        msgs = diagnosis_prompt(
            anomaly={"service_name": "demo"},
            metrics={},
            playbook_context="Check memory allocation",
        )
        content = msgs[1]["content"]
        assert "Check memory allocation" in content
        assert "validate against the metrics" in content.lower() or "primary reference" in content.lower()

    def test_diagnosis_prompt_with_logs(self):
        msgs = diagnosis_prompt(
            anomaly={"service_name": "demo"},
            metrics={},
            logs=["error: connection refused", "info: retrying"],
        )
        content = msgs[1]["content"]
        assert "connection refused" in content

    def test_novel_issue_prompt_structure(self):
        msgs = novel_issue_prompt(
            metrics={"demo": {"cpu_percent": 50, "memory_percent": 30, "state": "running"}},
        )
        assert len(msgs) == 2
        assert "No Playbook Match" in msgs[1]["content"]

    def test_novel_issue_prompt_has_checklist(self):
        msgs = novel_issue_prompt(metrics={"demo": {"cpu_percent": 50}})
        content = msgs[1]["content"]
        assert "Diagnostic Checklist" in content
        assert "confidence" in content.lower() and "0.5" in content

    def test_novel_issue_prompt_constrains_actions(self):
        msgs = novel_issue_prompt(metrics={})
        content = msgs[1]["content"]
        assert "ONLY from:" in content

    def test_summary_prompt_structure(self):
        msgs = summary_prompt({"title": "CPU Alert", "service_name": "demo", "severity": "HIGH"})
        assert len(msgs) == 2
        assert "CPU Alert" in msgs[1]["content"]

    def test_chat_prompt_structure(self):
        msgs = chat_prompt(
            question="What services are down?",
            system_state={"demo": {"state": "running", "cpu_percent": 30, "memory_percent": 50}},
        )
        assert len(msgs) == 2  # system + user (no history)
        assert "What services are down?" in msgs[-1]["content"]

    def test_chat_prompt_with_incident(self):
        msgs = chat_prompt(
            question="Tell me about this incident",
            system_state={},
            incident_context={"incident_id": "inc_123", "title": "High CPU"},
        )
        content = msgs[1]["content"]
        assert "inc_123" in content
        assert "High CPU" in content

    def test_chat_prompt_with_tools_structure(self):
        msgs = chat_prompt_with_tools(
            question="What is the status of redis?",
            system_state={"redis": {"state": "running", "cpu_percent": 10, "memory_percent": 30}},
        )
        assert len(msgs) == 2  # system + user (no history)
        assert "Tool Usage Rules" in msgs[0]["content"]
        assert "redis" in msgs[-1]["content"]

    def test_chat_prompt_with_tools_has_incident(self):
        msgs = chat_prompt_with_tools(
            question="Tell me more",
            system_state={},
            incident_context={"incident_id": "inc_1", "title": "test"},
        )
        assert "inc_1" in msgs[-1]["content"]

    # -- Conversation history context ----------------------------------------

    def test_chat_prompt_with_history(self):
        history = [
            {"role": "user", "content": "What is wrong with redis?"},
            {"role": "assistant", "content": "Redis CPU is at 95%. Shall I investigate?"},
        ]
        msgs = chat_prompt(
            question="yes",
            system_state={"redis": {"state": "running", "cpu_percent": 95, "memory_percent": 30}},
            history=history,
        )
        # system + 2 history + current user = 4
        assert len(msgs) == 4
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "What is wrong with redis?"
        assert msgs[2]["role"] == "assistant"
        assert "95%" in msgs[2]["content"]
        assert msgs[3]["role"] == "user"
        assert "yes" in msgs[3]["content"]

    def test_chat_prompt_with_tools_with_history(self):
        history = [
            {"role": "user", "content": "Check demo-api health"},
            {"role": "assistant", "content": "demo-api is healthy."},
        ]
        msgs = chat_prompt_with_tools(
            question="and demo-redis?",
            system_state={},
            history=history,
        )
        assert len(msgs) == 4
        assert msgs[0]["role"] == "system"
        assert "Tool Usage Rules" in msgs[0]["content"]
        assert msgs[1]["content"] == "Check demo-api health"
        assert msgs[3]["role"] == "user"
        assert "demo-redis" in msgs[3]["content"]

    def test_chat_prompt_no_history_is_default(self):
        """Without history param, prompt is system+user only."""
        msgs = chat_prompt("hello", {})
        assert len(msgs) == 2

    def test_chat_prompt_empty_history(self):
        """Empty list is same as no history."""
        msgs = chat_prompt("hello", {}, history=[])
        assert len(msgs) == 2
