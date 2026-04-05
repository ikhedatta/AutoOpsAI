"""Tests for agent.knowledge — knowledge base loading, matching, parsing."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agent.knowledge.knowledge_base import KnowledgeBase
from agent.knowledge.schemas import (
    Detection,
    DetectionCondition,
    Playbook,
    PlaybookMatch,
    Remediation,
    RemediationStep,
    Rollback,
)
from agent.models import (
    HealthCheckResult,
    MetricSnapshot,
    Severity,
    ServiceState,
    ServiceStatus,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PLAYBOOK_YAML = """\
id: test_high_cpu
name: Test High CPU
severity: MEDIUM
detection:
  type: threshold
  conditions:
    - type: metric_threshold
      metric: cpu_percent
      threshold: "> 90"
diagnosis: "CPU is above threshold. Check for runaway processes."
remediation:
  steps:
    - action: restart_service
      target: demo-app
      timeout: 30
rollback:
  description: Restart did not help
  steps:
    - action: collect_logs
      target: demo-app
      lines: 100
tags:
  - cpu
  - performance
"""

CONTAINER_HEALTH_PLAYBOOK = """\
id: test_service_down
name: Test Service Down
severity: HIGH
detection:
  type: container_health
  conditions:
    - type: container_health
      service_name: demo-app
      state: stopped
diagnosis: "Container stopped unexpectedly."
remediation:
  steps:
    - action: restart_service
      target: demo-app
tags:
  - down
"""


@pytest.fixture
def playbooks_dir(tmp_path):
    """Create a temporary directory with sample playbooks."""
    (tmp_path / "general").mkdir()
    (tmp_path / "general" / "high_cpu.yaml").write_text(SAMPLE_PLAYBOOK_YAML)
    (tmp_path / "general" / "service_down.yaml").write_text(CONTAINER_HEALTH_PLAYBOOK)
    return tmp_path


@pytest.fixture
def empty_dir(tmp_path):
    return tmp_path / "empty"


@pytest.fixture
def kb(playbooks_dir):
    return KnowledgeBase(playbooks_dir)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


class TestKnowledgeBaseLoading:
    def test_loads_playbooks(self, kb):
        assert len(kb.playbooks) == 2

    def test_playbook_ids(self, kb):
        ids = {pb.id for pb in kb.playbooks}
        assert "test_high_cpu" in ids
        assert "test_service_down" in ids

    def test_get_by_id(self, kb):
        pb = kb.get("test_high_cpu")
        assert pb is not None
        assert pb.name == "Test High CPU"
        assert pb.severity == Severity.MEDIUM

    def test_get_nonexistent(self, kb):
        assert kb.get("nonexistent") is None

    def test_empty_directory(self, empty_dir):
        kb = KnowledgeBase(empty_dir)
        assert len(kb.playbooks) == 0

    def test_nonexistent_directory(self, tmp_path):
        kb = KnowledgeBase(tmp_path / "does_not_exist")
        assert len(kb.playbooks) == 0

    def test_reload(self, playbooks_dir, kb):
        assert len(kb.playbooks) == 2
        # Add another playbook
        (playbooks_dir / "extra.yaml").write_text("""\
id: extra
name: Extra
severity: LOW
detection:
  type: threshold
  conditions: []
diagnosis: ""
remediation:
  steps: []
