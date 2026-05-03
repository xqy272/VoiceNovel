"""API-level tests for cold-start, buffer endpoints, and partial TTS."""

from pathlib import Path

import pytest

from vn_core.importers import import_book
from vn_core.pipeline.pipeline import MIN_BUFFER_SEGMENTS, Pipeline
from vn_core.store import ProjectStore

GOLDEN_BOOK = Path(__file__).parent / "golden_books" / "mountain_inn.txt"


class TestColdStartAPI:
    @pytest.fixture
    def client(self, tmp_path):
        from fastapi.testclient import TestClient

        from vn_server.api import create_app
        data_dir = tmp_path / "data"
        store_path = str(tmp_path / "cs_api.sqlite")
        app = create_app(data_dir=str(data_dir), store_path=store_path)
        return TestClient(app)

    @pytest.fixture
    def golden(self):
        return GOLDEN_BOOK

    def test_cold_start_playable_true(self, client, golden):
        client.post("/api/projects", json={
            "source_path": str(golden), "book_id": "cs_play",
        })
        resp = client.post("/api/projects/cs_play/chapters/ch001/cold-start")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("playable") is True, f"Got playable=False: {data}"
        assert data.get("buffer_package_dir")
        assert data.get("render_window_id")

    def test_buffer_endpoints_200(self, client, golden):
        client.post("/api/projects", json={
            "source_path": str(golden), "book_id": "cs_bf2",
        })
        client.post("/api/projects/cs_bf2/chapters/ch001/cold-start")

        buf = client.get("/api/projects/cs_bf2/chapters/ch001/buffer")
        assert buf.status_code == 200, buf.text
        bd = buf.json()
        assert bd["status"] in ("buffer_ready", "full_ready")
        assert bd["content_url"]

        c = client.get(bd["content_url"])
        assert c.status_code == 200
        assert "data-seg-id" in c.text

        t = client.get(bd["timing_url"])
        assert t.status_code == 200
        assert len(t.json()) > 0

        a = client.get(bd["audio_url"])
        assert a.status_code == 200
        assert a.headers["content-type"].startswith("audio/")

        m = client.get(bd["manifest_url"])
        assert m.status_code == 200, f"Manifest failed: {m.text}"
        md = m.json()
        assert "book_id" in md or "package_version" in md

    def test_render_windows_endpoint(self, client, golden):
        client.post("/api/projects", json={
            "source_path": str(golden), "book_id": "cs_rw2",
        })
        client.post("/api/projects/cs_rw2/chapters/ch001/cold-start")

        rw = client.get("/api/projects/cs_rw2/chapters/ch001/render-windows")
        assert rw.status_code == 200
        data = rw.json()
        assert len(data["windows"]) >= 1
        win = data["windows"][0]
        assert "window_id" in win
        assert "segment_ids" in win


class TestPartialTTS:
    @pytest.fixture
    def store(self, tmp_path):
        db = tmp_path / "bw_part.sqlite"
        s = ProjectStore(str(db))
        s.initialize()
        yield s
        s.close()

    @pytest.mark.asyncio
    async def test_partial_tts_bake_window_fails(self, store, tmp_path):
        chapters = import_book(str(GOLDEN_BOOK), book_id="bw_part", store=store)
        pipeline = Pipeline(
            store=store, output_dir=str(tmp_path / "bw_part_out"),
            tts_engine="mock", reading_profile="enhanced",
        )

        c = [0]
        orig_synth = pipeline.tts_gateway.synthesize

        async def _partial(req):
            c[0] += 1
            if c[0] % 2 == 0:
                raise RuntimeError("simulated TTS failure")
            return await orig_synth(req)

        pipeline.tts_gateway.synthesize = _partial

        n = min(8, MIN_BUFFER_SEGMENTS)
        result = await pipeline.bake_window("bw_part", chapters[0].chapter_id, 0, n)
        assert result.success is False, f"Errors: {result.errors}"
        assert any("incomplete" in e.lower() for e in result.errors)

        art = store.get_active_artifact(
            "bw_part", "window_package", chapters[0].chapter_id,
        )
        assert art is None, "No playable window_package after partial TTS"


class TestDedupFullJob:
    @pytest.fixture
    def store(self, tmp_path):
        db = tmp_path / "dedup.sqlite"
        s = ProjectStore(str(db))
        s.initialize()
        yield s
        s.close()

    @pytest.mark.asyncio
    async def test_no_job_when_full_package_exists(self, store, tmp_path):
        """If full reader_package already active, don't submit bake job."""
        chapters = import_book(str(GOLDEN_BOOK), book_id="dedup_full", store=store)
        # Bake full package first
        pipeline = Pipeline(
            store=store, output_dir=str(tmp_path / "dedup_full_out"),
            tts_engine="mock", reading_profile="enhanced",
        )
        await pipeline.bake_chapter("dedup_full", chapters[0].chapter_id)

        job_count_before = len(store.list_jobs(book_id="dedup_full"))
        await pipeline.cold_start_existing("dedup_full", chapters[0].chapter_id)
        job_count_after = len(store.list_jobs(book_id="dedup_full"))
        assert job_count_after == job_count_before, (
            "Should not submit job when full package already exists"
        )
