"""
Centralised application settings.

Reads from environment variables and ``.env`` file via pydantic-settings.
Every configurable knob lives here — no magic strings scattered across modules.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- LLM (Ollama) -------------------------------------------------------
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "gemma3:4b"
    ollama_fallback_model: str = "qwen3:4b"
    ollama_timeout: int = 120

    # -- Infrastructure Provider ---------------------------------------------
    provider_type: str = "docker_compose"
    compose_project_name: str = "autoops-demo"
    compose_file: str = "infra/docker-compose.target.yml"
    polling_interval_seconds: int = 15

    # -- Database (MongoDB) --------------------------------------------------
    mongodb_url: str = "mongodb://localhost:27017/autoops"

    # -- Observability -------------------------------------------------------
    prometheus_url: str = "http://localhost:9090"
    loki_url: str = "http://localhost:3100"
    grafana_url: str = "http://localhost:3000"
    grafana_user: str = ""
    grafana_password: str = ""

    # -- Approval ------------------------------------------------------------
    approval_timeout_medium_seconds: int = 300
    approval_timeout_medium_default: str = "deny"

    # -- API Security (pre-RBAC) ---------------------------------------------
    api_key: str = ""

    # -- Agent tuning --------------------------------------------------------
    cooldown_seconds: int = 300
    max_concurrent_remediations: int = 3
    playbooks_dir: str = "playbooks"

    # -- Tool-augmented chat -------------------------------------------------
    chat_tool_calling_enabled: bool = True
    chat_max_tool_iterations: int = 5
    tool_timeout_seconds: int = 5

    # -- Docker host override ------------------------------------------------
    docker_host: str = ""

    @property
    def playbooks_path(self) -> Path:
        return Path(self.playbooks_dir)


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton of the application settings."""
    return Settings()