""")
        count = kb.reload()
        assert count == 3
        assert kb.get("extra") is not None

    def test_invalid_yaml_skipped(self, tmp_path):
        (tmp_path / "bad.yaml").write_text("{{invalid yaml")
        (tmp_path / "good.yaml").write_text(SAMPLE_PLAYBOOK_YAML)
        kb = KnowledgeBase(tmp_path)
        assert len(kb.playbooks) == 1

    def test_yaml_without_id_skipped(self, tmp_path):
        (tmp_path / "no_id.yaml").write_text("name: Missing ID\nseverity: LOW\n")
        (tmp_path / "good.yaml").write_text(SAMPLE_PLAYBOOK_YAML)
        kb = KnowledgeBase(tmp_path)
        assert len(kb.playbooks) == 1


class TestPlaybookParsing:
    def test_detection_parsed(self, kb):
        pb = kb.get("test_high_cpu")
        assert pb.detection.type == "threshold"
        assert len(pb.detection.conditions) == 1
        cond = pb.detection.conditions[0]
        assert cond.type == "metric_threshold"
        assert cond.metric == "cpu_percent"
        assert cond.threshold == "> 90"

    def test_remediation_parsed(self, kb):
        pb = kb.get("test_high_cpu")
        assert len(pb.remediation.steps) == 1
        step = pb.remediation.steps[0]
        assert step.action == "restart_service"
        assert step.target == "demo-app"
        assert step.timeout == 30

    def test_rollback_parsed(self, kb):
        pb = kb.get("test_high_cpu")
        assert pb.rollback is not None
        assert "did not help" in pb.rollback.description
        assert len(pb.rollback.steps) == 1

    def test_tags_parsed(self, kb):
        pb = kb.get("test_high_cpu")
        assert "cpu" in pb.tags
        assert "performance" in pb.tags

    def test_no_rollback(self, kb):
        pb = kb.get("test_service_down")
        assert pb.rollback is None


# ---------------------------------------------------------------------------
# Threshold parsing
# ---------------------------------------------------------------------------


class TestThresholdParsing:
    def test_gt_threshold(self):
        op, val = KnowledgeBase._parse_threshold("> 90")
        assert op == ">"
        assert val == 90.0

    def test_gte_threshold(self):
        op, val = KnowledgeBase._parse_threshold(">= 85.5")
        assert op == ">="
        assert val == 85.5

    def test_lt_threshold(self):
        op, val = KnowledgeBase._parse_threshold("< 10")
        assert op == "<"
        assert val == 10.0

    def test_eq_threshold(self):
        op, val = KnowledgeBase._parse_threshold("== 100")
        assert op == "=="
        assert val == 100.0

    def test_bare_number(self):
        op, val = KnowledgeBase._parse_threshold("50")
        assert op == ">"
        assert val == 50.0

    def test_invalid_threshold(self):
        op, val = KnowledgeBase._parse_threshold("bad")
        assert op == ""
        assert val == 0.0


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


class TestMatchingMetricThreshold:
    def test_matches_high_cpu(self, kb):
        metrics = {
            "demo-app": MetricSnapshot(
                service_name="demo-app", cpu_percent=95.0,
                memory_used_bytes=100, memory_percent=10.0,
            ),
        }
        statuses = {
            "demo-app": ServiceStatus(
                name="demo-app", state=ServiceState.RUNNING, restart_count=0,
            ),
        }
        matches = kb.match(metrics, statuses)
        assert len(matches) >= 1
        assert matches[0].playbook.id == "test_high_cpu"
        assert matches[0].confidence > 0

    def test_no_match_for_low_cpu(self, kb):
        metrics = {
            "demo-app": MetricSnapshot(
                service_name="demo-app", cpu_percent=30.0,
                memory_used_bytes=100, memory_percent=10.0,
            ),
        }
        statuses = {
            "demo-app": ServiceStatus(
                name="demo-app", state=ServiceState.RUNNING, restart_count=0,
            ),
        }
        matches = kb.match(metrics, statuses)
        # The container_health playbook might partially match, but not the CPU one
        cpu_matches = [m for m in matches if m.playbook.id == "test_high_cpu"]
        assert len(cpu_matches) == 0


class TestMatchingContainerHealth:
    def test_matches_stopped_service(self, kb):
        metrics = {}
        statuses = {
            "demo-app": ServiceStatus(
                name="demo-app", state=ServiceState.STOPPED, restart_count=0,
            ),
        }
        matches = kb.match(metrics, statuses)
        down_matches = [m for m in matches if m.playbook.id == "test_service_down"]
        assert len(down_matches) == 1
        assert down_matches[0].confidence == 1.0

    def test_no_match_for_running_service(self, kb):
        metrics = {}
        statuses = {
            "demo-app": ServiceStatus(
                name="demo-app", state=ServiceState.RUNNING, restart_count=0,
            ),
        }
        matches = kb.match(metrics, statuses)
        down_matches = [m for m in matches if m.playbook.id == "test_service_down"]
        assert len(down_matches) == 0


class TestMatchingProviderScoping:
    def test_provider_scoped_playbook(self, tmp_path):
        (tmp_path / "scoped.yaml").write_text("""\
