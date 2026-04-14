"""
Grafana webhook receiver.

Grafana Unified Alerting sends a POST request to this endpoint whenever
an alert fires or resolves.  We create (or resolve) AutoOpsAI incidents
so they appear in the Incidents dashboard automatically.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from agent.models import Action, Anomaly, Diagnosis, IncidentStatus, Severity
from agent.store import incidents as incident_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


def _severity_from_alert(alertname: str, labels: dict) -> Severity:
    name = alertname.lower()
    if "500" in name or "503" in name or "critical" in labels.get("severity", "").lower():
        return Severity.HIGH
    if "404" in name or "error" in name or "warn" in labels.get("severity", "").lower():
        return Severity.MEDIUM
    return Severity.LOW


def _anomaly_type_from_alert(alertname: str) -> str:
    name = alertname.lower()
    if any(code in name for code in ["500", "503", "404"]):
        return "threshold"
    if "error" in name or "log" in name:
        return "log_pattern"
    return "threshold"


def _service_from_alert(labels: dict) -> str:
    for key in ("service", "service_name", "job", "container", "instance"):
        val = labels.get(key, "")
        if val and val not in ("ms_app_logs", "docker", "varlogs"):
            return val
    return labels.get("grafana_folder", "unknown")


@router.post("/grafana")
async def grafana_webhook(request: Request):
    """Receive Grafana Unified Alerting webhook and create/resolve incidents."""
    from agent.main import app_state  # avoid circular import at module load

    body: dict[str, Any] = await request.json()
    alerts: list = body.get("alerts", [])
    created_ids: list[str] = []
    resolved_ids: list[str] = []

    for alert in alerts:
        status = alert.get("status", "")
        labels: dict = alert.get("labels", {})
        annotations: dict = alert.get("annotations", {})
        alertname: str = labels.get("alertname", annotations.get("summary", "Unknown Alert"))
        starts_at: str = alert.get("startsAt", "")
        value_str: str = alert.get("valueString", "")

        service = _service_from_alert(labels)
        anomaly_type = _anomaly_type_from_alert(alertname)
        severity = _severity_from_alert(alertname, labels)

        if status == "firing":
            # Deduplicate - skip if an active incident already exists for this alert
            existing = await incident_store.find_active_incident(service, anomaly_type)
            if existing and alertname.lower() in existing.title.lower():
                logger.info("Duplicate alert skipped - incident %s already active", existing.incident_id)
                continue

            evidence = (
                annotations.get("description", "")
                or f'Grafana alert "{alertname}" fired at {starts_at}. Value: {value_str}'
            )
            anomaly = Anomaly(
                service_name=service,
                anomaly_type=anomaly_type,
                metric=alertname,
                evidence=evidence,
                severity_hint=severity,
            )
            diagnosis = Diagnosis(
                summary=annotations.get("summary", alertname),
                explanation=annotations.get("description", "") or f'Alert "{alertname}" fired. Value: {value_str}',
                confidence=0.9,
                root_cause=annotations.get("runbook_url", None),
            )

            doc = await incident_store.create_incident(
                anomaly=anomaly,
                diagnosis=diagnosis,
                proposed_actions=[],
                severity=severity,
            )
            doc.title = alertname
            await doc.save()

            created_ids.append(doc.incident_id)
            logger.info("Incident created from Grafana alert: %s -> %s", alertname, doc.incident_id)

            # Notify WebSocket clients so the incidents page updates live
            ws_manager = app_state.get("ws_manager")
            if ws_manager:
                await ws_manager.broadcast("incident_created", {
                    "incident_id": doc.incident_id,
                    "title": doc.title,
                    "severity": doc.severity,
                    "service": service,
                    "source": "grafana_alert",
                })

            # Send email notification for the new incident
            try:
                from agent.notifications.email_service import send_new_incident_email
                await send_new_incident_email(
                    incident_id=doc.incident_id,
                    title=doc.title,
                    service_name=service,
                    severity=doc.severity,
                    evidence=evidence,
                )
            except Exception as _email_exc:
                logger.warning("New-incident email failed: %s", _email_exc)

        elif status == "resolved":
            existing = await incident_store.find_active_incident(service, anomaly_type)
            if existing and alertname.lower() in existing.title.lower():
                await incident_store.update_status(
                    existing.incident_id,
                    IncidentStatus.RESOLVED,
                    detail=f'Grafana alert "{alertname}" resolved',
                )
                resolved_ids.append(existing.incident_id)
                logger.info("Incident resolved from Grafana: %s -> %s", alertname, existing.incident_id)

                ws_manager = app_state.get("ws_manager")
                if ws_manager:
                    await ws_manager.broadcast("incident_resolved", {"incident_id": existing.incident_id})

    return {
        "status": "ok",
        "created": len(created_ids),
        "resolved": len(resolved_ids),
        "incident_ids": created_ids,
    }
