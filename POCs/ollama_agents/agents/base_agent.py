import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

@dataclass
class AgentResponse:
    content: str
    model: str
    agent_name: str
    duration_ms: float
    raw_response: dict

class BaseAgent(ABC):
    def __init__(self, client, model: str | None = None):
        import os
        self.client = client
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen3:4b")
        self.history: list = []
        self._max_history = 50  # Prevent unbounded growth

    @property
    @abstractmethod
    def system_prompt(self) -> str: ...

    @property
    @abstractmethod
    def name(self) -> str: ...

    def run(self, user_message: str, use_history: bool = False) -> AgentResponse:
        messages = [{"role": "system", "content": self.system_prompt}]
        if use_history:
            messages.extend(self.history)
        messages.append({"role": "user", "content": user_message})

        start = time.time()
        raw = self.client.chat(model=self.model, messages=messages)
        duration_ms = (time.time() - start) * 1000

        content = raw.get("message", {}).get("content", "")
        if use_history:
            self.history.append({"role": "user", "content": user_message})
            self.history.append({"role": "assistant", "content": content})
            # Trim history to prevent unbounded growth
            if len(self.history) > self._max_history:
                self.history = self.history[-self._max_history:]

        return AgentResponse(
            content=content,
            model=self.model,
            agent_name=self.name,
            duration_ms=duration_ms,
            raw_response=raw
        )

    def reset(self):
        self.history = []
