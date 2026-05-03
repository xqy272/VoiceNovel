from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ExceptionType(str, Enum):
    low_confidence_speaker = "low_confidence_speaker"
    large_text_diff = "large_text_diff"
    asr_mismatch = "asr_mismatch"
    tts_timeout = "tts_timeout"
    audio_too_short = "audio_too_short"
    voice_missing = "voice_missing"
    cache_stale = "cache_stale"
    timing_missing = "timing_missing"
    schema_error = "schema_error"
    invariant_error = "invariant_error"


class ExceptionSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class ExceptionStatus(str, Enum):
    open = "open"
    auto_resolving = "auto_resolving"
    auto_resolved = "auto_resolved"
    user_resolved = "user_resolved"
    deferred = "deferred"


class ExceptionEntry(BaseModel):
    exception_id: str = Field(..., description="unique exception id")
    book_id: str = Field(..., description="book id")
    exception_type: ExceptionType = Field(..., description="type of exception")
    severity: ExceptionSeverity = Field(default=ExceptionSeverity.medium)
    status: ExceptionStatus = Field(default=ExceptionStatus.open)
    unit_id: str = Field(..., description="chapter_id or segment_id")
    stage: str = Field(..., description="pipeline stage where exception occurred")
    message: str = Field(default="", description="human-readable description")
    details: dict = Field(default_factory=dict, description="structured details")
    retry_count: int = Field(default=0, description="number of auto-retry attempts")
    created_at: str = Field(default="", description="ISO 8601 timestamp")
    resolved_at: str | None = Field(default=None)
