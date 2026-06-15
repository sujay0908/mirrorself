"""
Claude (Anthropic) wrapper for chat, fact extraction, and emotion classification.
All prompts assume the system message comes from `build_system_prompt` in prompt_service.
"""
from __future__ import annotations

import json
from typing import AsyncIterator, Optional

from anthropic import AsyncAnthropic

from app.core.config import settings
from app.core.logging import logger


class LLMService:
    def __init__(self) -> None:
        if not settings.ANTHROPIC_API_KEY:
            logger.warning("ANTHROPIC_API_KEY is not set; LLM calls will fail.")
        self._client: Optional[AsyncAnthropic] = None

    @property
    def client(self) -> AsyncAnthropic:
        if self._client is None:
            self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        return self._client

    async def chat(
        self,
        system: str,
        messages: list[dict],
        max_tokens: Optional[int] = None,
        temperature: float = 0.8,
    ) -> str:
        """Plain non-streaming chat completion."""
        try:
            response = await self.client.messages.create(
                model=settings.CLAUDE_MODEL,
                system=system,
                messages=messages,
                max_tokens=max_tokens or settings.CLAUDE_MAX_TOKENS,
                temperature=temperature,
            )
            parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
            return "".join(parts).strip()
        except Exception as e:
            logger.error(f"Claude chat failed: {e}")
            raise

    async def stream(
        self,
        system: str,
        messages: list[dict],
        max_tokens: Optional[int] = None,
        temperature: float = 0.8,
    ) -> AsyncIterator[str]:
        async with self.client.messages.stream(
            model=settings.CLAUDE_MODEL,
            system=system,
            messages=messages,
            max_tokens=max_tokens or settings.CLAUDE_MAX_TOKENS,
            temperature=temperature,
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    yield text

    async def classify_emotion(self, text: str) -> str:
        """Returns a JSON string with `emotion` and `intensity`."""
        prompt = (
            "You are an emotion classifier. Read the user's message and respond with ONLY "
            "a JSON object of the form {\"emotion\": <one of: joy, sadness, anger, fear, "
            "anxiety, love, surprise, frustration, loneliness, neutral>, \"intensity\": <0-1>}.\n\n"
            f"User message: {text}"
        )
        out = await self.chat(
            system="You output only valid JSON, no prose, no markdown fences.",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=64,
            temperature=0,
        )
        return out

    async def extract_facts(self, user_message: str, assistant_message: str) -> list[dict]:
        """Extract durable facts from the latest exchange. Returns list of {category, content}."""
        prompt = (
            "Extract durable facts about the user from this exchange. Output ONLY a JSON array; "
            "each item: {\"category\": one of [personal, preference, relationship, work, dream, "
            "fear, value, goal, hobby], \"content\": <short factual string>}. If there are no "
            "durable facts, output []. Do not include transient emotions. Max 5 items.\n\n"
            f"User: {user_message}\n\nAssistant: {assistant_message}"
        )
        out = await self.chat(
            system="You output only valid JSON arrays, no prose, no markdown fences.",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0,
        )
        try:
            data = json.loads(out)
            if not isinstance(data, list):
                return []
            return [d for d in data if isinstance(d, dict) and "content" in d]
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse fact extraction: {out}")
            return []


llm_service = LLMService()
