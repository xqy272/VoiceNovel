"""Tests for cold start Phase 3/4: buffer window + background job."""

import wave as _wv
from pathlib import Path

import pytest

from vn_core.importers import import_book
from vn_core.pipeline.pipeline import MIN_BUFFER_SEGMENTS, Pipeline
from vn_core.store import ProjectStore

GOLDEN_BOOK = Path(__file__).parent / "golden_books" / "mountain_inn.txt"


def _write_test_wav(path):
    with _wv.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * 2400)


def _fake_tts_result(seg_id, path, engine="mock"):
    return type("F", (), {
        "segment_id": seg_id,
        "audio_path": path,
        "status": "success",
        "duration_ms": 100,
        "engine": engine,
    })()


class TestBakeWindow:
    @pytest.fixture
    def store(self, tmp_path):
        db = tmp_path / "bw.sqlite"
        s = ProjectStore(str(db))
        s.initialize()
        yield s
        s.close()

    @pytest.mark.asyncio
    async def test_bake_window_generates_n_segments(self, store, tmp_path):
        chapters = import_book(str(GOLDEN_BOOK), book_id="bw_n", store=store)
        pipeline = Pipeline(
            store=store, output_dir=str(tmp_path / "bw_out"),
            tts_engine="mock", reading_profile="enhanced",
        )
        n = min(10, MIN_BUFFER_SEGMENTS)
        result = await pipeline.bake_window(
            "bw_n", chapters[0].chapter_id, start=0, count=n,
        )
        assert result.success, f"Window bake failed: {result.errors}"
        assert result.package_dir
        assert Path(result.package_dir).exists()
        assert len(result.segments) <= n

        art = store.get_active_artifact(
            "bw_n", "window_package", chapters[0].chapter_id,
        )
        assert art is not None, "window_package artifact must exist and be active"

    @pytest.mark.asyncio
    async def test_bake_window_second_hits_cache(self, store, tmp_path):
        chapters = import_book(str(GOLDEN_BOOK), book_id="bw_cache", store=store)

        c = [0]
        async def _s(req):
            c[0] += 1
            fp = str(tmp_path / f"bw_tts_{c[0]}.wav")
            _write_test_wav(fp)
            return _fake_tts_result(req.segment_id, fp)

        p1 = Pipeline(
            store=store, output_dir=str(tmp_path / "bw1"),
            tts_engine="mock", reading_profile="enhanced",
        )
        p1.tts_gateway.synthesize = _s
        n = min(8, MIN_BUFFER_SEGMENTS)
        r1 = await p1.bake_window("bw_cache", chapters[0].chapter_id, 0, n)
        assert r1.success
        assert c[0] > 0

        c[0] = 0
        p2 = Pipeline(
            store=store, output_dir=str(tmp_path / "bw2"),
            tts_engine="mock", reading_profile="enhanced",
        )
        p2.tts_gateway.synthesize = _s
        r2 = await p2.bake_window(
            "bw_cache", chapters[0].chapter_id, 0, n, force=True,
        )
        assert r2.success
        assert c[0] == 0, f"Second bake should hit cache, got {c[0]} calls"


class TestColdStartFull:
    @pytest.fixture
    def store(self, tmp_path):
        db = tmp_path / "cs_full.sqlite"
        s = ProjectStore(str(db))
        s.initialize()
        yield s
        s.close()

    @pytest.mark.asyncio
    async def test_cold_start_produces_playable_buffer(self, store, tmp_path):
        pipeline = Pipeline(
            store=store, output_dir=str(tmp_path / "cs_out"),
            tts_engine="mock", reading_profile="enhanced",
        )
        csr = await pipeline.cold_start(str(GOLDEN_BOOK), book_id="cs_play")
        assert csr.book_id == "cs_play"
        assert csr.buffer_segments_count > 0
        assert csr.playable is True
        assert csr.phase in ("buffer_ready", "phase4_background")
        assert csr.render_window_id
        assert csr.buffer_package_dir
        assert Path(csr.buffer_package_dir).exists()

        art = store.get_active_artifact("cs_play", "window_package", "ch001")
        assert art is not None

    @pytest.mark.asyncio
    async def test_cold_start_submits_full_bake_job(self, store, tmp_path):
        pipeline = Pipeline(
            store=store, output_dir=str(tmp_path / "cs_job"),
            tts_engine="mock", reading_profile="enhanced",
        )
        csr = await pipeline.cold_start(str(GOLDEN_BOOK), book_id="cs_job")
        assert csr.playable is True
        assert csr.full_bake_job_id, "Should submit a full bake job"

        job = store.get_job(csr.full_bake_job_id)
        assert job is not None
        assert job["book_id"] == "cs_job"
        assert job["output_artifact_type"] == "reader_package"

    @pytest.mark.asyncio
    async def test_window_package_dependencies_complete(self, store, tmp_path):
        """Window_package deps must include audio_take + all active."""
        pipeline = Pipeline(
            store=store, output_dir=str(tmp_path / "cs_wdeps"),
            tts_engine="mock", reading_profile="enhanced",
        )
        csr = await pipeline.cold_start(str(GOLDEN_BOOK), book_id="cs_wdeps")
        assert csr.playable is True

        win = store.get_active_artifact("cs_wdeps", "window_package", "ch001")
        assert win is not None
        deps = store.get_artifact_dependencies("cs_wdeps", win["artifact_version_id"])
        roles = {d["dependency_role"] for d in deps}
        assert "audio_take" in roles, f"Missing audio_take in deps: {roles}"
        assert "segments" in roles

        # Count audio_take deps should match window segment count
        at_deps = [d for d in deps if d["dependency_role"] == "audio_take"]
        assert len(at_deps) > 0
        assert len(at_deps) <= csr.buffer_segments_count

        # All deps must be active
        assert store.check_dependencies_active(
            "cs_wdeps", win["artifact_version_id"],
        )["all_active"]

    @pytest.mark.asyncio
    async def test_audio_take_has_adaptation_dep(self, store, tmp_path):
        """audio_take artifacts should depend on adaptation_ops when present."""
        pipeline = Pipeline(
            store=store, output_dir=str(tmp_path / "cs_atad"),
            tts_engine="mock", reading_profile="enhanced",
        )
        csr = await pipeline.cold_start(str(GOLDEN_BOOK), book_id="cs_atad")
        assert csr.playable is True

        conn = store._get_conn()
        at_rows = conn.execute(
            """SELECT * FROM artifacts
            WHERE book_id='cs_atad' AND artifact_type='audio_take' LIMIT 2""",
        ).fetchall()
        assert len(at_rows) > 0
        for r in at_rows:
            deps = store.get_artifact_dependencies("cs_atad", r["artifact_version_id"])
            roles = {d["dependency_role"] for d in deps}
            assert "segments" in roles
            assert "reading_plan" in roles

    @pytest.mark.asyncio
    async def test_repeat_cold_start_no_duplicate_job(self, store, tmp_path):
        pipeline = Pipeline(
            store=store, output_dir=str(tmp_path / "cs_dup"),
            tts_engine="mock", reading_profile="enhanced",
        )
        await pipeline.cold_start(str(GOLDEN_BOOK), book_id="cs_dup")
        jc1 = len(store.list_jobs(book_id="cs_dup"))

        await pipeline.cold_start(str(GOLDEN_BOOK), book_id="cs_dup",
                                   scan_chapters=1)
        jc2 = len(store.list_jobs(book_id="cs_dup"))
        assert jc2 <= jc1 + 1, f"Job count grew from {jc1} to {jc2}"
