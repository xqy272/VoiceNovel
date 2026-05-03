from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryPatch(BaseModel):
    book_id: str = Field(..., description="book id")
    base_snapshot_id: str = Field(..., description="snapshot this patch is based on")
    memory_type: str = Field(
        ...,
        description="character, alias, glossary, pronunciation, decision, scene_snapshot",
    )
    action: str = Field(..., description="upsert, delete, merge")
    key: str = Field(..., description="unique key within the memory type")
    value: dict = Field(..., description="new value or merge fragment")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_segments: list[str] = Field(default_factory=list)
    created_by: str = Field(default="", description="service or process that created this patch")
