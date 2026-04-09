"""Trace the exact chat_with_tools flow to find where it fails."""
import asyncio
import json
import logging

logging.basicConfig(level=logging.DEBUG, format="%(name)s | %(levelname)s | %(message)s")
logger = logging.getLogger("trace")

async def main():
    from agent.config import get_settings
    from agent.llm.github_client import GitHubLLMClient
    from agent.llm.tools import get_ollama_tool_schemas
    from agent.llm.prompts import chat_prompt_with_tools
    from agent.llm.tool_executor import ToolExecutor
    from agent.collector.prometheus_client import PrometheusClient
    from agent.collector.loki_client import LokiClient
    from agent.collector.grafana_client import GrafanaClient

    settings = get_settings()
    llm = GitHubLLMClient(settings)

    # Check availability
    ok = await llm.is_available()
    print(f"\n1. LLM available: {ok}")

    # Build tool schemas
    schemas = get_ollama_tool_schemas()
    print(f"2. Tool schemas count: {len(schemas)}")
    print(f"   Tool names: {[s['function']['name'] for s in schemas]}")

    # Build messages (same as routes_chat.py does)
    messages = chat_prompt_with_tools(
        question="are there any errors logged recently",
        system_state={},
        incident_context=None,
        history=None,
    )
    print(f"3. Messages count: {len(messages)}")
    print(f"   System prompt (first 300 chars): {messages[0]['content'][:300]}")

    # Step 4: Call _chat_with_tools_sync directly to see the raw response
    print("\n4. Calling _chat_with_tools_sync...")
    try:
        msg = await asyncio.to_thread(llm._chat_with_tools_sync, messages, schemas)
        print(f"   Response keys: {list(msg.keys())}")
        print(f"   Content: {msg.get('content', '')[:200]}")
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            print(f"   Tool calls: {len(tool_calls)}")
            for tc in tool_calls:
                func = tc.get("function", tc)
                print(f"     -> {func.get('name')}: {json.dumps(func.get('arguments', {}))[:200]}")
        else:
            print("   NO TOOL CALLS — LLM chose not to call any tools!")
    except Exception as e:
        print(f"   EXCEPTION: {type(e).__name__}: {e}")

    # Step 5: Now test the full chat_with_tools flow
    print("\n5. Full chat_with_tools (with real tool executor)...")
    prom = PrometheusClient(settings.prometheus_url)
    loki = LokiClient(settings.loki_url)
    grafana = GrafanaClient(settings.grafana_url, settings.grafana_user, settings.grafana_password)

    executor = ToolExecutor(prometheus=prom, loki=loki, grafana=grafana)

    try:
        response = await llm.chat_with_tools(
            question="are there any errors logged recently",
            system_state={},
            incident_context=None,
            tool_executor=executor,
            max_iterations=5,
        )
        print(f"   Response ({len(response)} chars): {response[:500]}")
    except Exception as e:
        print(f"   EXCEPTION: {type(e).__name__}: {e}")

    await prom.close()
    await loki.close()
    await grafana.close()


asyncio.run(main())
