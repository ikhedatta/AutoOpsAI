"""
conftest.py — shared pytest fixtures for all POC tests.
"""

import os
import pytest

# Ensure .env is loaded before any POC imports
os.environ.setdefault("OLLAMA_BASE", "http://localhost:11434")
os.environ.setdefault("OLLAMA_MODEL", "qwen3:4b")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGODB_DATABASE", "autoopsai_test")


@pytest.fixture
def playbooks_dir(tmp_path):
    """Create a temporary playbooks directory with sample YAML."""
    import yaml

    general = [
        {
            "id": "high_cpu_container",
            "name": "High CPU Container",
            "severity": "MEDIUM",
            "detection": {
                "type": "metric_threshold",
                "conditions": [{"metric": "container_cpu_percent", "threshold": "> 90"}],
            },
            "diagnosis": "Container has high CPU usage for extended period",
            "remediation": {
                "steps": [
                    {"action": "collect_diagnostics", "command": "docker stats {container} --no-stream"},
                    {"action": "docker_restart", "target": "{container}", "timeout": "30s"},
                    {"action": "metric_check", "metric": "container_cpu_percent", "expected": "< 80"},
                ],
            },
        },
        {
            "id": "container_restart_loop",
            "name": "Container Restart Loop",
            "severity": "HIGH",
            "detection": {
                "type": "container_health",
                "conditions": [{"restart_count": "> 3"}],
            },
            "diagnosis": "Container stuck in restart loop",
            "remediation": {
                "steps": [
                    {"action": "collect_logs", "target": "{container}", "tail": 200},
                    {"action": "escalate", "message": "Manual investigation required"},
                ],
            },
        },
    ]

    redis = [
        {
            "id": "redis_memory_full",
            "name": "Redis Memory Full",
            "severity": "LOW",
            "detection": {
                "type": "metric_threshold",
                "conditions": [{"metric": "container_memory_percent", "threshold": "> 90"}],
            },
            "diagnosis": "Redis memory usage is too high",
            "remediation": {
                "steps": [
                    {"action": "redis_command", "command": "MEMORY PURGE"},
                    {"action": "metric_check", "metric": "container_memory_percent", "expected": "< 80"},
                ],
            },
        },
    ]

    (tmp_path / "general.yaml").write_text(yaml.dump(general))
    (tmp_path / "redis.yaml").write_text(yaml.dump(redis))
    return tmp_path
