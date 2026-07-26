"""Local OpenAI-compatible LLM (Ollama, vLLM, etc.) — same contract as OpenAIProvider."""

from __future__ import annotations

from app.integrations.llm.openai_provider import OpenAIProvider


class LocalOpenAICompatibleProvider(OpenAIProvider):
    def __init__(
        self,
        *,
        base_url: str,
        model: str = "llama3.2",
        api_key: str = "not-needed",
    ) -> None:
        super().__init__(api_key=api_key, model=model, base_url=base_url)
