from __future__ import annotations

from pydantic import BaseModel, Field


class ContextCapsule(BaseModel):
    task: str = Field(..., description="task type this capsule was built for")
    segment_ids: list[str] = Field(default_factory=list)
    chapter_id: str | None = Field(default=None)
    memory_snapshot_id: str | None = Field(default=None)

    target_segments: list[dict] = Field(
        default_factory=list,
        description="full segment data for target",
    )
    left_context: str = Field(default="", description="text context before target")
    right_context: str = Field(default="", description="text context after target")

    active_characters: list[dict] = Field(default_factory=list)
    recent_dialogue_state: dict = Field(default_factory=dict)
    scene_summary: str = Field(default="")
    problem_patterns: list[str] = Field(default_factory=list)

    glossary_terms: list[dict] = Field(default_factory=list)
    pronunciation_overrides: list[dict] = Field(default_factory=list)
    aliases: list[dict] = Field(default_factory=list)
    prior_decisions: list[dict] = Field(default_factory=list)
    locked_items: list[dict] = Field(default_factory=list)
