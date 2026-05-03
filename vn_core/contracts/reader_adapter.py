from __future__ import annotations

from pydantic import BaseModel, Field


class ReaderAdapterRequest(BaseModel):
    book_id: str = Field(..., description="book identifier")
    chapter_id: str | None = Field(default=None, description="current chapter, None if not started")
    position_segment_id: str | None = Field(default=None, description="current segment for resume")
    position_time_ms: int | None = Field(default=None, description="current playback time in ms")
    action: str = Field(
        default="get_status",
        description="get_status, get_chapter, start_playback, report_progress",
    )
    capabilities: list[str] = Field(
        default_factory=list,
        description="reader capabilities: highlight, audio_stream, offline",
    )


class ReaderAdapterResponse(BaseModel):
    book_id: str = Field(...)
    status: str = Field(..., description="idle, processing, ready, playing, error")
    current_chapter: str | None = Field(default=None)
    available_chapters: list[str] = Field(default_factory=list)
    prefetch_status: dict = Field(
        default_factory=dict,
        description="chapter -> ready/rendering/failed",
    )
    manifest_url: str | None = Field(default=None, description="URL to Reader Package manifest")
    chapter_content_url: str | None = Field(default=None, description="URL to chapter cleaned HTML")
    chapter_audio_url: str | None = Field(default=None, description="URL to chapter audio")
    chapter_timing_url: str | None = Field(default=None, description="URL to chapter timing.json")
    error_message: str | None = Field(default=None)
