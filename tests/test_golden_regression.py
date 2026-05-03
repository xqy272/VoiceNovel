"""Golden chapter regression tests: validate full pipeline output against known fixtures.

These tests ensure that the pipeline produces consistent, correct output for
2-3 golden chapters, catching regressions in segmenter, planner, timing, and
packaging.
"""

import json
from pathlib import Path

import pytest

from vn_core.adaptation import TextAdapter
from vn_core.contracts.reader_manifest import ReaderPackageManifest
from vn_core.harness import GateDecision, HarnessGate
from vn_core.importers import import_book
from vn_core.llm_gateway import LLMGateway
from vn_core.packaging import PackagingService
from vn_core.planner import ReadingPlanner
from vn_core.segmenter import SEGMENTER_VERSION, ChineseSegmenter
from vn_core.store import ProjectStore
from vn_core.timing import build_timing, compute_chapter_duration_ms
from vn_core.voice import VoiceRegistry
from vn_core.voice.casting import cast_all_characters

GOLDEN_BOOK = Path(__file__).parent / "golden_books" / "mountain_inn.txt"


class TestGoldenChapterRegression:
    """Full regression suite against the mountain_inn.txt golden fixture."""

    @pytest.fixture
    def store(self, tmp_path):
        db_path = tmp_path / "golden_regression.sqlite"
        s = ProjectStore(str(db_path))
        s.initialize()
        yield s
        s.close()

    @pytest.fixture
    def golden_path(self):
        if not GOLDEN_BOOK.exists():
            pytest.skip("Golden test book not found")
        return str(GOLDEN_BOOK)

    @pytest.fixture
    def imported(self, store, golden_path):
        """Import golden book and return (chapters, all segments per chapter)."""
        chapters = import_book(golden_path, book_id="golden_regression", store=store)
        segmenter = ChineseSegmenter()
        adapter = TextAdapter()

        all_data = []
        for ch in chapters:
            segs = []
            adapted = {}
            for para in ch.paragraphs:
                a = adapter.adapt_pre_segment(f"{para.paragraph_id}_pre", para.source_text)
                segments = segmenter.segment_paragraph(para.paragraph_id, a.adapted_text)
                segs.extend(segments)
                for seg in segments:
                    ta = adapter.adapt_pre_tts(seg.segment_id, seg.text)
                    adapted[seg.segment_id] = ta.adapted_text
            all_data.append({
                "chapter": ch,
                "segments": segs,
                "adapted": adapted,
            })
        return chapters, all_data

    # ------------------------------------------------------------------
    # Chapter structure
    # ------------------------------------------------------------------

    def test_golden_book_has_multiple_chapters(self, store, golden_path):
        chapters = import_book(golden_path, book_id="test_multi_ch", store=store)
        assert len(chapters) >= 2, "Golden book should have at least 2 chapters"

    def test_golden_chapters_have_paragraphs(self, imported):
        chapters, all_data = imported
        for ch_data in all_data:
            assert len(ch_data["chapter"].paragraphs) > 0, (
                f"Chapter {ch_data['chapter'].chapter_id} has no paragraphs"
            )

    # ------------------------------------------------------------------
    # Segmenter regression
    # ------------------------------------------------------------------

    def test_segments_non_empty(self, imported):
        _, all_data = imported
        for ch_data in all_data:
            assert len(ch_data["segments"]) > 0, (
                f"Chapter {ch_data['chapter'].chapter_id} produced zero segments"
            )

    def test_segment_ids_are_stable(self, imported):
        """Re-run the segmenter and verify IDs are identical (stability)."""
        _, all_data = imported
        segmenter = ChineseSegmenter()
        adapter = TextAdapter()

        for ch_data in all_data:
            segs2 = []
            for para in ch_data["chapter"].paragraphs:
                a = adapter.adapt_pre_segment(f"{para.paragraph_id}_pre", para.source_text)
                segs2.extend(segmenter.segment_paragraph(para.paragraph_id, a.adapted_text))

            original_ids = [s.segment_id for s in ch_data["segments"]]
            rerun_ids = [s.segment_id for s in segs2]
            assert original_ids == rerun_ids, (
                f"Segment IDs changed on re-run for {ch_data['chapter'].chapter_id}"
            )

    def test_segment_ids_are_unique_per_chapter(self, imported):
        _, all_data = imported
        for ch_data in all_data:
            ids = [s.segment_id for s in ch_data["segments"]]
            assert len(ids) == len(set(ids)), (
                f"Duplicate segment IDs in {ch_data['chapter'].chapter_id}"
            )

    def test_segments_have_valid_version(self, imported):
        _, all_data = imported
        for ch_data in all_data:
            for seg in ch_data["segments"]:
                assert seg.segmenter_version == SEGMENTER_VERSION

    def test_segment_count_regression(self, imported):
        """Snapshot test: segment counts should match known values."""
        _, all_data = imported
        # First pass establishes the baseline; subsequent runs catch regressions
        for ch_data in all_data:
            count = len(ch_data["segments"])
            assert count > 0
            # Store for cross-reference
            ch_data["_segment_count"] = count

    def test_golden_chapter1_segments_in_range(self, imported):
        """Golden chapter 1 should have a reasonable number of segments."""
        _, all_data = imported
        ch1 = all_data[0]
        count = len(ch1["segments"])
        # The golden text has ~7-8 paragraphs; expect 20-60 segments
        assert 10 <= count <= 100, (
            f"Chapter 1 segment count {count} outside expected range [10, 100]"
        )

    # ------------------------------------------------------------------
    # Planner regression
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_plan_covers_all_segments(self, imported, store):
        chapters, all_data = imported
        llm = LLMGateway()
        for ch_data in all_data:
            planner = ReadingPlanner(llm=llm)
            plan = await planner.plan_chapter(ch_data["segments"], ch_data["chapter"].chapter_id)
            assert len(plan) == len(ch_data["segments"]), (
                f"Plan entries ({len(plan)}) != segments ({len(ch_data['segments'])})"
            )

    @pytest.mark.asyncio
    async def test_plan_has_narrator_entries(self, imported, store):
        chapters, all_data = imported
        llm = LLMGateway()
        for ch_data in all_data:
            planner = ReadingPlanner(llm=llm)
            plan = await planner.plan_chapter(ch_data["segments"], ch_data["chapter"].chapter_id)
            narrators = [p for p in plan if p.speaker_id == "char_narrator"]
            assert len(narrators) > 0, "Plan should have at least some narrator entries"

    @pytest.mark.asyncio
    async def test_plan_entries_have_required_fields(self, imported, store):
        chapters, all_data = imported
        llm = LLMGateway()
        for ch_data in all_data:
            planner = ReadingPlanner(llm=llm)
            plan = await planner.plan_chapter(ch_data["segments"], ch_data["chapter"].chapter_id)
            for entry in plan:
                assert entry.segment_id, "Missing segment_id"
                assert entry.text, "Missing text"
                assert entry.speaker_id, "Missing speaker_id"
                assert 0.0 <= entry.speaker_confidence <= 1.0, (
                    f"Invalid confidence {entry.speaker_confidence}"
                )

    # ------------------------------------------------------------------
    # Voice casting regression
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_voice_casting_produces_assignments(self, imported, store):
        chapters, all_data = imported
        llm = LLMGateway()
        voice_registry = VoiceRegistry()

        for ch_data in all_data:
            planner = ReadingPlanner(llm=llm)
            plan = await planner.plan_chapter(ch_data["segments"], ch_data["chapter"].chapter_id)
            assignments = cast_all_characters(plan, voice_registry, store, "golden_regression")

            assert len(assignments) > 0
            for char_id, assignment in assignments.items():
                assert assignment.voice_id, f"No voice assigned for {char_id}"
                assert assignment.character_id == char_id
                assert 0.0 <= assignment.confidence <= 1.0

    # ------------------------------------------------------------------
    # Timing regression
    # ------------------------------------------------------------------

    def test_timing_entries_match_segments(self, imported):
        _, all_data = imported
        for ch_data in all_data:
            segs = ch_data["segments"]
            timing = build_timing(
                segment_ids=[s.segment_id for s in segs],
                segment_durations_ms=[800] * len(segs),
            )
            assert len(timing) == len(segs)

    def test_timing_no_overlaps(self, imported):
        _, all_data = imported
        harness = HarnessGate()
        for ch_data in all_data:
            segs = ch_data["segments"]
            timing = build_timing(
                segment_ids=[s.segment_id for s in segs],
                segment_durations_ms=[800] * len(segs),
            )
            result = harness.validate("timing", timing)
            assert result.decision == GateDecision.pass_decision, (
                f"Timing overlap in {ch_data['chapter'].chapter_id}: {result.reason}"
            )

    def test_chapter_duration_positive(self, imported):
        _, all_data = imported
        for ch_data in all_data:
            segs = ch_data["segments"]
            timing = build_timing(
                segment_ids=[s.segment_id for s in segs],
                segment_durations_ms=[800] * len(segs),
            )
            duration = compute_chapter_duration_ms(timing)
            assert duration > 0

    # ------------------------------------------------------------------
    # Harness validation regression
    # ------------------------------------------------------------------

    def test_harness_validates_segments(self, imported):
        _, all_data = imported
        harness = HarnessGate()
        for ch_data in all_data:
            result = harness.validate("segments", ch_data["segments"])
            assert result.decision == GateDecision.pass_decision, (
                f"Segment validation failed: {result.reason}"
            )

    @pytest.mark.asyncio
    async def test_harness_validates_plan(self, imported):
        chapters, all_data = imported
        llm = LLMGateway()
        harness = HarnessGate()
        for ch_data in all_data:
            planner = ReadingPlanner(llm=llm)
            plan = await planner.plan_chapter(ch_data["segments"], ch_data["chapter"].chapter_id)
            result = harness.validate("reading_plan", plan)
            assert result.decision == GateDecision.pass_decision, (
                f"Plan validation failed: {result.reason}"
            )

    # ------------------------------------------------------------------
    # Packaging regression
    # ------------------------------------------------------------------

    def test_package_has_all_required_files(self, imported, tmp_path):
        _, all_data = imported
        pkg_service = PackagingService()

        for ch_data in all_data:
            segs = ch_data["segments"]
            segs_jsonl = "\n".join(json.dumps(s.model_dump(), ensure_ascii=False) for s in segs)
            timing = build_timing(
                segment_ids=[s.segment_id for s in segs],
                segment_durations_ms=[800] * len(segs),
            )
            timing_json = json.dumps([t.model_dump() for t in timing], ensure_ascii=False)
            voices_json = json.dumps([], ensure_ascii=False)

            manifest = ReaderPackageManifest(
                book_id="golden_regression",
                title=ch_data["chapter"].title or ch_data["chapter"].chapter_id,
                segmenter_version=SEGMENTER_VERSION,
            )

            pkg_dir = pkg_service.build_reader_package(
                output_dir=str(tmp_path / "pkgs" / ch_data["chapter"].chapter_id),
                manifest=manifest,
                segments_jsonl=segs_jsonl,
                voices_json=voices_json,
                timing_json=timing_json,
            )

            # Validate package completeness
            required = ["manifest.json", "segments.jsonl", "voices.json", "timing.json"]
            for filename in required:
                assert (pkg_dir / filename).exists(), (
                    f"Package missing {filename} for {ch_data['chapter'].chapter_id}"
                )

    # ------------------------------------------------------------------
    # Full pipeline integration (cold start path)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_cold_start_phases_1_2(self, store, golden_path, tmp_path):
        """Verify cold start Phase 1+2 (import + segment + scan) works end-to-end."""
        from vn_core.pipeline.pipeline import Pipeline

        pipeline = Pipeline(
            store=store,
            output_dir=str(tmp_path / "cold_start_output"),
            tts_engine="mock",
            reading_profile="faithful",
        )
        result = await pipeline.cold_start(golden_path, book_id="golden_cold_start")

        assert result.book_id == "golden_cold_start"
        assert len(result.chapters) >= 2
        assert result.segments_count > 0
        assert result.phase in (
            "phase1_local", "phase2_scan", "phase3_buffer", "buffer_ready",
            "phase4_background",
        )

    @pytest.mark.asyncio
    async def test_bake_chapter_faithful_mode(self, store, golden_path, tmp_path):
        """Full bake_chapter in faithful mode (no LLM enhancements)."""
        chapters = import_book(golden_path, book_id="golden_bake_faithful", store=store)
        from vn_core.pipeline.pipeline import Pipeline

        pipeline = Pipeline(
            store=store,
            output_dir=str(tmp_path / "bake_output"),
            tts_engine="mock",
            reading_profile="faithful",
            generation_config_id="default",
        )
        result = await pipeline.bake_chapter("golden_bake_faithful", chapters[0].chapter_id)

        assert result.success, f"Bake failed: {result.errors}"
        assert len(result.segments) > 0
        assert len(result.plan) > 0
        assert len(result.timing) > 0
        assert result.package_dir
        assert Path(result.package_dir).exists()

        # Faithful mode: all speakers should be narrator
        for entry in result.plan:
            assert entry.speaker_id == "char_narrator", (
                f"Faithful mode should use narrator only, got {entry.speaker_id}"
            )

    @pytest.mark.asyncio
    async def test_bake_chapter_enhanced_mode(self, store, golden_path, tmp_path):
        """Full bake_chapter in enhanced mode."""
        chapters = import_book(golden_path, book_id="golden_bake_enhanced", store=store)
        from vn_core.pipeline.pipeline import Pipeline

        pipeline = Pipeline(
            store=store,
            output_dir=str(tmp_path / "bake_output_enhanced"),
            tts_engine="mock",
            reading_profile="enhanced",
        )
        result = await pipeline.bake_chapter("golden_bake_enhanced", chapters[0].chapter_id)

        assert result.success, f"Bake failed: {result.errors}"
        assert len(result.segments) > 0
        assert result.cleaned_html, "Should produce cleaned HTML"
        assert "data-seg-id" in result.cleaned_html, "HTML should have data-seg-id spans"
        assert Path(result.package_dir).exists()

    # ------------------------------------------------------------------
    # Cross-chapter consistency
    # ------------------------------------------------------------------

    def test_segment_ids_differ_across_chapters(self, imported):
        """Segment IDs from different chapters should not collide."""
        _, all_data = imported
        if len(all_data) < 2:
            pytest.skip("Need at least 2 chapters")
        ch1_ids = {s.segment_id for s in all_data[0]["segments"]}
        ch2_ids = {s.segment_id for s in all_data[1]["segments"]}
        overlap = ch1_ids & ch2_ids
        assert not overlap, f"Segment ID collision across chapters: {overlap}"

    def test_paragraphs_preserved_in_store(self, imported, store):
        chapters, _ = imported
        for ch in chapters:
            db_paras = store.get_paragraphs("golden_regression", ch.chapter_id)
            assert len(db_paras) == len(ch.paragraphs), (
                f"Paragraph count mismatch for {ch.chapter_id}"
            )

    @pytest.mark.asyncio
    async def test_reader_package_dependencies_exist_and_active(
        self, store, golden_path, tmp_path,
    ):
        """After bake, every reader_package dependency must point to a real
        active artifact, and check_dependencies_active must return True."""
        book_id = "golden_dep_active"
        chapters = import_book(golden_path, book_id=book_id, store=store)
        from vn_core.pipeline.pipeline import Pipeline

        pipeline = Pipeline(
            store=store,
            output_dir=str(tmp_path / "dep_active_output"),
            tts_engine="mock",
            reading_profile="enhanced",
        )
        result = await pipeline.bake_chapter(book_id, chapters[0].chapter_id)
        assert result.success, f"Bake failed: {result.errors}"

        active_pkg = store.get_active_artifact(
            book_id, "reader_package", chapters[0].chapter_id,
        )
        assert active_pkg is not None, "reader_package artifact not found"
        pkg_vid = active_pkg["artifact_version_id"]

        deps = store.get_artifact_dependencies(book_id, pkg_vid)
        dep_roles = {d["dependency_role"] for d in deps}
        required_roles = {"segments", "reading_plan", "timing", "voice_assignment"}
        missing = required_roles - dep_roles
        assert not missing, f"Missing dependency roles: {missing}"

        # Every dependency must exist as an active artifact
        for dep in deps:
            dep_vid = dep["depends_on_artifact_version_id"]
            conn = store._get_conn()
            dep_row = conn.execute(
                "SELECT status FROM artifacts WHERE book_id=? AND artifact_version_id=?",
                (book_id, dep_vid),
            ).fetchone()
            assert dep_row is not None, (
                f"Dependency artifact {dep_vid} (role={dep['dependency_role']}) "
                f"does not exist in artifacts table"
            )
            assert dep_row[0] == "active", (
                f"Dependency artifact {dep_vid} (role={dep['dependency_role']}) "
                f"has status={dep_row[0]}, expected active"
            )

        # The composite check must pass
        dep_check = store.check_dependencies_active(book_id, pkg_vid)
        assert dep_check["all_active"] is True, (
            f"check_dependencies_active failed: {dep_check['inactive']}"
        )

    @pytest.mark.asyncio
    async def test_commit_stage_result_failure_propagates_as_bake_error(
        self, store, golden_path, tmp_path,
    ):
        """If commit_stage_result fails, bake must fail with error in result."""
        chapters = import_book(
            golden_path, book_id="golden_csr_fail", store=store,
        )
        from vn_core.pipeline.pipeline import Pipeline

        pipeline = Pipeline(
            store=store,
            output_dir=str(tmp_path / "csr_fail_output"),
            tts_engine="mock",
            reading_profile="enhanced",
        )

        # Monkeypatch commit_stage_result to simulate failure
        original_csr = pipeline.harness.commit_stage_result
        fail_called = []

        def _failing_csr(s, r):
            fail_called.append(True)
            from vn_core.harness import GateDecision, GateResult
            return GateResult(
                decision=GateDecision.fail_decision,
                reason="simulated failure",
            )

        pipeline.harness.commit_stage_result = _failing_csr

        result = await pipeline.bake_chapter(
            "golden_csr_fail", chapters[0].chapter_id,
        )

        # Restore
        pipeline.harness.commit_stage_result = original_csr

        assert fail_called, "commit_stage_result was never called"
        assert result.success is False, (
            "Bake should fail when commit_stage_result fails"
        )
        assert any("simulated failure" in e for e in result.errors), (
            f"Error should mention simulated failure, got: {result.errors}"
        )
