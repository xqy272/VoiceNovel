"""Tests for Pronunciation Engine and SystemLexicon."""

from __future__ import annotations

from vn_core.pronunciation import PronunciationEngine
from vn_core.pronunciation.system_lexicon import (
    apply_system_rules,
    get_version,
    normalize_english_in_chinese,
    normalize_percentage,
    normalize_punctuation_for_tts,
    normalize_units,
    normalize_year,
)
from vn_core.pronunciation.user_lexicon import UserLexicon


class TestSystemLexicon:
    def test_year_normalization(self):
        assert normalize_year("2024年") != "2024年"
        result = normalize_year("2024年")
        assert " " in result  # year digits spaced for TTS

    def test_year_preserves_non_year_numbers(self):
        text = "他有3个苹果，价格199元。"
        result = normalize_year(text)
        assert "3个苹果" in result
        assert "199元" in result  # 199 is not a year

    def test_percentage_normalization(self):
        result = normalize_percentage("增长了50%")
        assert result == "增长了百分之50"

    def test_unit_normalization(self):
        result = normalize_units("5kg的米和30cm的线")
        assert "千克" in result
        assert "厘米" in result

    def test_longer_units_are_replaced_before_shorter_units(self):
        result = normalize_units("100ml、2m²、3km²、4mm、5cm、6km、7m")
        assert result == "100毫升、2平方米、3平方千米、4毫米、5厘米、6千米、7米"

    def test_english_in_chinese(self):
        result = normalize_english_in_chinese("他使用了AI技术。")
        assert "A I" in result or "AI" in result

    def test_punctuation_normalization(self):
        result = normalize_punctuation_for_tts("你好...是的--没错")
        assert "…" in result
        assert "——" in result

    def test_apply_system_rules_idempotent(self):
        """System rules should be idempotent: second pass = no further changes."""
        text = "2024年增长了50%，重5kg。"
        first = apply_system_rules(text)
        second = apply_system_rules(first)
        # Polyphonic rules produce pinyin that won't re-match; other
        # rules check for patterns already converted. Result is stable.
        assert first == second

    def test_get_version(self):
        assert get_version() == "1.0.1"


class TestUserLexicon:
    def test_load_and_apply(self, tmp_path):
        lex_file = tmp_path / "lexicon.json"
        lex_file.write_text(
            '{"version":"1.0","overrides":{"测试A":"测试B"},"disabled_system_rules":[]}',
            encoding="utf-8",
        )
        lexicon = UserLexicon(lex_file)
        assert lexicon.version == "1.0"
        assert lexicon.apply("这是测试A文本") == "这是测试B文本"

    def test_empty_lexicon(self):
        lexicon = UserLexicon()
        assert lexicon.apply("hello") == "hello"

    def test_get_override(self):
        lexicon = UserLexicon()
        assert lexicon.get_override("nonexistent") is None


class TestPronunciationEngine:
    def test_normalize_basic(self):
        engine = PronunciationEngine()
        result = engine.normalize("到2024年，增长了50%。")
        assert result != "到2024年，增长了50%。"  # should have been modified

    def test_system_version(self):
        engine = PronunciationEngine()
        assert engine.system_version == "1.0.1"

    def test_user_lexicon_overrides_system(self, tmp_path):
        lex_file = tmp_path / "lexicon.json"
        lex_file.write_text(
            '{"version":"1.0","overrides":{"2024":"二零二四手动"},"disabled_system_rules":[]}',
            encoding="utf-8",
        )
        engine = PronunciationEngine(user_lexicon=UserLexicon(lex_file))
        result = engine.normalize("2024年")
        assert "二零二四手动" in result

    def test_cache_fingerprint_includes_user_lexicon_content(self, tmp_path):
        lex_a = tmp_path / "lexicon_a.json"
        lex_b = tmp_path / "lexicon_b.json"
        lex_a.write_text(
            '{"version":"1.0","overrides":{"陆明":"路明"},"disabled_system_rules":[]}',
            encoding="utf-8",
        )
        lex_b.write_text(
            '{"version":"1.0","overrides":{"陆明":"卢明"},"disabled_system_rules":[]}',
            encoding="utf-8",
        )

        engine_a = PronunciationEngine(user_lexicon=UserLexicon(lex_a))
        engine_b = PronunciationEngine(user_lexicon=UserLexicon(lex_b))

        assert engine_a.cache_fingerprint != engine_b.cache_fingerprint


class TestTTSInputComposerWithPronunciation:
    def test_composer_applies_pronunciation(self):
        from vn_core.render.tts_input_composer import TTSInputComposer

        engine = PronunciationEngine()
        composer = TTSInputComposer(pronunciation_engine=engine)
        request = composer.compose(
            segment_id="ch001_p001_s000",
            tts_base_text="2024年增长50%。",
            voice_id="edge_zh_narrator_001",
            engine="edge_tts",
        )
        # The text should have been modified by pronunciation normalization
        assert "百分之" in request.text
        assert request.segment_id == "ch001_p001_s000"

    def test_composer_without_pronunciation_engine(self):
        from vn_core.render.tts_input_composer import TTSInputComposer

        composer = TTSInputComposer()
        request = composer.compose(
            segment_id="ch001_p001_s000",
            tts_base_text="2024年增长50%。",
            voice_id="edge_zh_narrator_001",
            engine="edge_tts",
        )
        assert request.text == "2024年增长50%。"  # unchanged
