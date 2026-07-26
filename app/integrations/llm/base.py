from __future__ import annotations

from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.domain.models import CompletionRequest, CompletionResult, StructuredRequest

T = TypeVar("T", bound=BaseModel)


class LLMProvider(Protocol):
    async def complete(self, req: CompletionRequest) -> CompletionResult: ...

    async def structured(self, req: StructuredRequest, schema: type[T]) -> T: ...


class TranscriptionProvider(Protocol):
    async def transcribe(self, audio_path: Path, language: str) -> str: ...
