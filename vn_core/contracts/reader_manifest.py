from __future__ import annotations

from pydantic import BaseModel, Field


class TimingProfile(BaseModel):
    audio_codec: str = Field(default="mp3", description="audio codec: mp3, m4a, opus, wav")
    timing_unit: str = Field(default="ms", description="timing unit: ms")
    seek_precision: str = Field(
        default="approximate",
        description="seek precision: approximate, sample_accurate",
    )
    encoder_delay_ms: int = Field(default=0, description="encoder delay in ms")


class ReaderPackageManifest(BaseModel):
    package_version: str = Field(default="0.1")
    book_id: str = Field(..., description="book identifier")
    title: str = Field(default="", description="book title")
    text_format: str = Field(
        default="cleaned-html",
        description="text format: cleaned-html, cleaned-epub",
    )
    highlight_granularity: str = Field(
        default="sentence_clause",
        description="highlight granularity",
    )
    segmenter_version: str = Field(default="zh_clause_v1")
    audio_codec: str = Field(default="mp3")
    timing_unit: str = Field(default="ms")
    seek_precision: str = Field(default="approximate")
    segments: str = Field(default="segments.jsonl", description="segments file path")
    timing: str = Field(default="timing.json", description="timing file path")
    audio_manifest: str = Field(
        default="audio_manifest.json",
        description="audio manifest file path",
    )
    voices: str = Field(default="voices.json", description="voices file path")


class ReaderManifest(BaseModel):
    package_version: str = Field(default="0.1")
    book_id: str = Field(...)
    title: str = Field(default="")
    text_format: str = Field(default="cleaned-html")
    highlight_granularity: str = Field(default="sentence_clause")
    segmenter_version: str = Field(default="zh_clause_v1")
    audio_codec: str = Field(default="mp3")
    timing_unit: str = Field(default="ms")
    seek_precision: str = Field(default="approximate")
    encoder_delay_ms: int = Field(default=0)
    segments: str = Field(default="segments.jsonl")
    timing: str = Field(default="timing.json")
    audio_manifest: str = Field(default="audio_manifest.json")
    voices: str = Field(default="voices.json")
