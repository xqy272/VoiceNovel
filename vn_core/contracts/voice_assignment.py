from __future__ import annotations

from pydantic import BaseModel, Field


class VoiceAssignment(BaseModel):
    character_id: str = Field(..., description="character id from book model")
    voice_id: str = Field(..., description="assigned voice id from voice registry")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    user_locked: bool = Field(
        default=False,
        description="whether user explicitly locked this assignment",
    )
    source: str = Field(default="auto", description="auto, user, fallback")
