"""Tests for Koodo Package Adapter and Voice Plugin."""

import json

from integrations.koodo_package_adapter import koodo_from_reader_package
from integrations.koodo_voice_plugin import generate_koodo_voice_config


class TestKoodoPackageAdapter:
    def test_convert_empty_package(self, tmp_path):
        pkg_dir = tmp_path / "reader_pkg"
        pkg_dir.mkdir()
        (pkg_dir / "manifest.json").write_text(
            json.dumps({
                "book_id": "test01",
                "title": "Test Book",
                "segmenter_version": "zh_clause_v1",
                "audio_codec": "mp3",
                "timing_unit": "ms",
                "highlight_granularity": "sentence_clause",
            }),
            encoding="utf-8",
        )
        (pkg_dir / "timing.json").write_text("[]", encoding="utf-8")
        (pkg_dir / "segments.jsonl").write_text("", encoding="utf-8")
        (pkg_dir / "voices.json").write_text("[]", encoding="utf-8")

        out = koodo_from_reader_package(str(pkg_dir))
        assert (out / "koodo_metadata.json").exists()
        assert (out / "koodo_chapters.json").exists()
        assert (out / "koodo_toc.json").exists()

    def test_convert_with_timing_and_segments(self, tmp_path):
        pkg_dir = tmp_path / "reader_pkg"
        pkg_dir.mkdir()
        manifest = {
            "book_id": "book01",
            "title": "Mountain Inn",
            "segmenter_version": "zh_clause_v1",
            "audio_codec": "mp3",
            "timing_unit": "ms",
            "highlight_granularity": "sentence_clause",
        }
        (pkg_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8",
        )
        timing = [
            {
                "segment_id": "ch001_p001_s000",
                "chapter_audio": "ch001.mp3",
                "start_ms": 0,
                "end_ms": 3000,
            },
            {
                "segment_id": "ch001_p001_s001",
                "chapter_audio": "ch001.mp3",
                "start_ms": 3200,
                "end_ms": 6500,
            },
        ]
        (pkg_dir / "timing.json").write_text(
            json.dumps(timing), encoding="utf-8",
        )
        segments = [
            {"segment_id": "ch001_p001_s000", "text": "Hello."},
            {"segment_id": "ch001_p001_s001", "text": "World."},
        ]
        segments_jsonl = "\n".join(json.dumps(s, ensure_ascii=False) for s in segments)
        (pkg_dir / "segments.jsonl").write_text(segments_jsonl, encoding="utf-8")
        (pkg_dir / "voices.json").write_text("[]", encoding="utf-8")

        html = (
            '<div class="chapter">'
            '<p data-pid="ch001_p001">'
            '<span data-seg-id="ch001_p001_s000">Hello.</span>'
            '</p></div>'
        )
        (pkg_dir / "book01.cleaned.xhtml").write_text(html, encoding="utf-8")

        out = koodo_from_reader_package(str(pkg_dir), book_title="Mountain Inn")
        meta = json.loads((out / "koodo_metadata.json").read_text())
        assert meta["book_id"] == "book01"
        assert meta["title"] == "Mountain Inn"
        assert meta["total_timing_entries"] == 2

        chapters = json.loads((out / "koodo_chapters.json").read_text())
        assert len(chapters) == 1
        assert chapters[0]["audio_file"] == "ch001.mp3"
        assert chapters[0]["duration_ms"] == 6500

        toc = json.loads((out / "koodo_toc.json").read_text())
        assert len(toc["entries"]) == 2
        assert toc["entries"][0]["text_preview"] == "Hello."

        assert (out / "content.xhtml").exists()
        assert (out / "index.json").exists()


class TestKoodoVoicePlugin:
    def test_generate_basic_config(self, tmp_path):
        out = generate_koodo_voice_config(
            output_path=str(tmp_path / "koodo_voice"),
            book_id="test01",
        )
        assert (out / "voice_config.json").exists()
        assert (out / "playback_config.json").exists()

    def test_config_with_assignments(self, tmp_path):
        voice_assignments = [
            {
                "character_id": "char_lu_ming",
                "voice_id": "edge_zh_male_001",
                "confidence": 0.85,
                "source": "auto",
                "user_locked": False,
            },
        ]
        out = generate_koodo_voice_config(
            output_path=str(tmp_path / "koodo_voice"),
            voice_assignments=voice_assignments,
            book_id="book01",
        )
        config = json.loads((out / "voice_config.json").read_text())
        assert config["book_id"] == "book01"
        assert len(config["voices"]) == 1
        assert config["voices"][0]["voice_id"] == "edge_zh_male_001"

    def test_playback_config(self, tmp_path):
        out = generate_koodo_voice_config(
            output_path=str(tmp_path / "koodo_voice"),
            book_id="book01",
        )
        playback = json.loads((out / "playback_config.json").read_text())
        assert playback["highlight_sync"] is True
        assert playback["highlight_granularity"] == "sentence_clause"
        assert playback["segment_data_attribute"] == "data-seg-id"
