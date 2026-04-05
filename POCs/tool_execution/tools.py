"""
Tool definitions and executors for Docker and MongoDB operations.

Each tool has:
  - A schema (name, description, parameters) sent to the LLM
  - An execute() function that performs the real action
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import docker
import pymongo


# --- Tool result -------------------------------------------------------------

@dataclass
class ToolResult:
    tool: str
    success: bool
    output: Any
    error: str | None = None


# --- Tool schemas (sent to Ollama) -------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "docker_list_containers",
            "description": "List all Docker containers with their status, image, and ports.",
            "parameters": {
                "type": "object",
                "properties": {
                    "all": {
                        "type": "boolean",
                        "description": "Include stopped containers. Default true.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "docker_inspect_container",
            "description": "Get detailed info about a specific Docker container (state, config, network).",
            "parameters": {
                "type": "object",
                "properties": {
                    "container_name": {
                        "type": "string",
                        "description": "Name or ID of the container to inspect.",
                    }
                },
                "required": ["container_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "docker_container_logs",
            "description": "Retrieve recent logs from a Docker container.",
            "parameters": {
                "type": "object",
                "properties": {
                    "container_name": {
                        "type": "string",
                        "description": "Name or ID of the container.",
                    },
                    "tail": {
                        "type": "integer",
                        "description": "Number of recent log lines to retrieve. Default 50.",
                    },
                },
                "required": ["container_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "docker_restart_container",
            "description": "Restart a Docker container. Use when remediation requires a container restart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "container_name": {
                        "type": "string",
                        "description": "Name or ID of the container to restart.",
                    }
                },
                "required": ["container_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "docker_container_stats",
            "description": "Get CPU, memory, and network stats for a running Docker container.",
            "parameters": {
                "type": "object",
                "properties": {
                    "container_name": {
                        "type": "string",
                        "description": "Name or ID of the container.",
                    }
                },
                "required": ["container_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mongodb_server_status",
            "description": "Get MongoDB server status including connections, opcounters, memory, and uptime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "MongoDB host. Default 'localhost:27017'.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mongodb_list_databases",
            "description": "List all MongoDB databases with their sizes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "MongoDB host. Default 'localhost:27017'.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mongodb_current_operations",
            "description": "List currently running MongoDB operations. Useful for finding slow or stuck queries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "MongoDB host. Default 'localhost:27017'.",
                    }
                },
                "required": [],
            },
        },
    },
]


# --- Tool executors -----------------------------------------------------------

def _get_docker_client() -> docker.DockerClient:
    return docker.from_env()


def execute_docker_list_containers(all: bool = True) -> ToolResult:
    try:
        client = _get_docker_client()
        containers = client.containers.list(all=all)
        data = []
        for c in containers:
            data.append({
                "name": c.name,
                "id": c.short_id,
                "status": c.status,
                "image": str(c.image.tags[0]) if c.image.tags else str(c.image.id[:12]),
                "ports": c.ports,
            })
        return ToolResult(tool="docker_list_containers", success=True, output=data)
    except Exception as e:
        return ToolResult(tool="docker_list_containers", success=False, output=None, error=str(e))


def execute_docker_inspect_container(container_name: str) -> ToolResult:
    try:
        client = _get_docker_client()
        c = client.containers.get(container_name)
        info = {
            "name": c.name,
            "id": c.short_id,
            "status": c.status,
            "state": c.attrs.get("State", {}),
            "config": {
                "image": str(c.image.tags[0]) if c.image.tags else None,
                "env_count": len(c.attrs.get("Config", {}).get("Env", [])),
                "cmd": c.attrs.get("Config", {}).get("Cmd"),
            },
            "network": {k: v.get("IPAddress") for k, v in
                        c.attrs.get("NetworkSettings", {}).get("Networks", {}).items()},
            "ports": c.ports,
        }
        return ToolResult(tool="docker_inspect_container", success=True, output=info)
    except Exception as e:
        return ToolResult(tool="docker_inspect_container", success=False, output=None, error=str(e))


def execute_docker_container_logs(container_name: str, tail: int = 50) -> ToolResult:
    try:
        client = _get_docker_client()
        c = client.containers.get(container_name)
        logs = c.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")
        return ToolResult(tool="docker_container_logs", success=True, output=logs)
    except Exception as e:
        return ToolResult(tool="docker_container_logs", success=False, output=None, error=str(e))


def execute_docker_restart_container(container_name: str) -> ToolResult:
    try:
        client = _get_docker_client()
        c = client.containers.get(container_name)
        c.restart(timeout=30)
        return ToolResult(tool="docker_restart_container", success=True,
                          output=f"Container '{container_name}' restarted successfully.")
    except Exception as e:
        return ToolResult(tool="docker_restart_container", success=False, output=None, error=str(e))


def execute_docker_container_stats(container_name: str) -> ToolResult:
    try:
        client = _get_docker_client()
        c = client.containers.get(container_name)
        stats = c.stats(stream=False)
        # Extract key metrics
        cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - \
                    stats["precpu_stats"]["cpu_usage"]["total_usage"]
        system_delta = stats["cpu_stats"]["system_cpu_usage"] - \
                       stats["precpu_stats"]["system_cpu_usage"]
        num_cpus = stats["cpu_stats"].get("online_cpus", 1)
        cpu_pct = (cpu_delta / system_delta) * num_cpus * 100.0 if system_delta > 0 else 0.0

        mem_usage = stats["memory_stats"].get("usage", 0)
        mem_limit = stats["memory_stats"].get("limit", 1)
        mem_pct = (mem_usage / mem_limit) * 100.0

        data = {
            "cpu_percent": round(cpu_pct, 2),
            "memory_usage_mb": round(mem_usage / 1024 / 1024, 2),
            "memory_limit_mb": round(mem_limit / 1024 / 1024, 2),
            "memory_percent": round(mem_pct, 2),
        }
        return ToolResult(tool="docker_container_stats", success=True, output=data)
    except Exception as e:
        return ToolResult(tool="docker_container_stats", success=False, output=None, error=str(e))


def _validate_mongo_host(host: str) -> str:
    """Validate MongoDB host format (hostname:port or hostname)."""
    import re
    if not host or not re.match(r'^[a-zA-Z0-9._-]+(:\d{1,5})?$', host):
        raise ValueError(f"Invalid MongoDB host format: {host!r}. Expected 'hostname' or 'hostname:port'.")
    return host


def _get_mongo_client(host: str | None = None) -> pymongo.MongoClient:
    import os
    if host is None:
        host = os.getenv("MONGODB_HOST", "localhost:27017")
    host = _validate_mongo_host(host)
    return pymongo.MongoClient(f"mongodb://{host}", serverSelectionTimeoutMS=5000)


def execute_mongodb_server_status(host: str = "localhost:27017") -> ToolResult:
    try:
        client = _get_mongo_client(host)
        status = client.admin.command("serverStatus")
        data = {
            "uptime_seconds": status.get("uptime"),
            "connections": status.get("connections"),
            "opcounters": status.get("opcounters"),
            "mem_mb": status.get("mem"),
            "version": status.get("version"),
        }
        return ToolResult(tool="mongodb_server_status", success=True, output=data)
    except Exception as e:
        return ToolResult(tool="mongodb_server_status", success=False, output=None, error=str(e))


def execute_mongodb_list_databases(host: str = "localhost:27017") -> ToolResult:
    try:
        client = _get_mongo_client(host)
        dbs = client.list_database_names()
        data = []
        for db_name in dbs:
            stats = client[db_name].command("dbStats")
            data.append({
                "name": db_name,
                "size_mb": round(stats.get("dataSize", 0) / 1024 / 1024, 2),
                "collections": stats.get("collections", 0),
            })
        return ToolResult(tool="mongodb_list_databases", success=True, output=data)
    except Exception as e:
        return ToolResult(tool="mongodb_list_databases", success=False, output=None, error=str(e))


def execute_mongodb_current_operations(host: str = "localhost:27017") -> ToolResult:
    try:
        client = _get_mongo_client(host)
        ops = client.admin.command("currentOp")
        active = [
            {
                "opid": op.get("opid"),
                "op": op.get("op"),
                "ns": op.get("ns"),
                "secs_running": op.get("secs_running"),
                "desc": op.get("desc"),
            }
            for op in ops.get("inprog", [])
            if op.get("op") != "none"
        ]
        return ToolResult(tool="mongodb_current_operations", success=True, output=active)
    except Exception as e:
        return ToolResult(tool="mongodb_current_operations", success=False, output=None, error=str(e))


# --- Dispatcher ---------------------------------------------------------------

TOOL_EXECUTORS = {
    "docker_list_containers": execute_docker_list_containers,
    "docker_inspect_container": execute_docker_inspect_container,
    "docker_container_logs": execute_docker_container_logs,
    "docker_restart_container": execute_docker_restart_container,
    "docker_container_stats": execute_docker_container_stats,
    "mongodb_server_status": execute_mongodb_server_status,
    "mongodb_list_databases": execute_mongodb_list_databases,
    "mongodb_current_operations": execute_mongodb_current_operations,
}


def execute_tool(name: str, arguments: dict[str, Any]) -> ToolResult:
    """Execute a tool by name with the given arguments."""
    executor = TOOL_EXECUTORS.get(name)
    if not executor:
        return ToolResult(tool=name, success=False, output=None, error=f"Unknown tool: {name}")
    return executor(**arguments)
