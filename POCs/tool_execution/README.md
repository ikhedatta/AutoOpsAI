# POC 3: Tool Execution (Docker + MongoDB)

Demonstrates an Ollama-powered agent that autonomously decides which tools to call based on the user's request, executes them, and reasons about the results.

## Architecture

```
User Request → Ollama (with tool schemas) → Tool Call Decision
                    ↕                            ↓
              Final Response ← Tool Results ← Execute Tool
                    ↑                            ↓
              (loop until done)          Docker API / MongoDB
```

## Available Tools

### Docker Tools
| Tool | Description |
|------|-------------|
| `docker_list_containers` | List all containers with status |
| `docker_inspect_container` | Detailed container info |
| `docker_container_logs` | Retrieve recent logs |
| `docker_restart_container` | Restart a container |
| `docker_container_stats` | CPU/memory stats |

### MongoDB Tools
| Tool | Description |
|------|-------------|
| `mongodb_server_status` | Server health and metrics |
| `mongodb_list_databases` | List databases with sizes |
| `mongodb_current_operations` | Running operations |

## Quick Start

```bash
# Ensure Docker is running and Ollama has qwen3:4b
ollama pull qwen3:4b

# Run the demo
uv run python -m POCs.tool_execution.demo
```

## How It Works

1. User message + tool schemas are sent to Ollama via `/api/chat`
2. Model returns `tool_calls` with function name and arguments
3. Agent executes the tool and feeds results back to the model
4. Loop continues until the model produces a final text response (no more tool calls)

This is the same tool-calling pattern used by OpenAI, Anthropic, and other providers — Ollama supports it natively.
