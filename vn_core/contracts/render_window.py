"""RenderWindow — tracks a partial render for cold-start buffer playback."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class WindowStatus(str, Enum):
    pending = "pending"
    rendering = "rendering"
    playable = "playable"
    failed = "failed"


class RenderWindow(BaseModel):
    book_id: str = Field(..., description="book identifier")
    chapter_id: str = Field(..., description="chapter identifier")
    window_id: str = Field(..., description="stable window id, e.g. ch001_buffer_000_030")
    start_segment_id: str = Field(default="", description="first segment id")
    end_segment_id: str = Field(default="", description="last segment id")
    segment_ids: list[str] = Field(
        default_factory=list,
        description="segment ids covered by this window",
    )
    target_count: int = Field(default=0, description="requested segment count")
    status: WindowStatus = Field(default=WindowStatus.pending)
    package_dir: str = Field(default="", description="file system path")
    audio_manifest_path: str = Field(default="")
    timing_path: str = Field(default="")
    reader_package_artifact_version_id: str = Field(
        default="",
        description="artifact version for this window_package",
    )
    created_at: str = Field(default="")
    updated_at: str = Field(default="")
    error: str = Field(default="")
