"""
Observability API routes — expose Prometheus metrics, Loki logs,
and Grafana dashboard data to the frontend.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/observability", tags=["observability"])


def _get_clients():
    """Retrieve observability clients from app_state."""
    from agent.main import app_state
    return (
        app_state.get("prometheus"),
        app_state.get("loki"),
        app_state.get("grafana"),
    )


# -----------------------------------------------------------------------
# Prometheus
# -----------------------------------------------------------------------

@router.get("/prometheus/health")
async def prometheus_health():
    prom, _, _ = _get_clients()
    if not prom:
        return {"available": False, "reason": "client_not_configured"}
    ok = await prom.is_available()
    return {"available": ok}


@router.get("/prometheus/query")
async def prometheus_query(promql: str = Query(..., description="PromQL expression")):
    prom, _, _ = _get_clients()
    if not prom:
        raise HTTPException(503, "Prometheus client not configured")
    result = await prom.query(promql)
    return {"query": promql, "result": result}


@router.get("/prometheus/query_range")
async def prometheus_query_range(
    promql: str = Query(..., description="PromQL expression"),
    duration_minutes: int = Query(30, ge=1, le=1440),
    step: str = Query("60s"),
):
    prom, _, _ = _get_clients()
    if not prom:
        raise HTTPException(503, "Prometheus client not configured")
    result = await prom.query_range(promql, step=step, duration_minutes=duration_minutes)
    return {"query": promql, "duration_minutes": duration_minutes, "step": step, "result": result}


@router.get("/prometheus/targets")
async def prometheus_targets():
    prom, _, _ = _get_clients()
    if not prom:
        raise HTTPException(503, "Prometheus client not configured")
    targets = await prom.get_targets()
    return {"targets": targets}


@router.get("/prometheus/alerts")
async def prometheus_alerts():
    prom, _, _ = _get_clients()
    if not prom:
        raise HTTPException(503, "Prometheus client not configured")
    alerts = await prom.get_alerts()
    return {"alerts": alerts}


@router.get("/prometheus/metric_names")
async def prometheus_metric_names(match: str | None = Query(None)):
    prom, _, _ = _get_clients()
    if not prom:
        raise HTTPException(503, "Prometheus client not configured")
    names = await prom.get_metric_names(match)
    return {"count": len(names), "names": names}


# -----------------------------------------------------------------------
# Loki
# -----------------------------------------------------------------------

@router.get("/loki/health")
async def loki_health():
    _, loki, _ = _get_clients()
    if not loki:
        return {"available": False, "reason": "client_not_configured"}
    ok = await loki.is_available()
    return {"available": ok}


@router.get("/loki/query")
async def loki_query(
    logql: str = Query(..., description="LogQL expression"),
    limit: int = Query(100, ge=1, le=5000),
    duration_minutes: int = Query(30, ge=1, le=1440),
):
    _, loki, _ = _get_clients()
    if not loki:
        raise HTTPException(503, "Loki client not configured")
    entries = await loki.query(logql, limit=limit, duration_minutes=duration_minutes)
    return {
        "query": logql,
        "count": len(entries),
        "entries": [e.model_dump() for e in entries],
    }


@router.get("/loki/labels")
async def loki_labels():
    _, loki, _ = _get_clients()
    if not loki:
        raise HTTPException(503, "Loki client not configured")
    labels = await loki.get_labels()
    return {"labels": labels}


@router.get("/loki/label/{label}/values")
async def loki_label_values(label: str):
    _, loki, _ = _get_clients()
    if not loki:
        raise HTTPException(503, "Loki client not configured")
    values = await loki.get_label_values(label)
    return {"label": label, "values": values}


# -----------------------------------------------------------------------
# Grafana
# -----------------------------------------------------------------------

@router.get("/grafana/health")
async def grafana_health():
    _, _, grafana = _get_clients()
    if not grafana:
        return {"available": False, "reason": "client_not_configured"}
    ok = await grafana.is_available()
    return {"available": ok}


@router.get("/grafana/dashboards")
async def grafana_dashboards(query: str | None = Query(None)):
    _, _, grafana = _get_clients()
    if not grafana:
        raise HTTPException(503, "Grafana client not configured")
    dashboards = await grafana.list_dashboards(query)
    return {"dashboards": dashboards}


@router.get("/grafana/dashboards/{uid}")
async def grafana_dashboard_detail(uid: str):
    _, _, grafana = _get_clients()
    if not grafana:
        raise HTTPException(503, "Grafana client not configured")
    dashboard = await grafana.get_dashboard(uid)
    if not dashboard:
        raise HTTPException(404, f"Dashboard {uid} not found")
    return dashboard


@router.get("/grafana/annotations")
async def grafana_annotations(
    dashboard_uid: str | None = Query(None),
    duration_minutes: int = Query(60, ge=1, le=1440),
):
    _, _, grafana = _get_clients()
    if not grafana:
        raise HTTPException(503, "Grafana client not configured")
    annotations = await grafana.get_annotations(dashboard_uid, duration_minutes)
    return {"annotations": annotations}


@router.get("/grafana/datasources")
async def grafana_datasources():
    _, _, grafana = _get_clients()
    if not grafana:
        raise HTTPException(503, "Grafana client not configured")
    sources = await grafana.get_datasources()
    return {"datasources": sources}


# -----------------------------------------------------------------------
# Combined health check
# -----------------------------------------------------------------------

@router.get("/health")
async def observability_health():
    prom, loki, grafana = _get_clients()
    result = {}
    result["prometheus"] = await prom.is_available() if prom else False
    result["loki"] = await loki.is_available() if loki else False
    result["grafana"] = await grafana.is_available() if grafana else False
    all_ok = all(result.values())
    return {"status": "healthy" if all_ok else "degraded", "components": result}
