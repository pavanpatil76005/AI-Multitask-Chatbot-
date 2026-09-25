from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator


class AIProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Generate a text response for the supplied prompt."""

    @abstractmethod
    def stream_generate(self, prompt: str) -> Iterator[str]:
        """Yield streamed text chunks for the supplied prompt."""
