from app.integrations.llm.base import LLMProvider, TranscriptionProvider
from app.integrations.llm.openai_provider import OpenAIProvider, OpenAITranscriptionProvider

__all__ = [
    "LLMProvider",
    "TranscriptionProvider",
    "OpenAIProvider",
    "OpenAITranscriptionProvider",
    "build_llm_provider",
    "build_transcription_provider",
]


def __getattr__(name: str):
    if name in {"build_llm_provider", "build_transcription_provider"}:
        from app.integrations.llm.factory import (
            build_llm_provider,
            build_transcription_provider,
        )

        return {
            "build_llm_provider": build_llm_provider,
            "build_transcription_provider": build_transcription_provider,
        }[name]
    raise AttributeError(name)
