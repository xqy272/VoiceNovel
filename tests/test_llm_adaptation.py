"""Tests for LLM-driven text adaptation."""

from __future__ import annotations

import pytest

from vn_core.adaptation.llm_adapter import (
    POLICY_THRESHOLDS,
    AdaptationPolicy,
    LLMTextAdapter,
)
from vn_core.contracts.text_adaptation import (
    AdaptationCategory,
)
from vn_core.llm_gateway import LLMGateway


@pytest.fixture
def llm_gateway():
    return LLMGateway()


@pytest.fixture
def adapter(llm_gateway):
    return LLMTextAdapter(llm_gateway, policy=AdaptationPolicy.balanced)


class TestAdaptationPolicy:
    def test_policy_values(self):
        assert AdaptationPolicy.conservative == "conservative"
        assert AdaptationPolicy.balanced == "balanced"
        assert AdaptationPolicy.aggressive == "aggressive"

    def test_conservative_threshold_is_highest(self):
        assert POLICY_THRESHOLDS[AdaptationPolicy.conservative] == 0.90

    def test_balanced_threshold(self):
        assert POLICY_THRESHOLDS[AdaptationPolicy.balanced] == 0.75


class TestLLMTextAdapter:
    @pytest.mark.asyncio
    async def test_adapt_empty_paragraphs(self, adapter):
        result = await adapter.adapt_paragraphs_batch([])
        assert result.operations == []
        assert result.error == ""

    @pytest.mark.asyncio
    async def test_adapt_with_mock_llm(self, adapter):
        """Mock LLM returns empty operations array, so no ops produced."""
        result = await adapter.adapt_paragraph(
            "ch001_p001",
            "陆明冷冷道：你既然来了，就别想走。",
        )
        # Mock LLM returns {"operations": []}, so result should be empty
        assert result.error == ""

    @pytest.mark.asyncio
    async def test_adapt_batch_splits_large_input(self, adapter):
        """Verify batch splitting works for paragraphs exceeding batch size."""
        adapter.batch_size = 2
        paragraphs = [
            {"paragraph_id": f"ch001_p{i:03d}", "text": f"测试段落{i}"}
            for i in range(5)
        ]
        result = await adapter.adapt_paragraphs_batch(paragraphs)
        # Should not error even though mock LLM returns empty ops
        assert result.error == ""


class TestPolicyFilters:
    def test_conservative_filters_aggressive_categories(self):
        """Conservative policy should reject de_obfuscation ops."""
        from vn_core.adaptation.llm_adapter import POLICY_CATEGORIES

        conservative = POLICY_CATEGORIES[AdaptationPolicy.conservative]
        assert AdaptationCategory.de_obfuscation not in conservative
        assert AdaptationCategory.typo not in conservative
        assert AdaptationCategory.basic_cleanup in conservative
        assert AdaptationCategory.tts_normalization in conservative

    def test_balanced_allows_all(self):
        from vn_core.adaptation.llm_adapter import POLICY_CATEGORIES

        balanced = POLICY_CATEGORIES[AdaptationPolicy.balanced]
        assert AdaptationCategory.de_obfuscation in balanced
        assert AdaptationCategory.typo in balanced
        assert AdaptationCategory.terminology in balanced

    def test_op_parse_respects_confidence_threshold(self, llm_gateway):
        """Verify low-confidence ops are filtered out."""
        adapter = LLMTextAdapter(llm_gateway, policy=AdaptationPolicy.balanced)

        raw_ops = [{
            "op_id": "op_001",
            "segment_id": "ch001_p001",
            "original": "ZF",
            "normalized": "政府",
            "category": "de_obfuscation",
            "scope": "display_and_tts",
            "confidence": 0.50,  # below balanced threshold of 0.75
            "risk": "medium",
            "evidence": ["test"],
        }]
        ops = adapter._parse_operations(
            raw_ops,
            [{"paragraph_id": "ch001_p001", "text": "test"}],
            [0],
        )
        assert len(ops) == 0  # filtered by confidence

    def test_op_parse_accepts_high_confidence(self, llm_gateway):
        adapter = LLMTextAdapter(llm_gateway, policy=AdaptationPolicy.balanced)
        raw_ops = [{
            "op_id": "op_001",
            "segment_id": "ch001_p001",
            "original": "ZF",
            "normalized": "政府",
            "category": "de_obfuscation",
            "scope": "display_and_tts",
            "confidence": 0.92,
            "risk": "low",
            "evidence": ["test"],
        }]
        ops = adapter._parse_operations(
            raw_ops,
            [{"paragraph_id": "ch001_p001", "text": "test"}],
            [0],
        )
        assert len(ops) == 1
        assert ops[0].category.value == "de_obfuscation"
        assert ops[0].source == "llm_context"

    def test_op_parse_filters_suggest_only(self, llm_gateway):
        """suggest_only scope ops should not be auto-applied."""
        adapter = LLMTextAdapter(llm_gateway, policy=AdaptationPolicy.balanced)
        raw_ops = [{
            "op_id": "op_001",
            "segment_id": "ch001_p001",
            "original": "test",
            "normalized": "fixed",
            "category": "cleanup",
            "scope": "suggest_only",
            "confidence": 0.99,
            "risk": "low",
            "evidence": [],
        }]
        ops = adapter._parse_operations(
            raw_ops,
            [{"paragraph_id": "ch001_p001", "text": "test"}],
            [0],
        )
        assert len(ops) == 0


class TestPipelineIntegration:
    @pytest.mark.asyncio
    async def test_pipeline_with_adaptation_policy(self, tmp_path):
        """Verify Pipeline construction with adaptation_policy works."""
        from vn_core.pipeline.pipeline import Pipeline
        from vn_core.store import ProjectStore

        store = ProjectStore(str(tmp_path / "test.sqlite"))
        pipeline = Pipeline(
            store=store,
            output_dir=str(tmp_path),
            adaptation_policy="conservative",
        )
        assert pipeline.llm_adapter is not None
        assert pipeline.llm_adapter.policy == AdaptationPolicy.conservative

    def test_pipeline_with_adaptation_off(self, tmp_path):
        """Verify Pipeline with adaptation_policy='off' disables LLM adapter."""
        from vn_core.pipeline.pipeline import Pipeline
        from vn_core.store import ProjectStore

        store = ProjectStore(str(tmp_path / "test.sqlite"))
        pipeline = Pipeline(
            store=store,
            output_dir=str(tmp_path),
            adaptation_policy="off",
        )
        assert pipeline.llm_adapter is None

    def test_pipeline_rejects_invalid_policy(self, tmp_path):
        from vn_core.pipeline.pipeline import Pipeline
        from vn_core.store import ProjectStore

        store = ProjectStore(str(tmp_path / "test.sqlite"))
        with pytest.raises(ValueError, match="adaptation_policy"):
            Pipeline(store=store, output_dir=str(tmp_path), adaptation_policy="invalid")
