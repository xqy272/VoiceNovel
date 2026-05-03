from __future__ import annotations

from pydantic import BaseModel, Field


class ProvenanceEntry(BaseModel):
    unit_id: str = Field(..., description="chapter_id or segment_id")
    stage: str = Field(..., description="pipeline stage that produced this artifact")
    generation_config_id: str = Field(default="", description="generation config snapshot id")
    run_id: str = Field(default="", description="run id for this generation run")
    artifact_version_id: str = Field(default="", description="specific artifact version id")
    llm_model: str = Field(default="", description="llm model used, if any")
    prompt_version: str = Field(default="", description="prompt version used")
    input_hash: str = Field(default="", description="hash of input data")
    output_hash: str = Field(default="", description="hash of output data")
    cache_key: str = Field(default="", description="cache key for this artifact")
    cache_buster: str | None = Field(default=None, description="explicit cache invalidation")
    reading_profile: str = Field(
        default="enhanced",
        description="faithful, enhanced, dramatic-lite",
    )
    created_at: str = Field(default="", description="ISO 8601 timestamp")
