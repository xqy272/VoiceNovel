from __future__ import annotations

from pydantic import BaseModel, Field


class ReadingStyle(BaseModel):
    emotion: str = Field(
        default="neutral",
        description=(
            "emotion tag: neutral, happy, sad, angry, fearful, restrained, "
            "excited, calm"
        ),
    )
    intensity: float = Field(default=0.0, ge=0.0, le=1.0, description="emotion intensity")
    prosody_hint: str = Field(
        default="normal_pause",
        description="semantic pause hint: short_pause, normal_pause, long_pause",
    )


class Enhancements(BaseModel):
    sfx: str | None = Field(default=None, description="sound effect id or null")
    bgm: str | None = Field(default=None, description="background music id or null")


class VoiceConstraints(BaseModel):
    gender_style: str | None = Field(default=None, description="male, female, neutral")
    age_range: str | None = Field(default=None, description="child, young_adult, adult, senior")
    tone: list[str] = Field(
        default_factory=list,
        description="tone tags: cold, warm, aggressive, calm, etc.",
    )


class ReadingPlanEntry(BaseModel):
    segment_id: str = Field(..., description="target segment id")
    segmenter_version: str = Field(default="zh_clause_v1")
    source_href: str = Field(default="")
    source_order: int = Field(default=0, description="original paragraph order in source")
    text: str = Field(..., description="segment text")
    speaker_candidate: str | None = Field(default=None, description="raw speaker name from text")
    speaker_id: str = Field(default="char_narrator", description="resolved character id")
    speaker_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reading_style: ReadingStyle = Field(default_factory=ReadingStyle)
    enhancements: Enhancements = Field(default_factory=Enhancements)
    voice_constraints: VoiceConstraints = Field(default_factory=VoiceConstraints)
    evidence: list[str] = Field(
        default_factory=list,
        description="evidence for speaker attribution",
    )
    fallback_policy: str = Field(
        default="use_narrator",
        description="fallback policy when confidence is low",
    )
