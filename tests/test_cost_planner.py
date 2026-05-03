"""Cost Planner tests: estimation accuracy, edge cases, and rate card lookups."""

import pytest

from vn_core.cost_planner import (
    LLM_RATES,
    TTS_RATES,
    CostEstimate,
    CostPlanner,
)


class TestCostPlanner:
    @pytest.fixture
    def planner(self):
        return CostPlanner()

    # --- LLM estimation ---

    def test_estimate_llm_cost_mock_is_zero(self, planner):
        line = planner.estimate_llm_cost("mock", "speaker_attribution", segment_count=100)
        assert line.cost_usd == 0.0

    def test_estimate_llm_cost_gpt4o_mini(self, planner):
        line = planner.estimate_llm_cost(
            "gpt-4o-mini", "speaker_attribution",
            input_tokens=1000, output_tokens=500,
        )
        expected = 1000 / 1_000_000 * 0.15 + 500 / 1_000_000 * 0.60
        assert line.cost_usd == pytest.approx(expected, rel=1e-6)
        assert line.model == "gpt-4o-mini"

    def test_estimate_llm_cost_with_heuristics(self, planner):
        line = planner.estimate_llm_cost(
            "gpt-4o-mini", "character_extraction", segment_count=50, chapter_count=2,
        )
        assert line.input_tokens > 0
        assert line.output_tokens > 0
        assert line.cost_usd >= 0.0

    def test_estimate_llm_cost_from_response(self, planner):
        usage = {"prompt_tokens": 2000, "completion_tokens": 800}
        line = planner.estimate_llm_cost_from_response(
            "gpt-4o-mini", "speaker_attribution", usage,
        )
        assert line.input_tokens == 2000
        assert line.output_tokens == 800
        assert line.cost_usd > 0.0

    def test_estimate_llm_cost_cached_is_zero(self, planner):
        usage = {"prompt_tokens": 2000, "completion_tokens": 800}
        line = planner.estimate_llm_cost_from_response(
            "gpt-4o", "speaker_attribution", usage, cached=True,
        )
        assert line.cost_usd == 0.0

    def test_unknown_model_falls_back_to_mock_rates(self, planner):
        line = planner.estimate_llm_cost(
            "nonexistent-model", "speaker_attribution", segment_count=10,
        )
        assert line.cost_usd == 0.0  # mock rates = $0

    # --- TTS estimation ---

    def test_estimate_tts_cost_mock_is_zero(self, planner):
        line = planner.estimate_tts_cost("mock", segment_count=100)
        assert line.cost_usd == 0.0

    def test_estimate_tts_cost_edge_tts_is_zero(self, planner):
        line = planner.estimate_tts_cost("edge_tts", segment_count=100)
        assert line.cost_usd == 0.0

    def test_estimate_tts_cost_openai(self, planner):
        line = planner.estimate_tts_cost(
            "openai_tts", total_chars=100000,
        )
        expected = 100000 / 1_000_000 * 15.00
        assert line.cost_usd == pytest.approx(expected, rel=1e-6)

    def test_estimate_tts_cost_from_segment_count(self, planner):
        line = planner.estimate_tts_cost("azure_tts", segment_count=200, avg_chars_per_segment=80)
        assert line.chars_synthesized == 16000
        assert line.duration_ms > 0
        assert line.cost_usd > 0.0

    # --- Chapter estimation ---

    def test_estimate_chapter_enhanced(self, planner):
        est = planner.estimate_chapter(
            "test_book", "ch001", segment_count=100,
            llm_model="gpt-4o-mini", tts_engine="edge_tts", reading_profile="enhanced",
        )
        assert est.book_id == "test_book"
        assert est.chapter_id == "ch001"
        assert est.llm_cost_usd > 0.0
        assert est.tts_cost_usd == 0.0  # edge_tts is free
        assert est.total_cost_usd > 0.0

    def test_estimate_chapter_faithful_has_no_llm_cost(self, planner):
        est = planner.estimate_chapter(
            "test_book", "ch001", segment_count=100,
            llm_model="gpt-4o", tts_engine="mock", reading_profile="faithful",
        )
        assert est.llm_cost_usd == 0.0
        assert est.llm_items == []

    def test_estimate_chapter_zero_segments(self, planner):
        est = planner.estimate_chapter(
            "test_book", "ch001", segment_count=0,
        )
        assert est.total_cost_usd == 0.0
        assert est.llm_items == []
        assert est.tts_items == []

    # --- Book estimation ---

    def test_estimate_book(self, planner):
        est = planner.estimate_book(
            "test_book", chapter_ids=["ch001", "ch002", "ch003"],
            total_segments=300,
            llm_model="gpt-4o-mini", tts_engine="mock",
        )
        assert est.book_id == "test_book"
        assert est.total_cost_usd >= 0.0
        assert est.total_duration_minutes >= 0.0
        assert len(est.llm_items) > 0

    def test_estimate_book_empty_chapters(self, planner):
        est = planner.estimate_book(
            "test_book", chapter_ids=[], total_segments=0,
        )
        assert est.total_cost_usd == 0.0

    # --- Rate cards ---

    def test_llm_rates_have_required_fields(self):
        for model, rates in LLM_RATES.items():
            assert "input_per_1m" in rates, f"{model} missing input_per_1m"
            assert "output_per_1m" in rates, f"{model} missing output_per_1m"

    def test_tts_rates_have_known_engines(self):
        assert "mock" in TTS_RATES
        assert "edge_tts" in TTS_RATES
        assert "cosyvoice" in TTS_RATES

    # --- CostEstimate properties ---

    def test_cost_estimate_total_cost_usd(self):
        est = CostEstimate(llm_cost_usd=1.5, tts_cost_usd=2.3)
        assert est.total_cost_usd == 3.8

    def test_cost_estimate_total_duration_minutes(self):
        est = CostEstimate(tts_total_duration_ms=180000)
        assert est.total_duration_minutes == 3.0