id: docker_only
name: Docker Only
severity: LOW
provider: docker_compose
detection:
  type: container_health
  conditions:
    - type: container_health
      service_name: demo-app
      state: stopped
diagnosis: ""
remediation:
  steps: []
""")
        kb = KnowledgeBase(tmp_path)
        statuses = {
            "demo-app": ServiceStatus(
                name="demo-app", state=ServiceState.STOPPED, restart_count=0,
            ),
        }
        # Match with correct provider
        matches = kb.match({}, statuses, provider_name="docker_compose")
        assert len(matches) == 1

        # Match with wrong provider
        matches = kb.match({}, statuses, provider_name="kubernetes")
        assert len(matches) == 0

        # Match with no provider filter
        matches = kb.match({}, statuses, provider_name=None)
        assert len(matches) == 1


class TestMatchSorting:
    def test_higher_confidence_first(self, tmp_path):
        # Two playbooks, one with 2 conditions (partial match), one with 1 (full match)
        (tmp_path / "one.yaml").write_text("""\
id: one_cond
name: One Condition
severity: LOW
detection:
  type: threshold
  conditions:
    - type: container_health
      service_name: demo-app
      state: stopped
diagnosis: ""
remediation:
  steps: []
""")
        (tmp_path / "two.yaml").write_text("""\
id: two_cond
name: Two Conditions
severity: MEDIUM
detection:
  type: compound
  conditions:
    - type: container_health
      service_name: demo-app
      state: stopped
    - type: metric_threshold
      metric: cpu_percent
      threshold: "> 90"
diagnosis: ""
remediation:
  steps: []
""")
        kb = KnowledgeBase(tmp_path)
        statuses = {
            "demo-app": ServiceStatus(
                name="demo-app", state=ServiceState.STOPPED, restart_count=0,
            ),
        }
        metrics = {
            "demo-app": MetricSnapshot(
                service_name="demo-app", cpu_percent=30.0,
                memory_used_bytes=100, memory_percent=10.0,
            ),
        }
        matches = kb.match(metrics, statuses)
        # one_cond should have higher confidence (1.0) vs two_cond (0.5)
        assert matches[0].playbook.id == "one_cond"


# ---------------------------------------------------------------------------
# Schema models
# ---------------------------------------------------------------------------


class TestSchemaModels:
    def test_playbook_defaults(self):
        pb = Playbook(
            id="test", name="Test", severity=Severity.LOW,
            detection=Detection(type="threshold"),
            diagnosis="", remediation=Remediation(steps=[]),
        )
        assert pb.provider is None
        assert pb.tags == []
        assert pb.cooldown_seconds == 300
        assert pb.rollback is None

    def test_remediation_step(self):
        step = RemediationStep(action="restart_service", target="demo", timeout=30)
        assert step.action == "restart_service"
        assert step.command is None

    def test_playbook_match(self):
        pb = Playbook(
            id="test", name="Test", severity=Severity.LOW,
            detection=Detection(type="threshold"),
            diagnosis="", remediation=Remediation(steps=[]),
        )
        match = PlaybookMatch(playbook=pb, confidence=0.85, matched_conditions=["cpu > 90"])
        assert match.confidence == 0.85
        assert len(match.matched_conditions) == 1
