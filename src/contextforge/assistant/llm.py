import httpx


class LLMError(Exception):
    pass


class OpenAICompatibleClient:
    """Minimal chat-completions client. Works with Ollama (`http://host:11434/v1`) and any
    OpenAI-compatible server."""

    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def complete(self, system: str, user: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"unexpected LLM response format: {exc}") from exc
