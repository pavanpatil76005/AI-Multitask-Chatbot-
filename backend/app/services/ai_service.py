from __future__ import annotations

from collections.abc import Iterator
import logging

from app.ai.gemini_provider import GeminiProvider
from app.models.message import Message


SYSTEM_PROMPT = """You are AI Multitask, a general-purpose AI assistant.
Answer the user's questions clearly and accurately.
Use previous messages in the current conversation when relevant.
You can help with programming, mathematics, science, technology, education,
explanations, writing, summarization, brainstorming, interview preparation,
data analysis, general knowledge, and problem solving.
If a request is unclear, ask for clarification.
"""

logger = logging.getLogger(__name__)


def log_ai_error(exc: Exception) -> None:
    logger.error("AI failure: type=%s HTTP=%s", type(exc).__name__, getattr(exc, "code", None))


def build_chat_prompt(messages: list[Message]) -> str:
    recent_messages = [m for m in messages if m.role == "user" or m.status == "completed"][-20:]
    lines = [SYSTEM_PROMPT, "",]

    for message in recent_messages:
        role_name = "User" if message.role == "user" else "Assistant"
        lines.append(f"{role_name}: {message.content.strip()}")

    lines.append("Assistant:")
    return "\n".join(lines)


def generate_chat_response(messages: list[Message]) -> str:
    try:
        return GeminiProvider().generate(build_chat_prompt(messages))
    except Exception as exc:
        log_ai_error(exc)
        raise


def generate_chat_response_stream(messages: list[Message]) -> Iterator[str]:
    try:
        yield from GeminiProvider().stream_generate(build_chat_prompt(messages))
    except Exception as exc:
        log_ai_error(exc)
        raise
