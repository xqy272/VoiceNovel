from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class AdaptationCategory(str, Enum):
    basic_cleanup = "basic_cleanup"
    punctuation = "punctuation"
    typo = "typo"
    de_obfuscation = "de_obfuscation"
    tts_normalization = "tts_normalization"
    terminology = "terminology"
    dialogue_fix = "dialogue_fix"


class AdaptationScope(str, Enum):
    display_and_tts = "display_and_tts"
    tts_only = "tts_only"
    display_only = "display_only"
    suggest_only = "suggest_only"


class TextAdaptationOperation(BaseModel):
    op_id: str = Field(..., description="unique operation id")
    segment_id: str = Field(..., description="target segment")
    original: str = Field(..., description="original text before operation")
    normalized: str = Field(..., description="text after operation")
    category: AdaptationCategory = Field(..., description="type of adaptation")
    scope: AdaptationScope = Field(..., description="where this operation applies")
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="confidence of this operation",
    )
    risk: str = Field(default="low", description="risk level: low, medium, high")
    evidence: list[str] = Field(default_factory=list, description="evidence for this operation")
    source: str = Field(default="rule", description="source: rule, llm_context, user")
