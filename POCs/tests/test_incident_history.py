"""Tests for the incident history POC."""

from datetime import datetime

from POCs.incident_history_poc.incident_history import (
    IncidentHistory,
    IncidentContext,
    IncidentStatus,
    ResolvedIncident,
    SimilarIncidentMatcher,
)


def _make_incident(
    incident_id: str = "INC-001",
    symptom: str = "High CPU usage on webapp",
    container: str = "webapp",
    playbook_id: str = "high_cpu_container",
    status: IncidentStatus = IncidentStatus.RESOLVED,
) -> ResolvedIncident:
    return ResolvedIncident(
        incident_id=incident_id,
        context=IncidentContext(
            incident_id=incident_id,
            detected_at=datetime.now(),
            symptom=symptom,
            container=container,
        ),
        playbook_id=playbook_id,
        playbook_name="High CPU Container",
        remediation_steps=["collect_diagnostics", "docker_restart"],
        status=status,
        resolved_at=datetime.now(),
        resolution_time_seconds=45.0,
    )


class TestIncidentHistory:
    """Test incident history storage and search."""

    def setup_method(self):
        self.history = IncidentHistory(use_db=False)

    def test_add_and_retrieve(self):
        inc = _make_incident()
        self.history.add(inc)
        assert len(self.history.incidents) == 1

    def test_newest_first(self):
        self.history.add(_make_incident(incident_id="INC-001"))
        self.history.add(_make_incident(incident_id="INC-002"))
        assert self.history.incidents[0].incident_id == "INC-002"

    def test_max_history_trimmed(self):
        self.history.MAX_HISTORY_ITEMS = 5
        for i in range(10):
            self.history.add(_make_incident(incident_id=f"INC-{i:03d}"))
        assert len(self.history.incidents) == 5

    def test_find_similar_by_symptom(self):
        self.history.add(_make_incident(symptom="High CPU usage on webapp"))
        self.history.add(_make_incident(incident_id="INC-002", symptom="Redis connection refused"))
        results = self.history.find_similar("High CPU")
        assert len(results) == 1
        assert results[0].incident_id == "INC-001"

    def test_find_similar_with_container_filter(self):
        self.history.add(_make_incident(container="webapp"))
        self.history.add(_make_incident(incident_id="INC-002", container="redis",
                                        symptom="High CPU usage on redis"))
        results = self.history.find_similar("High CPU", container="redis")
        assert len(results) == 1
        assert results[0].context.container == "redis"

    def test_find_by_playbook(self):
        self.history.add(_make_incident(playbook_id="high_cpu_container"))
        self.history.add(_make_incident(incident_id="INC-002", playbook_id="redis_memory_full"))
        results = self.history.find_by_playbook("high_cpu_container")
        assert len(results) == 1

    def test_playbook_stats(self):
        self.history.add(_make_incident(playbook_id="pb1", status=IncidentStatus.RESOLVED))
        self.history.add(_make_incident(incident_id="INC-002", playbook_id="pb1",
                                        status=IncidentStatus.RESOLVED))
        self.history.add(_make_incident(incident_id="INC-003", playbook_id="pb1",
                                        status=IncidentStatus.FAILED))
        stats = self.history.get_playbook_stats("pb1")
        assert stats["usage_count"] == 3
        assert stats["success_count"] == 2
        assert stats["success_rate"] == pytest.approx(2 / 3)

    def test_playbook_stats_empty(self):
        stats = self.history.get_playbook_stats("nonexistent")
        assert stats["usage_count"] == 0

    def test_clear(self):
        self.history.add(_make_incident())
        self.history.clear()
        assert len(self.history.incidents) == 0

    def test_export(self, tmp_path):
        self.history.add(_make_incident())
        export_file = str(tmp_path / "export.json")
        self.history.export(export_file)
        import json
        with open(export_file) as f:
            data = json.load(f)
        assert data["total_incidents"] == 1


class TestSimilarIncidentMatcher:
    def test_match_and_suggest(self):
        history = IncidentHistory(use_db=False)
        history.add(_make_incident(symptom="High CPU usage on webapp", container="webapp"))
        result = SimilarIncidentMatcher.match_and_suggest_playbook(
            "High CPU", history, container="webapp"
        )
        assert result is not None
        incident, confidence = result
        assert confidence >= 0.8
        assert incident.playbook_id == "high_cpu_container"

    def test_no_match_returns_none(self):
        history = IncidentHistory(use_db=False)
        result = SimilarIncidentMatcher.match_and_suggest_playbook("Unknown error", history)
        assert result is None


import pytest
