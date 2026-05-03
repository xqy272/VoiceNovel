"""Cache key stability tests for reader_package and audio_take."""

from vn_core.orchestration.cache_keys import (
    audio_take_cache_key,
    reader_package_cache_key,
)


class TestReaderPackageCacheKey:
    def test_same_inputs_same_key(self):
        k1 = reader_package_cache_key(
            "book_001", "ch001", "default", "enhanced", "balanced",
            "mock", ["seg_v1", "plan_v1"], "buster_1",
        )
        k2 = reader_package_cache_key(
            "book_001", "ch001", "default", "enhanced", "balanced",
            "mock", ["seg_v1", "plan_v1"], "buster_1",
        )
        assert k1 == k2

    def test_different_chapter_different_key(self):
        k1 = reader_package_cache_key(
            "book_001", "ch001", "default", "enhanced", "balanced", "mock",
        )
        k2 = reader_package_cache_key(
            "book_001", "ch002", "default", "enhanced", "balanced", "mock",
        )
        assert k1 != k2

    def test_input_versions_order_independent(self):
        """Sorted internally, so order of the list does not matter."""
        k1 = reader_package_cache_key(
            "book_001", "ch001", "default", "enhanced", "balanced", "mock",
            input_artifact_versions=["b", "a"],
        )
        k2 = reader_package_cache_key(
            "book_001", "ch001", "default", "enhanced", "balanced", "mock",
            input_artifact_versions=["a", "b"],
        )
        assert k1 == k2

    def test_cache_buster_changes_key(self):
        k1 = reader_package_cache_key(
            "book_001", "ch001", "default", "enhanced", "balanced", "mock",
            cache_buster="abc",
        )
        k2 = reader_package_cache_key(
            "book_001", "ch001", "default", "enhanced", "balanced", "mock",
            cache_buster="def",
        )
        assert k1 != k2

    def test_none_cache_buster_same_as_absent(self):
        k1 = reader_package_cache_key(
            "book_001", "ch001", "default", "enhanced", "balanced", "mock",
        )
        k2 = reader_package_cache_key(
            "book_001", "ch001", "default", "enhanced", "balanced", "mock",
            cache_buster=None,
        )
        assert k1 == k2


class TestAudioTakeCacheKey:
    def test_same_inputs_same_key(self):
        k1 = audio_take_cache_key(
            "ch001_p000_s000", "你好世界", "edge_zh_female_001",
            "edge_tts", {"emotion": "neutral", "intensity": 0.5},
            "default", ["seg_v1", "voice_v1"],
        )
        k2 = audio_take_cache_key(
            "ch001_p000_s000", "你好世界", "edge_zh_female_001",
            "edge_tts", {"emotion": "neutral", "intensity": 0.5},
            "default", ["seg_v1", "voice_v1"],
        )
        assert k1 == k2

    def test_text_change_changes_key(self):
        k1 = audio_take_cache_key(
            "s001", "你好", "v1", "mock",
        )
        k2 = audio_take_cache_key(
            "s001", "世界", "v1", "mock",
        )
        assert k1 != k2

    def test_voice_id_change_changes_key(self):
        k1 = audio_take_cache_key("s001", "text", "voice_a", "mock")
        k2 = audio_take_cache_key("s001", "text", "voice_b", "mock")
        assert k1 != k2

    def test_engine_change_changes_key(self):
        k1 = audio_take_cache_key("s001", "text", "v1", "mock")
        k2 = audio_take_cache_key("s001", "text", "v1", "edge_tts")
        assert k1 != k2

    def test_cache_buster_changes_key(self):
        k1 = audio_take_cache_key("s001", "text", "v1", "mock", cache_buster="a")
        k2 = audio_take_cache_key("s001", "text", "v1", "mock", cache_buster="b")
        assert k1 != k2

    def test_reading_style_order_independent(self):
        k1 = audio_take_cache_key(
            "s001", "text", "v1", "mock",
            reading_style={"intensity": 0.5, "emotion": "neutral"},
        )
        k2 = audio_take_cache_key(
            "s001", "text", "v1", "mock",
            reading_style={"emotion": "neutral", "intensity": 0.5},
        )
        assert k1 == k2

    def test_input_versions_order_independent(self):
        k1 = audio_take_cache_key(
            "s001", "text", "v1", "mock",
            input_artifact_versions=["c", "a", "b"],
        )
        k2 = audio_take_cache_key(
            "s001", "text", "v1", "mock",
            input_artifact_versions=["a", "b", "c"],
        )
        assert k1 == k2


class TestCacheKeyArtifactDependency:
    def test_voice_assignment_version_changes_key(self):
        k1 = reader_package_cache_key(
            "book_001", "ch001", "default", "enhanced", "balanced", "mock",
            voice_assignment_version="va_v1",
        )
        k2 = reader_package_cache_key(
            "book_001", "ch001", "default", "enhanced", "balanced", "mock",
            voice_assignment_version="va_v2",
        )
        assert k1 != k2

    def test_adaptation_ops_version_changes_key(self):
        k1 = reader_package_cache_key(
            "book_001", "ch001", "default", "enhanced", "balanced", "mock",
            adaptation_ops_version="ao_v1",
        )
        k2 = reader_package_cache_key(
            "book_001", "ch001", "default", "enhanced", "balanced", "mock",
            adaptation_ops_version="ao_v2",
        )
        assert k1 != k2

    def test_none_versions_same_as_absent(self):
        k1 = reader_package_cache_key(
            "book_001", "ch001", "default", "enhanced", "balanced", "mock",
        )
        k2 = reader_package_cache_key(
            "book_001", "ch001", "default", "enhanced", "balanced", "mock",
            voice_assignment_version=None,
            adaptation_ops_version=None,
        )
        assert k1 == k2
