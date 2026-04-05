"""
Remediation executor: runs fix actions and verification checks.

Supports:
  - docker_restart: restart a container
  - docker_exec: run a command inside a container
  - redis_command: execute a Redis CLI command
  - health_check: verify a container/service is healthy
  - collect_logs: gather container logs for investigation
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import docker
from docker.errors import NotFound, APIError

logger = logging.getLogger("autoopsai.executor")


class ActionStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


@dataclass
class ActionResult:
    """Result of executing a single remediation step."""
    action: str
    target: str
    status: ActionStatus
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0


@dataclass
class RemediationResult:
    """Result of a complete remediation attempt (all steps)."""
    playbook_id: str
    container_name: str
    steps: list[ActionResult] = field(default_factory=list)
    verified: bool = False
    total_duration_ms: float = 0.0
    escalated: bool = False
    escalation_message: str = ""


class RemediationExecutor:
    """Executes remediation steps from a playbook entry."""

    def __init__(self):
        self._docker = docker.from_env()

    def execute_playbook(
        self,
        playbook_id: str,
        container_name: str,
        steps: list[dict],
        max_retries: int = 1,
    ) -> RemediationResult:
        """
        Execute all steps in a remediation playbook.

        If a step fails and retries are available, retries once.
        If all retries fail, marks as escalated.
        """
        result = RemediationResult(
            playbook_id=playbook_id,
            container_name=container_name,
        )
        overall_start = time.time()

        for step in steps:
            action = step.get("action", "")
            # Substitute {container} placeholder
            step_resolved = {
                k: v.replace("{container}", container_name) if isinstance(v, str) else v
                for k, v in step.items()
            }

            step_result = self._execute_step(step_resolved)
            result.steps.append(step_result)
            logger.info("Step %s on %s: %s (%.0fms)",
                        action, step_resolved.get("target", ""), step_result.status.value, step_result.duration_ms)

            if step_result.status == ActionStatus.FAILED:
                # Retry once
                if max_retries > 0:
                    time.sleep(2)  # Brief pause before retry
                    retry_result = self._execute_step(step_resolved)
                    retry_result.action = f"{retry_result.action} (retry)"
                    result.steps.append(retry_result)
                    if retry_result.status == ActionStatus.FAILED:
                        result.escalated = True
                        result.escalation_message = (
                            f"Step '{action}' failed after retry: {retry_result.error}"
                        )
                        break
                else:
                    result.escalated = True
                    result.escalation_message = (
                        f"Step '{action}' failed: {step_result.error}"
                    )
                    break

            if action == "escalate":
                result.escalated = True
                result.escalation_message = step.get("message", "Manual investigation required.")
                break

        result.total_duration_ms = (time.time() - overall_start) * 1000

        # Mark as verified if we completed all steps without escalation
        if not result.escalated:
            result.verified = all(
                s.status == ActionStatus.SUCCESS for s in result.steps
            )

        return result

    def _execute_step(self, step: dict) -> ActionResult:
        """Execute a single remediation step."""
        action = step.get("action", "")
        target = step.get("target", "")

        start = time.time()
        try:
            if action == "docker_restart":
                return self._do_docker_restart(target, step, start)
            elif action == "health_check":
                return self._do_health_check(target, step, start)
            elif action == "docker_exec":
                return self._do_docker_exec(target, step, start)
            elif action == "redis_command":
                return self._do_redis_command(step, start)
            elif action == "collect_logs":
                return self._do_collect_logs(target, step, start)
            elif action == "collect_diagnostics":
                return self._do_collect_diagnostics(step, start)
            elif action == "metric_check":
                return self._do_metric_check(step, start)
            elif action == "escalate":
                return ActionResult(
                    action=action, target=target,
                    status=ActionStatus.SUCCESS,
                    output=step.get("message", "Escalated"),
                    duration_ms=(time.time() - start) * 1000,
                )
            else:
                return ActionResult(
                    action=action, target=target,
                    status=ActionStatus.SKIPPED,
                    error=f"Unknown action type: {action}",
                    duration_ms=(time.time() - start) * 1000,
                )
        except Exception as e:
            return ActionResult(
                action=action, target=target,
                status=ActionStatus.FAILED,
                error=str(e),
                duration_ms=(time.time() - start) * 1000,
            )

    def _do_docker_restart(self, target: str, step: dict, start: float) -> ActionResult:
        timeout_str = step.get("timeout", "30s")
        timeout_sec = int(timeout_str.rstrip("s")) if isinstance(timeout_str, str) else 30

        container = self._docker.containers.get(target)
        container.restart(timeout=timeout_sec)

        # Wait briefly for container to be ready
        time.sleep(2)
        container.reload()
        status = container.status

        return ActionResult(
            action="docker_restart", target=target,
            status=ActionStatus.SUCCESS if status == "running" else ActionStatus.FAILED,
            output=f"Container '{target}' restarted, status={status}",
            error="" if status == "running" else f"Container status after restart: {status}",
            duration_ms=(time.time() - start) * 1000,
        )

    def _do_health_check(self, target: str, step: dict, start: float) -> ActionResult:
        check_cmd = step.get("check", "")
        timeout_str = step.get("timeout", "10s")

        try:
            container = self._docker.containers.get(target)
            container.reload()

            if container.status != "running":
                return ActionResult(
                    action="health_check", target=target,
                    status=ActionStatus.FAILED,
                    error=f"Container not running: {container.status}",
                    duration_ms=(time.time() - start) * 1000,
                )

            # If a check command is provided, run it
            if check_cmd:
                exec_result = container.exec_run(check_cmd, demux=True)
                stdout = (exec_result.output[0] or b"").decode("utf-8", errors="replace")
                exit_code = exec_result.exit_code

                return ActionResult(
                    action="health_check", target=target,
                    status=ActionStatus.SUCCESS if exit_code == 0 else ActionStatus.FAILED,
                    output=stdout[:500],
                    error="" if exit_code == 0 else f"Health check exited with code {exit_code}",
                    duration_ms=(time.time() - start) * 1000,
                )

            # No check command — just verify container is running
            return ActionResult(
                action="health_check", target=target,
                status=ActionStatus.SUCCESS,
                output=f"Container '{target}' is running",
                duration_ms=(time.time() - start) * 1000,
            )

        except NotFound:
            return ActionResult(
                action="health_check", target=target,
                status=ActionStatus.FAILED,
                error=f"Container '{target}' not found",
                duration_ms=(time.time() - start) * 1000,
            )

    def _do_docker_exec(self, target: str, step: dict, start: float) -> ActionResult:
        command = step.get("command", "")
        container = self._docker.containers.get(target)
        exec_result = container.exec_run(command, demux=True)
        stdout = (exec_result.output[0] or b"").decode("utf-8", errors="replace")

        return ActionResult(
            action="docker_exec", target=target,
            status=ActionStatus.SUCCESS if exec_result.exit_code == 0 else ActionStatus.FAILED,
            output=stdout[:1000],
            error="" if exec_result.exit_code == 0 else f"Exit code: {exec_result.exit_code}",
            duration_ms=(time.time() - start) * 1000,
        )

    def _do_redis_command(self, step: dict, start: float) -> ActionResult:
        command = step.get("command", "")
        # Execute via docker exec on the redis container
        try:
            container = self._docker.containers.get("redis")
            exec_result = container.exec_run(f"redis-cli {command}", demux=True)
            stdout = (exec_result.output[0] or b"").decode("utf-8", errors="replace")

            return ActionResult(
                action="redis_command", target="redis",
                status=ActionStatus.SUCCESS if exec_result.exit_code == 0 else ActionStatus.FAILED,
                output=stdout[:500],
                duration_ms=(time.time() - start) * 1000,
            )
        except NotFound:
            return ActionResult(
                action="redis_command", target="redis",
                status=ActionStatus.FAILED,
                error="Redis container not found",
                duration_ms=(time.time() - start) * 1000,
            )

    def _do_collect_logs(self, target: str, step: dict, start: float) -> ActionResult:
        tail = step.get("tail", 100)
        container = self._docker.containers.get(target)
        logs = container.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")

        return ActionResult(
            action="collect_logs", target=target,
            status=ActionStatus.SUCCESS,
            output=f"Collected {len(logs.splitlines())} log lines",
            duration_ms=(time.time() - start) * 1000,
        )

    def _do_collect_diagnostics(self, step: dict, start: float) -> ActionResult:
        command = step.get("command", "")
        # Parse "docker exec <container> <cmd>" or "docker stats <container> --no-stream"
        if command.startswith("docker exec "):
            parts = command.split(maxsplit=3)
            if len(parts) >= 4:
                target = parts[2]
                cmd = parts[3]
                return self._do_docker_exec(target, {"command": cmd}, start)

        if command.startswith("docker stats "):
            parts = command.split()
            target = parts[2] if len(parts) >= 3 else "unknown"
            container = self._docker.containers.get(target)
            stats = container.stats(stream=False)
            return ActionResult(
                action="collect_diagnostics", target=target,
                status=ActionStatus.SUCCESS,
                output=f"CPU: {stats.get('cpu_stats', {})}, Mem: {stats.get('memory_stats', {})}",
                duration_ms=(time.time() - start) * 1000,
            )

        return ActionResult(
            action="collect_diagnostics", target="",
            status=ActionStatus.SKIPPED,
            error=f"Unsupported diagnostics command: {command}",
            duration_ms=(time.time() - start) * 1000,
        )

    def _do_metric_check(self, step: dict, start: float) -> ActionResult:
        """Placeholder — in production this would query Prometheus."""
        metric = step.get("metric", "")
        expected = step.get("expected", "")

        return ActionResult(
            action="metric_check", target=metric,
            status=ActionStatus.SUCCESS,
            output=f"Metric check '{metric}' {expected} — simulated OK",
            duration_ms=(time.time() - start) * 1000,
        )
