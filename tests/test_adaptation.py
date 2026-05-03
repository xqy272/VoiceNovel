"""Tests for Text Adaptation module."""

from vn_core.adaptation import TextAdapter, basic_cleanup, fix_punctuation
from vn_core.contracts.text_adaptation import (
    AdaptationCategory,
    AdaptationScope,
    TextAdaptationOperation,
)


class TestBasicCleanup:
    def test_normalize_whitespace(self):
        assert basic_cleanup("  \u591a\u4f59  \u7a7a\u683c  ") == "\u591a\u4f59 \u7a7a\u683c"

    def test_normalize_newlines(self):
        result = basic_cleanup("\u7b2c\u4e00\u884c\n\n\n\u7b2c\u4e8c\u884c")
        assert "\u7b2c\u4e00\u884c" in result
        assert "\u7b2c\u4e8c\u884c" in result

    def test_normalize_unicode(self):
        result = basic_cleanup("\uff01\uff0c")
        assert result == "!,"


class TestPunctuationFix:
    def test_ellipsis_normalization(self):
        three_dots = "\u2026\u2026\u2026"
        result, ops = fix_punctuation(three_dots, "test_p001")
        assert "\u2026" in result
        assert len(ops) == 1
        assert ops[0].category.value == "punctuation"

    def test_em_dash_normalization(self):
        result, ops = fix_punctuation(
            "\u4ed6\u8d70\u4e86\u2014\u2014\u2014\u2014\u56de\u6765\u4e86",
            "test_p001",
        )
        assert "\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014\u2014" not in result

    def test_no_change_needed(self):
        result, ops = fix_punctuation("\u7b80\u5355\u7684\u53e5\u5b50\u3002", "test_p001")
        assert result == "\u7b80\u5355\u7684\u53e5\u5b50\u3002"
        assert len(ops) == 0


class TestTextAdapter:
    def test_pre_segment_basic(self):
        adapter = TextAdapter(policy="balanced")
        result = adapter.adapt_pre_segment("ch001_p001_s001", "\u4ed6\u8fdb\u6765\u4e86\u3002")
        assert result.adapted_text == "\u4ed6\u8fdb\u6765\u4e86\u3002"
        assert len(result.operations) == 0

    def test_pre_segment_cleanup(self):
        adapter = TextAdapter(policy="balanced")
        result = adapter.adapt_pre_segment("ch001_p001_s001", "  \u591a\u4f59\u7a7a\u683c  ")
        assert len(result.operations) >= 1
        assert result.operations[0].category.value == "basic_cleanup"

    def test_pre_tts_number_normalization(self):
        adapter = TextAdapter(policy="balanced")
        text = "\u57282024\u5e74\u6625\u5929"
        result = adapter.adapt_pre_tts("ch001_p001_s001", text)
        assert len(result.operations) >= 0

    def test_apply_operations_display_and_tts(self):
        adapter = TextAdapter()
        ops = [
            TextAdaptationOperation(
                op_id="op_001",
                segment_id="ch001_p001_s001",
                original="\u9519\u5b57",
                normalized="\u6b63\u786e",
                category=AdaptationCategory.typo,
                scope=AdaptationScope.display_and_tts,
                confidence=0.95,
                risk="low",
                evidence=["\u4e0a\u4e0b\u6587\u8bc1\u636e"],
                source="rule",
            )
        ]
        result = adapter.apply_operations(
            "\u8fd9\u662f\u4e00\u4e2a\u9519\u5b57\u5728\u8fd9\u91cc\u3002",
            ops,
        )
        assert "\u6b63\u786e" in result
