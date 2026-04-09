"""Benchmark Loki query latencies."""
import asyncio
import time
from agent.collector.loki_client import LokiClient

async def main():
    loki = LokiClient("http://10.41.31.20:3100", timeout=45.0)

    queries = [
        ('{container=~".+"}', "all containers (no filter)"),
        ('{container="grafana"}', "grafana only"),
        ('{container="grafana"} |~ "(?i)error"', "grafana errors"),
        ('{container=~".+"} |~ "(?i)error"', "all containers errors"),
        ('{container="node-exporter"} |~ "(?i)error"', "node-exporter errors"),
    ]
    for q, label in queries:
        start = time.time()
        entries = await loki.query(q, limit=20, duration_minutes=60)
        elapsed = time.time() - start
        print(f"  {elapsed:.1f}s | {len(entries):3d} entries | {label}")

    await loki.close()

asyncio.run(main())
