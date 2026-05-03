from __future__ import annotations

from pydantic import BaseModel, Field


class TimingEntry(BaseModel):
    segment_id: str = Field(..., description="target segment id")
    segmenter_version: str = Field(default="zh_clause_v1")
    chapter_audio: str = Field(..., description="chapter audio filename, e.g. Chapter_001.mp3")
    start_ms: int = Field(..., description="start time in milliseconds")
    end_ms: int = Field(..., description="end time in milliseconds")
    gap_after_ms: int = Field(
        default=0,
        description="silence gap after this segment in milliseconds",
    )
    start_sample: int | None = Field(
        default=None,
        description="start sample for precise reconstruction",
    )
    end_sample: int | None = Field(
        default=None,
        description="end sample for precise reconstruction",
    )
    sample_rate: int = Field(default=48000, description="sample rate for sample-based timing")


class AudioSpacing(BaseModel):
    clause_gap_ms: int = Field(default=120, description="gap between clauses within a sentence")
    sentence_gap_ms: int = Field(default=180, description="gap between sentences")
    paragraph_gap_ms: int = Field(default=350, description="gap between paragraphs")
    chapter_intro_silence_ms: int = Field(default=500, description="silence at chapter start")
    chapter_outro_silence_ms: int = Field(default=800, description="silence at chapter end")
