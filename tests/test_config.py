"""Tests for agent.config — Settings loading and defaults."""

from __future__ import annotations

import os

import pytest

from agent.config import Settings, get_settings


class TestSettings:
    def test_default_values(self):
        s = Settings(
            _env_file=None,  # Don't read .env for tests
        )
        assert s.ollama_host == "http://localhost:11434"
        assert s.ollama_model == "llama3:8b"
        assert s.provider_type == "docker_compose"
        assert s.mongodb_url == "mongodb://localhost:27017/autoops"
        assert s.polling_interval_seconds == 15
        assert s.cooldown_seconds == 300
        assert s.approval_timeout_medium_seconds == 300
        assert s.approval_timeout_medium_default == "deny"
        assert s.api_key == ""
        assert s.playbooks_dir == "playbooks"

    def test_override_via_constructor(self):
        s = Settings(
            ollama_model="qwen3:4b",
            polling_interval_seconds=5,
            mongodb_url="mongodb://test:27017/test",
            _env_file=None,
        )
        assert s.ollama_model == "qwen3:4b"
        assert s.polling_interval_seconds == 5
        assert s.mongodb_url == "mongodb://test:27017/test"

    def test_playbooks_path_property(self):
        s = Settings(playbooks_dir="my_playbooks", _env_file=None)
        assert s.playbooks_path.name == "my_playbooks"

    def test_extra_fields_ignored(self):
        # extra="ignore" in model_config
        s = Settings(nonexistent_field="whatever", _env_file=None)
        assert not hasattr(s, "nonexistent_field")

    def test_get_settings_returns_singleton(self):
        # Clear the lru_cache
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
        get_settings.cache_clear()
