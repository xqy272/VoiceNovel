from __future__ import annotations

from pydantic import BaseModel, Field


class AudioTake(BaseModel):
    take_id: str = Field(..., description="unique take id")
    segment_id: str = Field(..., description="target segment id")
    path: str = Field(..., description="relative path to audio file")
    duration_ms: float = Field(default=0.0, description="audio duration in milliseconds")
    asr_score: float = Field(default=0.0, ge=0.0, le=1.0, description="asr verification score")
    loudness_ok: bool = Field(default=True, description="whether loudness is within range")
    selected: bool = Field(default=False, description="whether this is the selected take")
    engine: str = Field(default="", description="tts engine that produced this take")
    voice_id: str = Field(default="", description="voice id used")
