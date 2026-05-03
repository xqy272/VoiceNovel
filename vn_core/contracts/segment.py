from __future__ import annotations

from pydantic import BaseModel, Field


class Segment(BaseModel):
    segment_id: str = Field(..., description="chapter_id + paragraph_id + segment_index")
    segmenter_version: str = Field(
        default="zh_clause_v1",
        description="version of segmenter that produced this segment",
    )
    paragraph_id: str = Field(..., description="parent paragraph id")
    source_href: str = Field(default="", description="original EPUB/TXT source location")
    source_order: int = Field(..., description="order within the paragraph")
    source_dom_hint: str = Field(
        default="", description="DOM element hint from source (p, h1, etc.)",
    )
    text: str = Field(..., description="cleaned text for display and default TTS")
    quote_depth: int = Field(default=0, description="nesting depth of quotation marks")
    is_dialogue_candidate: bool = Field(
        default=False,
        description="whether this segment might be dialogue",
    )
    boundary_reason: str = Field(default="", description="why the segmenter split here")
