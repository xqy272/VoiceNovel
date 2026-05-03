"""Tests for audio_take cache integration."""

import os
import wave
from pathlib import Path

import pytest

from vn_core.pipeline.pipeline import Pipeline
from vn_core.store import ProjectStore


def _make_test_wav(filepath):
    """Write a minimal WAV file for testing."""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with wave.open(filepath, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * 2400)


class TestAudioTakeCacheE2E:
    """End-to-end tests: verify idempotent commits enable cache reuse."""

    @pytest.fixture
    def store(self, tmp_path):
        db = tmp_path / "at_e2e.sqlite"
        s = ProjectStore(str(db))
        s.initialize()
        yield s
        s.close()

    @pytest.mark.asyncio
    async def test_force_bake_hits_audio_take_cache(self, store, tmp_path):
        """Two force bakes with identical content — second must reuse audio_take."""
        from vn_core.importers import import_book

        golden = Path(__file__).parent / "golden_books" / "mountain_inn.txt"
        chapters = import_book(str(golden), book_id="cache_hit_e2e", store=store)

        tts_call_count = 0

        async def _counting_synth(request):
            nonlocal tts_call_count
            tts_call_count += 1
            fpath = str(tmp_path / f"tts_{tts_call_count}.wav")
            _make_test_wav(fpath)
            return type("FakeTTS", (), {
                "segment_id": request.segment_id,
                "audio_path": fpath,
                "status": "success",
                "duration_ms": 100,
                "engine": "mock",
            })()

        events = []

        p1 = Pipeline(
            store=store,
            output_dir=str(tmp_path / "b1"),
            tts_engine="mock",
            reading_profile="enhanced",
        )
        p1.tts_gateway.synthesize = _counting_synth
        r1 = await p1.bake_chapter(
            "cache_hit_e2e", chapters[0].chapter_id, force=True,
        )
        assert r1.success, f"Bake 1 failed: {r1.errors}"
        first_calls = tts_call_count
        assert first_calls > 0, "First bake should call TTS"

        tts_call_count = 0
        p2 = Pipeline(
            store=store,
            output_dir=str(tmp_path / "b2"),
            tts_engine="mock",
            reading_profile="enhanced",
        )
        p2.tts_gateway.synthesize = _counting_synth
        p2.on_progress(lambda t, d: events.append(t))
        r2 = await p2.bake_chapter(
            "cache_hit_e2e", chapters[0].chapter_id, force=True,
        )
        assert r2.success, f"Bake 2 failed: {r2.errors}"

        assert tts_call_count == 0, (
            f"Second bake TTS calls ({tts_call_count}) should be 0"
        )
        assert "tts_cache_hit" in events, (
            f"No tts_cache_hit event. Events: {events}"
        )

        # Verify reused audio_take deps are all active
        conn = store._get_conn()
        at_rows = conn.execute(
            "SELECT artifact_version_id FROM artifacts "
            "WHERE book_id='cache_hit_e2e' AND artifact_type='audio_take'",
        ).fetchall()
        for r in at_rows:
            deps_ok = store.check_dependencies_active(
                "cache_hit_e2e", r["artifact_version_id"],
            )
            assert deps_ok["all_active"], f"Deps not active for {r['artifact_version_id']}"

    @pytest.mark.asyncio
    async def test_engine_change_causes_cache_miss(self, store, tmp_path):
        """Changing TTS engine must invalidate cache."""
        from vn_core.importers import import_book

        golden = Path(__file__).parent / "golden_books" / "mountain_inn.txt"
        chapters = import_book(str(golden), book_id="voice_miss", store=store)

        count1 = 0
        count2 = 0

        async def _synth1(request):
            nonlocal count1
            count1 += 1
            fpath = str(tmp_path / f"vm_tts1_{count1}.wav")
            _make_test_wav(fpath)
            return type("Fake", (), {
                "segment_id": request.segment_id,
                "audio_path": fpath,
                "status": "success",
                "duration_ms": 100,
                "engine": "mock",
            })()

        async def _synth2(request):
            nonlocal count2
            count2 += 1
            fpath = str(tmp_path / f"vm_tts2_{count2}.wav")
            _make_test_wav(fpath)
            return type("Fake", (), {
                "segment_id": request.segment_id,
                "audio_path": fpath,
                "status": "success",
                "duration_ms": 100,
                "engine": "edge_tts",
            })()

        p1 = Pipeline(
            store=store,
            output_dir=str(tmp_path / "vm1"),
            tts_engine="mock",
            reading_profile="enhanced",
        )
        p1.tts_gateway.synthesize = _synth1
        await p1.bake_chapter("voice_miss", chapters[0].chapter_id, force=True)
        assert count1 > 0

        p2 = Pipeline(
            store=store,
            output_dir=str(tmp_path / "vm2"),
            tts_engine="edge_tts",
            reading_profile="enhanced",
        )
        p2.tts_gateway.synthesize = _synth2
        await p2.bake_chapter("voice_miss", chapters[0].chapter_id, force=True)
        assert count2 > 0, "Different engine should cause cache miss"

    @pytest.mark.asyncio
    async def test_same_content_no_new_artifact_versions(self, store, tmp_path):
        """Second force bake with identical content must NOT create new versions."""
        from vn_core.importers import import_book

        golden = Path(__file__).parent / "golden_books" / "mountain_inn.txt"
        chapters = import_book(str(golden), book_id="no_new_ver", store=store)

        async def _synth(request):
            fpath = str(tmp_path / f"t_{request.segment_id}.wav")
            _make_test_wav(fpath)
            return type("F", (), {
                "segment_id": request.segment_id,
                "audio_path": fpath,
                "status": "success",
                "duration_ms": 100,
                "engine": "mock",
            })()

        p1 = Pipeline(
            store=store, output_dir=str(tmp_path / "nv1"),
            tts_engine="mock", reading_profile="enhanced",
        )
        p1.tts_gateway.synthesize = _synth
        await p1.bake_chapter("no_new_ver", chapters[0].chapter_id, force=True)

        # Count artifacts after first bake
        def count_at(atype, unit=None):
            conn = store._get_conn()
            if unit:
                return conn.execute(
                    "SELECT COUNT(*) FROM artifacts "
                    "WHERE book_id='no_new_ver' AND artifact_type=? AND unit_id=?",
                    (atype, unit),
                ).fetchone()[0]
            return conn.execute(
                "SELECT COUNT(*) FROM artifacts "
                "WHERE book_id='no_new_ver' AND artifact_type=?",
                (atype,),
            ).fetchone()[0]

        seg_count1 = count_at("segments", chapters[0].chapter_id)
        plan_count1 = count_at("reading_plan", chapters[0].chapter_id)
        at_count1 = count_at("audio_take")

        # Second force bake
        p2 = Pipeline(
            store=store, output_dir=str(tmp_path / "nv2"),
            tts_engine="mock", reading_profile="enhanced",
        )
        p2.tts_gateway.synthesize = _synth
        await p2.bake_chapter("no_new_ver", chapters[0].chapter_id, force=True)

        seg_count2 = count_at("segments", chapters[0].chapter_id)
        plan_count2 = count_at("reading_plan", chapters[0].chapter_id)
        at_count2 = count_at("audio_take")

        assert seg_count2 == seg_count1, (
            f"Segments: {seg_count1} → {seg_count2} (should not increase)"
        )
        assert plan_count2 == plan_count1, (
            f"Reading plan: {plan_count1} → {plan_count2} (should not increase)"
        )
        assert at_count2 == at_count1, (
            f"Audio_takes: {at_count1} → {at_count2} (should not increase)"
        )

    @pytest.mark.asyncio
    async def test_old_audio_takes_not_superseded_on_reuse(self, store, tmp_path):
        """When content matches, old audio_take versions stay active, not superseded."""
        from vn_core.importers import import_book

        golden = Path(__file__).parent / "golden_books" / "mountain_inn.txt"
        chapters = import_book(str(golden), book_id="stay_active", store=store)

        async def _synth(request):
            fpath = str(tmp_path / f"sa_{request.segment_id}.wav")
            _make_test_wav(fpath)
            return type("F", (), {
                "segment_id": request.segment_id,
                "audio_path": fpath,
                "status": "success",
                "duration_ms": 100,
                "engine": "mock",
            })()

        p1 = Pipeline(
            store=store, output_dir=str(tmp_path / "sa1"),
            tts_engine="mock", reading_profile="enhanced",
        )
        p1.tts_gateway.synthesize = _synth
        await p1.bake_chapter("stay_active", chapters[0].chapter_id, force=True)

        # Record the active audio_take artifact versions
        conn = store._get_conn()
        at_vids_1 = {
            r["unit_id"]: r["artifact_version_id"]
            for r in conn.execute(
                "SELECT unit_id, artifact_version_id, status FROM artifacts "
                "WHERE book_id='stay_active' AND artifact_type='audio_take'",
            ).fetchall()
        }

        p2 = Pipeline(
            store=store, output_dir=str(tmp_path / "sa2"),
            tts_engine="mock", reading_profile="enhanced",
        )
        p2.tts_gateway.synthesize = _synth
        await p2.bake_chapter("stay_active", chapters[0].chapter_id, force=True)

        # Same audio_takes should still be active, same versions
        for unit_id, vid in at_vids_1.items():
            row = conn.execute(
                "SELECT artifact_version_id, status FROM artifacts "
                "WHERE book_id='stay_active' AND unit_id=? AND artifact_type='audio_take' "
                "AND status='active'",
                (unit_id,),
            ).fetchone()
            assert row is not None, f"Audio_take for {unit_id} should still be active"
            assert row["artifact_version_id"] == vid, (
                f"Audio_take {unit_id} version changed from {vid} to {row['artifact_version_id']}"
            )

    @pytest.mark.asyncio
    async def test_audio_take_dependencies_exist(self, store, tmp_path):
        """After bake, audio_take artifacts must have real, active deps."""
        from vn_core.importers import import_book

        golden = Path(__file__).parent / "golden_books" / "mountain_inn.txt"
        chapters = import_book(str(golden), book_id="at_dep_test", store=store)

        pipeline = Pipeline(
            store=store,
            output_dir=str(tmp_path / "at_deps"),
            tts_engine="mock",
            reading_profile="enhanced",
        )
        result = await pipeline.bake_chapter(
            "at_dep_test", chapters[0].chapter_id,
        )
        assert result.success, f"Bake failed: {result.errors}"

        conn = store._get_conn()
        at_rows = conn.execute(
            "SELECT artifact_version_id FROM artifacts "
            "WHERE book_id='at_dep_test' AND artifact_type='audio_take'",
        ).fetchall()
        assert len(at_rows) > 0, "No audio_take artifacts created"

        for r in at_rows:
            at_vid = r["artifact_version_id"]
            dep_ok = store.check_dependencies_active("at_dep_test", at_vid)
            assert dep_ok["all_active"], (
                f"Audio_take {at_vid} has inactive deps: {dep_ok['inactive']}"
            )
            deps = store.get_artifact_dependencies("at_dep_test", at_vid)
            for dep in deps:
                dep_row = conn.execute(
                    "SELECT status FROM artifacts "
                    "WHERE book_id='at_dep_test' AND artifact_version_id=?",
                    (dep["depends_on_artifact_version_id"],),
                ).fetchone()
                assert dep_row is not None, (
                    f"Dependency {dep['depends_on_artifact_version_id']} "
                    f"of audio_take {at_vid} does not exist"
                )


