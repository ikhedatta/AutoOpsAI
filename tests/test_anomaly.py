"""Tests for agent.engine.anomaly — anomaly detection rules."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from agent.engine.anomaly import AnomalyDetector, DEFAULT_THRESHOLDS
from agent.models import (
    MetricSnapshot,
    ServiceState,
    ServiceStatus,
    Severity,
)


class TestAnomalyDetectorInit:
    def test_default_thresholds(self):
        d = AnomalyDetector()
        assert d.thresholds == DEFAULT_THRESHOLDS
        assert d.thresholds["cpu_critical"] == 90.0
        assert d.thresholds["memory_critical"] == 85.0

    def test_custom_thresholds(self):
        d = AnomalyDetector(thresholds={"cpu_critical": 80.0})
        assert d.thresholds["cpu_critical"] == 80.0
        # Other defaults still present
        assert d.thresholds["memory_critical"] == 85.0

    def test_empty_thresholds_uses_defaults(self):
        d = AnomalyDetector(thresholds={})
        assert d.thresholds == DEFAULT_THRESHOLDS


class TestHighCpuDetection:
    def test_detects_high_cpu(self, high_cpu_metrics, running_status):
        d = AnomalyDetector()
        anomalies = d.detect(high_cpu_metrics, running_status)
        cpu_anomalies = [a for a in anomalies if a.anomaly_type == "high_cpu"]
        assert len(cpu_anomalies) == 1
        assert cpu_anomalies[0].service_name == "demo-app"
        assert cpu_anomalies[0].current_value == 95.0
        assert cpu_anomalies[0].threshold == 90.0

    def test_no_anomaly_below_threshold(self, normal_metrics, running_status):
        d = AnomalyDetector()
        anomalies = d.detect(normal_metrics, running_status)
        assert len(anomalies) == 0

    def test_exact_threshold_triggers(self, running_status):
        metrics = {
            "demo-app": MetricSnapshot(
                service_name="demo-app", cpu_percent=90.0,
                memory_used_bytes=100, memory_percent=10.0,
            ),
        }
        d = AnomalyDetector()
        anomalies = d.detect(metrics, running_status)
        cpu = [a for a in anomalies if a.anomaly_type == "high_cpu"]
        assert len(cpu) == 1

    def test_custom_cpu_threshold(self, running_status):
        metrics = {
            "demo-app": MetricSnapshot(
                service_name="demo-app", cpu_percent=82.0,
                memory_used_bytes=100, memory_percent=10.0,
            ),
        }
        d = AnomalyDetector(thresholds={"cpu_critical": 80.0})
        anomalies = d.detect(metrics, running_status)
        cpu = [a for a in anomalies if a.anomaly_type == "high_cpu"]
        assert len(cpu) == 1


class TestHighMemoryDetection:
    def test_detects_high_memory(self, high_memory_metrics, running_status):
        d = AnomalyDetector()
        anomalies = d.detect(high_memory_metrics, running_status)
        mem_anomalies = [a for a in anomalies if a.anomaly_type == "high_memory"]
        assert len(mem_anomalies) == 1
        assert mem_anomalies[0].current_value == 90.0

    def test_no_anomaly_below_memory_threshold(self, normal_metrics, running_status):
        d = AnomalyDetector()
        anomalies = d.detect(normal_metrics, running_status)
        mem = [a for a in anomalies if a.anomaly_type == "high_memory"]
        assert len(mem) == 0


class TestServiceDownDetection:
    def test_detects_stopped_service(self, stopped_status, normal_metrics):
        d = AnomalyDetector()
        anomalies = d.detect(normal_metrics, stopped_status)
        down = [a for a in anomalies if a.anomaly_type == "service_down"]
        assert len(down) == 1
        assert down[0].severity_hint == Severity.MEDIUM

    def test_detects_error_service(self, error_status, normal_metrics):
        d = AnomalyDetector()
        anomalies = d.detect(normal_metrics, error_status)
        down = [a for a in anomalies if a.anomaly_type == "service_down"]
        assert len(down) == 1
        assert down[0].severity_hint == Severity.HIGH

    def test_error_includes_details(self, error_status, normal_metrics):
        d = AnomalyDetector()
        anomalies = d.detect(normal_metrics, error_status)
        down = anomalies[0]
        assert "OOMKilled" in down.evidence
        assert "5" in down.evidence  # restart count

    def test_stopped_skips_metrics(self, stopped_status):
        # Even with no metrics at all, service_down is detected from status
        d = AnomalyDetector()
        anomalies = d.detect({}, stopped_status)
        assert len(anomalies) == 1
        assert anomalies[0].anomaly_type == "service_down"


class TestCrashLoopDetection:
    def test_detects_crash_loop(self, crash_loop_status):
        metrics = {
            "demo-app": MetricSnapshot(
                service_name="demo-app", cpu_percent=30.0,
                memory_used_bytes=100, memory_percent=10.0,
            ),
        }
        d = AnomalyDetector()
        anomalies = d.detect(metrics, crash_loop_status)
        crash = [a for a in anomalies if a.anomaly_type == "crash_loop"]
        assert len(crash) == 1
        assert crash[0].severity_hint == Severity.HIGH

    def test_no_crash_loop_with_few_restarts(self, running_status):
        running_status["demo-app"].restart_count = 2
        metrics = {
            "demo-app": MetricSnapshot(
                service_name="demo-app", cpu_percent=30.0,
                memory_used_bytes=100, memory_percent=10.0,
            ),
        }
        d = AnomalyDetector()
        anomalies = d.detect(metrics, running_status)
        crash = [a for a in anomalies if a.anomaly_type == "crash_loop"]
        assert len(crash) == 0


class TestCooldown:
    def test_cooldown_prevents_duplicate(self, high_cpu_metrics, running_status):
        d = AnomalyDetector()
        # First detection
        a1 = d.detect(high_cpu_metrics, running_status, cooldown_seconds=300)
        assert len(a1) > 0

        # Second detection within cooldown — should be suppressed
        a2 = d.detect(high_cpu_metrics, running_status, cooldown_seconds=300)
        assert len(a2) == 0

    def test_cooldown_expires(self, high_cpu_metrics, running_status):
        d = AnomalyDetector()
        # First detection
        a1 = d.detect(high_cpu_metrics, running_status, cooldown_seconds=1)
        assert len(a1) > 0

        # Manually expire cooldown
        d._cooldowns["demo-app"] = datetime.now(timezone.utc) - timedelta(seconds=2)

        # Now it should trigger again
        a2 = d.detect(high_cpu_metrics, running_status, cooldown_seconds=1)
        assert len(a2) > 0

    def test_zero_cooldown(self, high_cpu_metrics, running_status):
        d = AnomalyDetector()
        a1 = d.detect(high_cpu_metrics, running_status, cooldown_seconds=0)
        assert len(a1) > 0
        # With 0 cooldown, detections still set a timestamp, but 0s means no wait
        # The next call's timestamp will be >= the cooldown time, so it fires again
        # Actually cooldown_seconds=0 means (now - last).total_seconds() < 0 is always False
        # so it should always fire
        a2 = d.detect(high_cpu_metrics, running_status, cooldown_seconds=0)
        assert len(a2) > 0


class TestMultipleServices:
    def test_multiple_service_anomalies(self):
        metrics = {
            "app1": MetricSnapshot(
                service_name="app1", cpu_percent=95.0,
                memory_used_bytes=100, memory_percent=10.0,
            ),
            "app2": MetricSnapshot(
                service_name="app2", cpu_percent=20.0,
                memory_used_bytes=900, memory_limit_bytes=1000,
                memory_percent=90.0,
            ),
        }
        statuses = {
            "app1": ServiceStatus(name="app1", state=ServiceState.RUNNING, restart_count=0),
            "app2": ServiceStatus(name="app2", state=ServiceState.RUNNING, restart_count=0),
        }
        d = AnomalyDetector()
        anomalies = d.detect(metrics, statuses)
        types = {a.anomaly_type for a in anomalies}
        assert "high_cpu" in types
        assert "high_memory" in types
        services = {a.service_name for a in anomalies}
        assert "app1" in services
        assert "app2" in services


class TestNoAnomaly:
    def test_empty_inputs(self):
        d = AnomalyDetector()
        assert d.detect({}, {}) == []

    def test_no_metrics_running_service(self, running_status):
        d = AnomalyDetector()
        assert d.detect({}, running_status) == []
