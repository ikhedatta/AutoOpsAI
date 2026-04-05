import httpx
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

class OllamaConnectionError(Exception): pass
class OllamaModelNotFoundError(Exception): pass
class OllamaTimeoutError(Exception): pass

class OllamaClient:
    def __init__(self, base_url: str | None = None):
        import os
        self.base_url = base_url or os.getenv("OLLAMA_BASE", "http://localhost:11434")

    def health_check(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            return r.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            return False

    @retry(
        wait=wait_exponential(min=1, max=8),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(httpx.ConnectError)
    )
    def chat(self, model: str, messages: list, stream: bool = False) -> dict:
        try:
            r = httpx.post(
                f"{self.base_url}/api/chat",
                json={"model": model, "messages": messages, "stream": False},
                timeout=120
            )
            if r.status_code == 404:
                raise OllamaModelNotFoundError(f"Model '{model}' not found")
            r.raise_for_status()
            return r.json()
        except httpx.ConnectError:
            raise OllamaConnectionError(f"Cannot connect to Ollama at {self.base_url}. Is it running?")
        except httpx.TimeoutException:
            raise OllamaTimeoutError("Ollama request timed out after 120s")
