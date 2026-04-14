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

    # -- LLM Provider -------------------------------------------------------
    llm_provider: str = "ollama"  # "ollama" or "github"

    # -- LLM (Ollama) -------------------------------------------------------
    ollama_host: str = "https://localhost:11434"
    ollama_model: str = "gemma3:4b"
    ollama_fallback_model: str = "qwen3:4b"
    ollama_timeout: int = 120

    # -- LLM (GitHub Models) ------------------------------------------------
    github_token: str = ""
    github_model: str = "gpt-4o"
    github_models_endpoint: str = "https://models.inference.ai.azure.com"
    llm_max_tokens: int = 4096
    llm_timeout: int = 120

    # -- Infrastructure Provider ---------------------------------------------
    provider_type: str = "docker_compose"
    compose_project_name: str = "autoops-demo"
    compose_file: str = "infra/docker-compose.target.yml"
    polling_interval_seconds: int = 15

    # -- Database (MongoDB) --------------------------------------------------
    mongodb_url: str = "mongodb://localhost:27017/autoops"

    # -- Observability -------------------------------------------------------
    prometheus_url: str = "https://localhost:9090"
    loki_url: str = "https://localhost:3100"
    grafana_url: str = "https://localhost:3000"
    grafana_user: str = ""
    grafana_password: str = ""

    # -- Approval ------------------------------------------------------------
    approval_timeout_medium_seconds: int = 300
    approval_timeout_medium_default: str = "deny"

    # -- Email / SMTP --------------------------------------------------------
    smtp_host: str = "inetmail.emrsn.net"
    smtp_port: int = 25
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "pkm-noreply@emerson.com"
    smtp_use_tls: bool = False
    escalation_recipients: str = "datta.ikhe@emerson.com,shubham.nangare@emerson.com"  # comma-separated list of emails
    incident_recipients: str = ""  # separate list for new-incident emails; falls back to escalation_recipients

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
    chat_history_turns: int = 10  # recent user+agent messages to include for context

    # -- Teams Bot Framework -------------------------------------------------
    teams_bot_enabled: bool = False
    teams_app_id: str = ""
    teams_app_secret: str = ""
    teams_tenant_id: str = ""
    teams_bot_endpoint: str = "/api/messages"

    # -- Docker host override ------------------------------------------------
    docker_host: str = ""

    @property
    def playbooks_path(self) -> Path:
        return Path(self.playbooks_dir)


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton of the application settings."""
    return Settings()
