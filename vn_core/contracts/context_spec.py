from __future__ import annotations

from pydantic import BaseModel, Field


class ContextSpec(BaseModel):
    task: str = Field(
        ...,
        description=(
            "task type: speaker_attribution, text_adaptation, voice_casting, "
            "pronunciation, qa_review"
        ),
    )
    segment_ids: list[str] = Field(default_factory=list, description="target segments")
    chapter_id: str | None = Field(default=None, description="target chapter")
    scene_state: bool = Field(default=False, description="whether to include scene state")
    active_characters: dict = Field(
        default_factory=dict,
        description="top_k or specific character ids",
    )
    recent_dialogue: dict = Field(
        default_factory=dict,
        description="segments_before, segments_after",
    )
    aliases: str | None = Field(
        default=None,
        description="for_active_characters, all, or specific ids",
    )
    glossary: bool = Field(default=False, description="whether to include book glossary")
    pronunciation: bool = Field(
        default=False,
        description="whether to include pronunciation overrides",
    )
    prior_decisions: bool = Field(
        default=False,
        description="whether to include prior reading decisions",
    )
    locked_items: bool = Field(default=False, description="whether to include user-locked items")
    problem_patterns: list[str] = Field(
        default_factory=list,
        description="detected problem patterns",
    )
