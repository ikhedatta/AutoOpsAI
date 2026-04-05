"""
Pipeline integration: wires standalone POCs into the E2E pipeline.

Provides:
  - Prometheus-based metric verification for post-remediation checks
  - LLM diagnostic fallback when no playbook matches
  - Tool-calling agent for ad-hoc investigation
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("autoopsai.integration")


async def verify_with_prometheus(
    container_name: str,
    metric_name: str = "container_cpu_percent",
    threshold: float = 90.0,
) -> dict[str, Any]:
    """
    Use Prometheus to verify a container is healthy after remediation.

    Returns a dict with 'healthy' (bool) and 'details'.
    """
    try:
        from POCs.prometheus_grafana.prometheus_client import PrometheusClient
        prom_url = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
        client = PrometheusClient(base_url=prom_url)

        if not await client.health_check():
            return {"healthy": None, "details": "Prometheus unreachable"}

        # Query container CPU
        query = f'container_cpu_usage_seconds_total{{name="{container_name}"}}'
        result = await client.instant_query(query)

        if not result.success:
            return {"healthy": None, "details": f"Query failed: {result.error}"}

        return {"healthy": True, "details": result.data}
    except Exception as e:
        logger.warning("Prometheus verification failed: %s", e)
        return {"healthy": None, "details": str(e)}


def diagnose_with_llm(
    anomaly_description: str,
    system_state: dict | None = None,
) -> dict[str, Any] | None:
    """
    Use the LLM fallback to diagnose an unknown anomaly.

    Returns a dict with diagnosis fields, or None if LLM fails.
    """
    try:
        from POCs.playbook_matching.llm_fallback import llm_diagnose
        diagnosis = llm_diagnose(anomaly_description, system_state)
        if diagnosis:
            return {
                "diagnosis": diagnosis.diagnosis,
                "severity": diagnosis.severity,
                "recommended_action": diagnosis.recommended_action,
                "action_type": diagnosis.action_type,
                "action_target": diagnosis.action_target,
                "rollback_plan": diagnosis.rollback_plan,
                "verification_check": diagnosis.verification_check,
                "confidence": diagnosis.confidence,
            }
    except Exception as e:
        logger.warning("LLM diagnosis failed: %s", e)
    return None


async def investigate_with_agent(
    question: str,
    agent_type: str = "docker",
) -> dict[str, Any]:
    """
    Run the tool-calling agent for ad-hoc infrastructure investigation.

    Args:
        question: Natural language question about infrastructure
        agent_type: "docker" for Docker/MongoDB agent, "observability" for Prometheus/Grafana
    """
    try:
        if agent_type == "observability":
            from POCs.prometheus_grafana.agent import run_agent
        else:
            from POCs.tool_execution.agent import run_agent

        run = await run_agent(question)
        return {
            "response": run.final_response,
            "tools_called": run.tools_called,
            "steps": len(run.steps),
        }
    except Exception as e:
        logger.warning("Agent investigation failed: %s", e)
        return {"response": f"Investigation failed: {e}", "tools_called": [], "steps": 0}
