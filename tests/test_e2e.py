"""End-to-end pipeline test: import → segment → plan → TTS → timing → package."""

from pathlib import Path

import pytest

from vn_core.adaptation import TextAdapter
from vn_core.contracts.reader_manifest import ReaderPackageManifest
from vn_core.importers import import_book
from vn_core.llm_gateway import LLMGateway
from vn_core.packaging import PackagingService
from vn_core.planner import ReadingPlanner
from vn_core.render import SpeechGateway
from vn_core.render.tts_input_composer import TTSInputComposer
from vn_core.segmenter import ChineseSegmenter
from vn_core.store import ProjectStore
from vn_core.timing import build_timing
from vn_core.voice import VoiceRegistry

GOLDEN_BOOK = Path(__file__).parent / "golden_books" / "mountain_inn.txt"


class TestEndToEnd:
    @pytest.fixture
    def store(self, tmp_path):
        db_path = tmp_path / "e2e_test.sqlite"
        s = ProjectStore(str(db_path))
        s.initialize()
        yield s
        s.close()

    @pytest.fixture
    def golden_book_path(self):
        if not GOLDEN_BOOK.exists():
            pytest.skip("Golden test book not found")
        return str(GOLDEN_BOOK)

    def test_import_txt(self, store, golden_book_path):
        chapters = import_book(golden_book_path, book_id="golden_mountain_inn", store=store)
        assert len(chapters) >= 2
        total_paragraphs = sum(len(ch.paragraphs) for ch in chapters)
        assert total_paragraphs > 0

        db_chapters = store.get_chapters("golden_mountain_inn")
        assert len(db_chapters) >= 2

    def test_segment_chapter(self, store, golden_book_path):
        chapters = import_book(golden_book_path, book_id="golden_mountain_inn", store=store)
        chapter = chapters[0]
        segmenter = ChineseSegmenter()

        all_segments = []
        for para in chapter.paragraphs:
            segs = segmenter.segment_paragraph(para.paragraph_id, para.source_text)
            all_segments.extend(segs)

        assert len(all_segments) > 0
        assert all(s.segment_id for s in all_segments)
        assert all(s.text for s in all_segments)

    @pytest.mark.asyncio
    async def test_plan_chapter(self, store, golden_book_path):
        chapters = import_book(golden_book_path, book_id="golden_mountain_inn", store=store)
        chapter = chapters[0]

        segmenter = ChineseSegmenter()
        all_segments = []
        for para in chapter.paragraphs:
            segs = segmenter.segment_paragraph(para.paragraph_id, para.source_text)
            all_segments.extend(segs)

        llm = LLMGateway()
        planner = ReadingPlanner(llm=llm)
        plan = await planner.plan_chapter(all_segments, chapter.chapter_id)

        assert len(plan) == len(all_segments)
        assert all(p.segment_id for p in plan)
        narrator_count = sum(1 for p in plan if p.speaker_id == "char_narrator")
        assert narrator_count > 0

    @pytest.mark.asyncio
    async def test_full_pipeline_mock(self, store, golden_book_path, tmp_path):
        chapters = import_book(golden_book_path, book_id="golden_mountain_inn", store=store)
        chapter = chapters[0]

        segmenter = ChineseSegmenter()
        adapter = TextAdapter()
        llm = LLMGateway()
        planner = ReadingPlanner(llm=llm)
        voice_registry = VoiceRegistry()
        TTSInputComposer()
        SpeechGateway(output_dir=str(tmp_path / "tts"))

        all_segments = []
        for para in chapter.paragraphs:
            adapted = adapter.adapt_pre_segment(f"{para.paragraph_id}_pre", para.source_text)
            segs = segmenter.segment_paragraph(para.paragraph_id, adapted.adapted_text)
            all_segments.extend(segs)

        await planner.plan_chapter(all_segments, chapter.chapter_id)

        import json
        segments_jsonl = "\n".join(
            json.dumps(s.model_dump(), ensure_ascii=False) for s in all_segments
        )
        voices_json = json.dumps(voice_registry.list_voices(), ensure_ascii=False)

        timing_entries = build_timing(
            segment_ids=[s.segment_id for s in all_segments],
            segment_durations_ms=[800] * len(all_segments),
        )

        timing_json = json.dumps([t.model_dump() for t in timing_entries], ensure_ascii=False)

        pkg_service = PackagingService()
        manifest = ReaderPackageManifest(
            book_id="golden_mountain_inn",
            title="山间客栈",
            segmenter_version="zh_clause_v1",
        )
        pkg_dir = pkg_service.build_reader_package(
            output_dir=str(tmp_path / "pkg"),
            manifest=manifest,
            segments_jsonl=segments_jsonl,
            voices_json=voices_json,
            timing_json=timing_json,
        )

        assert pkg_dir.exists()
        assert (pkg_dir / "manifest.json").exists()
        manifest_data = json.loads((pkg_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest_data["book_id"] == "golden_mountain_inn"
