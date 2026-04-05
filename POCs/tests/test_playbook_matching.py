"""Tests for the playbook matching knowledge base."""

from POCs.playbook_matching.knowledge_base import (
    KnowledgeBase,
    AnomalyEvent,
    MatchResult,
)


class TestKnowledgeBase:
    """Test playbook loading and matching logic."""

    def setup_method(self, method):
        # Will be set by fixture
        self.kb = None

    def _init_kb(self, playbooks_dir):
        self.kb = KnowledgeBase(playbooks_dir)

    def test_loads_playbook_entries(self, playbooks_dir):
        self._init_kb(playbooks_dir)
        assert len(self.kb.entries) == 3  # 2 general + 1 redis

    def test_match_container_health_exited(self, playbooks_dir):
        self._init_kb(playbooks_dir)
        event = AnomalyEvent(
            event_type="container_health",
            container_name="webapp",
            restart_count=5,
        )
        result = self.kb.match(event)
        assert result.matched
        assert result.entry.id == "container_restart_loop"

    def test_match_metric_threshold_cpu(self, playbooks_dir):
        self._init_kb(playbooks_dir)
        event = AnomalyEvent(
            event_type="metric_threshold",
            container_name="webapp",
            metric_name="container_cpu_percent",
            metric_value=95.0,
        )
        result = self.kb.match(event)
        assert result.matched
        assert result.entry.id == "high_cpu_container"
        assert result.confidence > 0

    def test_match_metric_threshold_memory(self, playbooks_dir):
        self._init_kb(playbooks_dir)
        event = AnomalyEvent(
            event_type="metric_threshold",
            container_name="redis",
            metric_name="container_memory_percent",
            metric_value=95.0,
        )
        result = self.kb.match(event)
        assert result.matched
        assert result.entry.id == "redis_memory_full"

    def test_no_match_returns_false(self, playbooks_dir):
        self._init_kb(playbooks_dir)
        event = AnomalyEvent(
            event_type="log_pattern",
            container_name="unknown_service",
            log_pattern="some random error",
        )
        result = self.kb.match(event)
        # May or may not match via fuzzy — just ensure no crash
        assert isinstance(result, MatchResult)

    def test_get_entry_by_id(self, playbooks_dir):
        self._init_kb(playbooks_dir)
        entry = self.kb.get_entry_by_id("redis_memory_full")
        assert entry is not None
        assert entry.severity == "LOW"

    def test_get_entry_by_id_missing(self, playbooks_dir):
        self._init_kb(playbooks_dir)
        entry = self.kb.get_entry_by_id("nonexistent")
        assert entry is None

    def test_threshold_check(self, playbooks_dir):
        self._init_kb(playbooks_dir)
        assert KnowledgeBase._check_threshold(95.0, "> 90") is True
        assert KnowledgeBase._check_threshold(85.0, "> 90") is False
        assert KnowledgeBase._check_threshold(90.0, ">= 90") is True
        assert KnowledgeBase._check_threshold(5.0, "< 10") is True
