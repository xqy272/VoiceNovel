from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class JobStage(str, Enum):
    import_book = "import"
    text_adaptation = "text_adaptation"
    segmentation = "segmentation"
    cleaned_html = "cleaned_html"
    reading_plan = "reading_plan"
    voice_casting = "voice_casting"
    tts_render = "tts_render"
    asr_verify = "asr_verify"
    timing_build = "timing_build"
    packaging = "packaging"
    export = "export"


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    skipped = "skipped"
    stale = "stale"


class ExceptionSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class JobState(BaseModel):
    job_id: str = Field(..., description="unique job id")
    book_id: str = Field(default="", description="book this job operates on")
    generation_config_id: str = Field(default="", description="generation config snapshot id")
    run_id: str = Field(default="", description="run id for this generation run")
    memory_snapshot_id: str | None = Field(default=None, description="memory snapshot for this job")
    execution_mode: str = Field(default="balanced", description="economy or balanced")
    stage: JobStage = Field(..., description="current pipeline stage")
    unit_id: str = Field(..., description="chapter_id or segment_id")
    status: JobStatus = Field(default=JobStatus.pending)
    priority: str = Field(default="P2", description="P0-P4 priority")
    input_artifact_versions: list[str] = Field(default_factory=list)
    output_artifact_type: str = Field(default="", description="expected output artifact type")
    input_hash: str = Field(default="", description="hash of all inputs affecting this job")
    cache_key: str = Field(default="", description="cache key for deduplication")
    cache_buster: str | None = Field(default=None, description="explicit cache invalidation")
    artifact: str = Field(default="", description="path to output artifact")
    retry_count: int = Field(default=0)
