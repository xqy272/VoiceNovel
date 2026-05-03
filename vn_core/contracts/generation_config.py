from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ReadingProfile = Literal["faithful", "enhanced"]
ExecutionMode = Literal["economy", "balanced"]


class GenerationConfig(BaseModel):
    generation_config_id: str = Field(default="default")
    book_id: str = Field(...)
    reading_profile: ReadingProfile = Field(default="enhanced")
    execution_mode: ExecutionMode = Field(default="balanced")
    tts_engine: str = Field(default="mock")
    cache_buster: str | None = Field(default=None)
    metadata: dict = Field(default_factory=dict)
