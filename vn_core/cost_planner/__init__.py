"""Cost Planner: token/audio duration/provider cost estimation and tracking.

Provides pre-run estimates and post-run actuals for LLM token usage and TTS
audio duration, with configurable provider rate cards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Provider rate cards (USD per unit)
# ---------------------------------------------------------------------------

# LLM rates: USD per 1M input tokens / 1M output tokens
LLM_RATES: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input_per_1m": 0.15, "output_per_1m": 0.60},
    "gpt-4o": {"input_per_1m": 2.50, "output_per_1m": 10.00},
    "claude-haiku": {"input_per_1m": 0.25, "output_per_1m": 1.25},
    "claude-sonnet": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "deepseek-chat": {"input_per_1m": 0.27, "output_per_1m": 1.10},
    "mock": {"input_per_1m": 0.0, "output_per_1m": 0.0},
}

# TTS rates: USD per 1M characters
TTS_RATES: dict[str, float] = {
    "edge_tts": 0.0,          # free
    "mock": 0.0,              # free
    "cosyvoice": 0.0,         # self-hosted Docker
    "openai_tts": 15.00,      # ~$15/1M chars
    "azure_tts": 15.00,       # ~$15/1M chars
}

# Fallback: average characters per second for cost estimation from duration
EST_CHARS_PER_SECOND = 5.0   # rough average for Chinese TTS


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class LLMCostLine:
    model: str
    backend: str = ""
    task: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cached: bool = False


@dataclass
class TTSCostLine:
    engine: str
    chars_synthesized: int = 0
    duration_ms: int = 0
    cost_usd: float = 0.0


@dataclass
class CostEstimate:
    """Pre-run estimate or post-run actual cost breakdown."""

    book_id: str = ""
    chapter_id: str = ""
    estimate_type: Literal["pre_run", "post_run"] = "pre_run"

    # LLM
    llm_input_tokens_est: int = 0
    llm_output_tokens_est: int = 0
    llm_model: str = "mock"
    llm_cost_usd: float = 0.0
    llm_items: list[LLMCostLine] = field(default_factory=list)

    # TTS
    tts_engine: str = "mock"
    tts_total_chars: int = 0
    tts_total_duration_ms: int = 0
    tts_cost_usd: float = 0.0
    tts_items: list[TTSCostLine] = field(default_factory=list)

    # Totals
    @property
    def total_cost_usd(self) -> float:
        return round(self.llm_cost_usd + self.tts_cost_usd, 6)

    @property
    def total_duration_minutes(self) -> float:
        return round(self.tts_total_duration_ms / 60000, 2)


# ---------------------------------------------------------------------------
# Cost Planner
# ---------------------------------------------------------------------------

class CostPlanner:
    """Estimate and track costs for LLM and TTS usage."""

    def __init__(
        self,
        llm_rates: dict[str, dict[str, float]] | None = None,
        tts_rates: dict[str, float] | None = None,
    ):
        self.llm_rates = llm_rates or LLM_RATES
        self.tts_rates = tts_rates or TTS_RATES

    # --- LLM cost estimation ---

    def estimate_llm_cost(
        self,
        model: str,
        task: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        segment_count: int = 0,
        chapter_count: int = 1,
    ) -> LLMCostLine:
        """Estimate LLM cost for a pipeline task.

        If input_tokens/output_tokens are 0, uses heuristics based on segment
        and chapter counts.
        """
        if input_tokens == 0:
            input_tokens = self._estimate_input_tokens(task, segment_count, chapter_count)
        if output_tokens == 0:
            output_tokens = self._estimate_output_tokens(task, segment_count)

        rates = self.llm_rates.get(model, self.llm_rates["mock"])
        cost = (
            input_tokens / 1_000_000 * rates["input_per_1m"]
            + output_tokens / 1_000_000 * rates["output_per_1m"]
        )

        return LLMCostLine(
            model=model,
            task=task,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
        )

    def estimate_llm_cost_from_response(
        self,
        model: str,
        task: str,
        usage: dict,
        cached: bool = False,
    ) -> LLMCostLine:
        """Compute actual LLM cost from a response usage dict."""
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        rates = self.llm_rates.get(model, self.llm_rates["mock"])
        cost = (
            input_tokens / 1_000_000 * rates["input_per_1m"]
            + output_tokens / 1_000_000 * rates["output_per_1m"]
        )

        if cached:
            cost = 0.0

        return LLMCostLine(
            model=model,
            task=task,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
            cached=cached,
        )

    # --- TTS cost estimation ---

    def estimate_tts_cost(
        self,
        engine: str,
        total_chars: int = 0,
        total_duration_ms: int = 0,
        segment_count: int = 0,
        avg_chars_per_segment: int = 60,
    ) -> TTSCostLine:
        """Estimate TTS cost for a chapter or segment batch."""
        if total_chars == 0 and segment_count > 0:
            total_chars = segment_count * avg_chars_per_segment
        if total_duration_ms == 0 and segment_count > 0:
            # rough estimate: Chinese TTS ~5 chars/sec
            total_duration_ms = int(
                segment_count * avg_chars_per_segment / EST_CHARS_PER_SECOND * 1000
            )

        rate = self.tts_rates.get(engine, 0.0)
        cost = total_chars / 1_000_000 * rate

        return TTSCostLine(
            engine=engine,
            chars_synthesized=total_chars,
            duration_ms=total_duration_ms,
            cost_usd=round(cost, 6),
        )

    # --- Full pipeline estimate ---

    def estimate_chapter(
        self,
        book_id: str,
        chapter_id: str,
        segment_count: int,
        llm_model: str = "mock",
        tts_engine: str = "mock",
        reading_profile: str = "enhanced",
    ) -> CostEstimate:
        """Pre-run cost estimate for baking a single chapter."""
        est = CostEstimate(
            book_id=book_id,
            chapter_id=chapter_id,
            estimate_type="pre_run",
            llm_model=llm_model,
            tts_engine=tts_engine,
        )

        if segment_count <= 0:
            return est  # zero-cost for empty chapters

        # LLM tasks: scan chapter, plan chapter (speaker attribution)
        scan_line = self.estimate_llm_cost(
            llm_model, "character_extraction", segment_count=segment_count,
        )
        plan_line = self.estimate_llm_cost(
            llm_model, "speaker_attribution", segment_count=segment_count,
        )
        est.llm_items = [scan_line, plan_line]
        est.llm_input_tokens_est = sum(it.input_tokens for it in est.llm_items)
        est.llm_output_tokens_est = sum(it.output_tokens for it in est.llm_items)
        est.llm_cost_usd = sum(it.cost_usd for it in est.llm_items)

        # If faithful mode, skip most LLM calls
        if reading_profile == "faithful":
            est.llm_input_tokens_est = 0
            est.llm_output_tokens_est = 0
            est.llm_cost_usd = 0.0
            est.llm_items = []

        # TTS
        tts_line = self.estimate_tts_cost(tts_engine, segment_count=segment_count)
        est.tts_items = [tts_line]
        est.tts_total_chars = tts_line.chars_synthesized
        est.tts_total_duration_ms = tts_line.duration_ms
        est.tts_cost_usd = tts_line.cost_usd

        return est

    def estimate_book(
        self,
        book_id: str,
        chapter_ids: list[str],
        total_segments: int,
        llm_model: str = "mock",
        tts_engine: str = "mock",
        reading_profile: str = "enhanced",
    ) -> CostEstimate:
        """Pre-run cost estimate for baking an entire book."""
        chapters = len(chapter_ids)
        segs_per_chapter = max(total_segments // chapters, 1) if chapters else total_segments

        # Sum per-chapter estimates
        total = CostEstimate(
            book_id=book_id,
            chapter_id="all",
            estimate_type="pre_run",
            llm_model=llm_model,
            tts_engine=tts_engine,
        )

        for ch_id in chapter_ids:
            ch_est = self.estimate_chapter(
                book_id, ch_id, segs_per_chapter, llm_model, tts_engine, reading_profile,
            )
            total.llm_items.extend(ch_est.llm_items)
            total.tts_items.extend(ch_est.tts_items)

        total.llm_input_tokens_est = sum(it.input_tokens for it in total.llm_items)
        total.llm_output_tokens_est = sum(it.output_tokens for it in total.llm_items)
        total.llm_cost_usd = round(sum(it.cost_usd for it in total.llm_items), 6)
        total.tts_total_chars = sum(it.chars_synthesized for it in total.tts_items)
        total.tts_total_duration_ms = sum(it.duration_ms for it in total.tts_items)
        total.tts_cost_usd = round(sum(it.cost_usd for it in total.tts_items), 6)

        return total

    # --- Heuristic token estimators ---

    @staticmethod
    def _estimate_input_tokens(task: str, segment_count: int, chapter_count: int = 1) -> int:
        base = {
            "character_extraction": 500 + chapter_count * 1200,
            "speaker_attribution": 300 + segment_count * 150,
            "scene_summary": 400 + chapter_count * 800,
            "text_adaptation": 200 + segment_count * 100,
        }
        return base.get(task, 500 + segment_count * 100)

    @staticmethod
    def _estimate_output_tokens(task: str, segment_count: int) -> int:
        base = {
            "character_extraction": 200 + segment_count * 30,
            "speaker_attribution": 100 + segment_count * 80,
            "scene_summary": 100 + segment_count * 20,
            "text_adaptation": 50 + segment_count * 40,
        }
        return base.get(task, 100 + segment_count * 50)
