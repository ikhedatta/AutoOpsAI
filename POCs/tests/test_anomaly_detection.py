"""Tests for the anomaly detector."""

from POCs.anomaly_detection.collector import ContainerSnapshot, SystemSnapshot
from POCs.anomaly_detection.detector import AnomalyDetector, ThresholdConfig
from POCs.playbook_matching.knowledge_base import AnomalyEvent

import time


def _make_snapshot(containers: list[ContainerSnapshot]) -> SystemSnapshot:
    return SystemSnapshot(containers=containers, collected_at=time.time())


def _make_container(
    name: str = "webapp",
    status: str = "running",
    health: str = "healthy",
    cpu_percent: float = 10.0,
    memory_percent: float = 30.0,
    restart_count: int = 0,
) -> ContainerSnapshot:
    return ContainerSnapshot(
        name=name,
        container_id="abc123",
        status=status,
        health=health,
        cpu_percent=cpu_percent,
        memory_usage_mb=512,
        memory_limit_mb=2048,
        memory_percent=memory_percent,
        restart_count=restart_count,
        uptime_seconds=3600,
        image="test:latest",
    )


class TestAnomalyDetector:
    """Test anomaly detection logic."""

    def setup_method(self):
        self.detector = AnomalyDetector(config=ThresholdConfig(
            cpu_percent=80, cpu_duration_seconds=0,  # Immediate for testing
            memory_percent=85, memory_duration_seconds=0,
            max_restart_count=3,
        ))

    def test_healthy_container_no_events(self):
        snapshot = _make_snapshot([_make_container()])
        events = self.detector.analyze(snapshot)
        assert events == []

    def test_exited_container_detected(self):
        snapshot = _make_snapshot([_make_container(status="exited")])
        events = self.detector.analyze(snapshot)
        assert len(events) >= 1
        assert any(e.event_type == "container_health" for e in events)

    def test_dead_container_detected(self):
        snapshot = _make_snapshot([_make_container(status="dead")])
        events = self.detector.analyze(snapshot)
        assert len(events) >= 1

    def test_restarting_container_detected(self):
        snapshot = _make_snapshot([_make_container(status="restarting")])
        events = self.detector.analyze(snapshot)
        assert len(events) >= 1

    def test_restart_loop_detected(self):
        snapshot = _make_snapshot([_make_container(restart_count=5)])
        events = self.detector.analyze(snapshot)
        assert any(e.restart_count == 5 for e in events)

    def test_unhealthy_detected(self):
        snapshot = _make_snapshot([_make_container(health="unhealthy")])
        events = self.detector.analyze(snapshot)
        assert any(e.status == "unhealthy" for e in events)

    def test_high_cpu_detected(self):
        snapshot = _make_snapshot([_make_container(cpu_percent=95.0)])
        events = self.detector.analyze(snapshot)
        assert any(e.metric_name == "container_cpu_percent" for e in events)

    def test_high_memory_detected(self):
        snapshot = _make_snapshot([_make_container(memory_percent=90.0)])
        events = self.detector.analyze(snapshot)
        assert any(e.metric_name == "container_memory_percent" for e in events)

    def test_normal_cpu_no_event(self):
        snapshot = _make_snapshot([_make_container(cpu_percent=50.0)])
        events = self.detector.analyze(snapshot)
        assert not any(e.metric_name == "container_cpu_percent" for e in events)

    def test_callback_fired(self):
        received = []
        self.detector.on_anomaly(lambda event, cs: received.append(event))
        snapshot = _make_snapshot([_make_container(status="exited")])
        self.detector.analyze(snapshot)
        assert len(received) >= 1

    def test_stale_state_cleanup(self):
        from POCs.anomaly_detection.detector import _ConditionState
        self.detector._states[("old_container", "high_cpu")] = _ConditionState(
            first_seen=0, last_seen=0, consecutive_count=1
        )
        snapshot = _make_snapshot([_make_container()])
        self.detector.analyze(snapshot)
        assert ("old_container", "high_cpu") not in self.detector._states

    def test_multiple_containers(self):
        snapshot = _make_snapshot([
            _make_container(name="web1", status="running"),
            _make_container(name="web2", status="exited"),
            _make_container(name="redis", cpu_percent=95.0),
        ])
        events = self.detector.analyze(snapshot)
        containers_with_events = {e.container_name for e in events}
        assert "web2" in containers_with_events
        assert "redis" in containers_with_events
        assert "web1" not in containers_with_events