class TestAudioTakeCacheStore:
    @pytest.fixture
    def store(self, tmp_path):
        db = tmp_path / "at_store.sqlite"
        s = ProjectStore(str(db))
        s.initialize()
        yield s
        s.close()

    def test_cache_hit_finds_artifact(self, store):
        ck = "test_audio_take_ck_001"
        store.write_artifact(
            "book_001", "at_v001", "audio_take", "ch001_p000_s000",
            file_path="/tmp/audio.wav", input_hash=ck,
        )
        found = store.find_artifact_by_cache_key("book_001", "audio_take", ck)
        assert found is not None
        assert found["artifact_version_id"] == "at_v001"

    def test_cache_miss_different_key(self, store):
        store.write_artifact(
            "book_001", "at_v001", "audio_take", "seg1", input_hash="key_a",
        )
        found = store.find_artifact_by_cache_key("book_001", "audio_take", "key_b")
        assert found is None

    def test_inactive_dependency_causes_cache_miss(self, store):
        ck = "dep_ck_003"
        store.write_artifact(
            "book_001", "at_dep2", "audio_take", "seg1",
            file_path="/tmp/test.wav", input_hash=ck,
        )
        store.write_artifact(
            "book_001", "seg_v1", "segments", "seg1", status="superseded",
        )
        store.add_dependency("book_001", "at_dep2", "seg_v1", "segments")
        found = store.find_artifact_by_cache_key("book_001", "audio_take", ck)
        assert found is not None
        dep_ok = store.check_dependencies_active("book_001", "at_dep2")
        assert dep_ok["all_active"] is False

    def test_missing_file_found(self, store):
        ck = "missing_file_ck"
        store.write_artifact(
            "book_001", "at_missing", "audio_take", "seg1",
            file_path="/nonexistent/path.wav", input_hash=ck,
        )
        found = store.find_artifact_by_cache_key("book_001", "audio_take", ck)
        assert found is not None
        assert not os.path.exists("/nonexistent/path.wav")
