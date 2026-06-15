"""
Sentiment + emotion analysis. Uses VADER for a quick baseline and a small
Claude call for fine-grained emotion classification.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from app.core.logging import logger


Emotion = Literal[
    "joy", "sadness", "anger", "fear", "anxiety", "love",
    "surprise", "neutral", "frustration", "loneliness",
]


# Map emotion -> response tone
EMOTION_TO_TONE: dict[str, str] = {
    "joy": "playful",
    "sadness": "supportive",
    "anger": "grounding",
    "fear": "supportive",
    "anxiety": "grounding",
    "love": "warm",
    "surprise": "playful",
    "frustration": "challenging",
    "loneliness": "warm",
    "neutral": "neutral",
}


@dataclass
class SentimentResult:
    compound: float           # -1.0 to 1.0
    positive: float
    negative: float
    neutral: float
    emotion: Emotion
    tone: str


class SentimentAnalyzer:
    """Hybrid rule-based + LLM emotion detection."""

    def __init__(self) -> None:
        self._vader = SentimentIntensityAnalyzer()

    def vader(self, text: str) -> dict[str, float]:
        return self._vader.polarity_scores(text)

    def quick(self, text: str) -> SentimentResult:
        """Cheap, no-LLM path. Used for streaming / fallback."""
        scores = self.vader(text)
        compound = scores["compound"]
        emotion: Emotion = "neutral"
        if compound >= 0.5:
            emotion = "joy"
        elif compound <= -0.5:
            emotion = "sadness"
        elif scores["neg"] > 0.3:
            emotion = "frustration"
        elif scores["neu"] > 0.9:
            emotion = "neutral"
        return SentimentResult(
            compound=compound,
            positive=scores["pos"],
            negative=scores["neg"],
            neutral=scores["neu"],
            emotion=emotion,
            tone=EMOTION_TO_TONE.get(emotion, "neutral"),
        )

    async def deep(self, text: str) -> SentimentResult:
        """Claude-based fine-grained emotion detection (lazy-imported)."""
        from app.services.llm_service import llm_service  # avoid circular at import

        base = self.quick(text)
        try:
            raw = await llm_service.classify_emotion(text)
            data = json.loads(raw)
            emotion = data.get("emotion", base.emotion)
            if emotion not in EMOTION_TO_TONE:
                emotion = "neutral"
            return SentimentResult(
                compound=base.compound,
                positive=base.positive,
                negative=base.negative,
                neutral=base.neutral,
                emotion=emotion,  # type: ignore[arg-type]
                tone=EMOTION_TO_TONE.get(emotion, "neutral"),
            )
        except Exception as e:
            logger.warning(f"Deep emotion classification failed, using VADER: {e}")
            return base


sentiment_analyzer = SentimentAnalyzer()
