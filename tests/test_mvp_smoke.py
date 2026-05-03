"""MVP smoke test: shortest publish path from import to download."""

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from vn_server.api import create_app

GOLDEN_BOOK = Path(__file__).parent / "golden_books" / "mountain_inn.txt"


class TestMVPSmoke:
    """End-to-end smoke test covering the demo flow."""

    @staticmethod
    def _make_client(tmp_path):
        data_dir = tmp_path / "data"
        store_path = str(tmp_path / "smoke.sqlite")
        app = create_app(data_dir=str(data_dir), store_path=store_path)
        return TestClient(app)

    def test_full_publish_path(self, tmp_path):
        c = self._make_client(tmp_path)

        # 1. Import sample book
        r = c.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "smoke",
        })
        assert r.status_code == 200, r.text
        assert r.json()["book_id"] == "smoke"

        # 2. Cold-start ch001 → playable buffer
        r = c.post("/api/projects/smoke/chapters/ch001/cold-start")
        assert r.status_code == 200, r.text
        cs = r.json()
        assert cs["playable"] is True
        assert cs["segments_count"] > 0

        # 3. Buffer content/timing/audio/manifest all 200
        buf = c.get("/api/projects/smoke/chapters/ch001/buffer")
        assert buf.status_code == 200, buf.text
        assert buf.json()["package_kind"] == "buffer"

        for asset in ("content", "timing", "manifest", "audio"):
            r = c.get(f"/api/projects/smoke/chapters/ch001/buffer/{asset}")
            assert r.status_code == 200, (
                f"Buffer {asset} must return 200, got {r.status_code}: {r.text[:200]}"
            )

        # 4. Full bake → reader_package ready
        r = c.post("/api/bake", json={
            "book_id": "smoke", "chapter_id": "ch001",
        })
        assert r.status_code == 200, r.text
        bake_result = r.json()
        assert bake_result["success"] is True

        # 5. Station shows full_package ready
        station = c.get("/api/projects/smoke/station")
        assert station.status_code == 200
        ch1 = station.json()["chapters"][0]
        assert ch1["full_package"]["status"] == "ready", (
            f"full_package must be ready. Got: {ch1['full_package']}"
        )

        # 6. Export DAW
        r = c.post("/api/projects/smoke/chapters/ch001/exports?format=daw")
        assert r.status_code == 200, r.text
        exp = r.json()
        assert exp["format"] == "daw"
        vid = exp["artifact_version_id"]
        assert Path(exp["output_dir"]).exists()

        # 7. Export metadata
        r = c.get(f"/api/projects/smoke/exports/{vid}")
        assert r.status_code == 200, r.text
        assert r.json()["downloadable"] is True

        # 8. Download ZIP and verify content
        dl = c.get(f"/api/projects/smoke/exports/{vid}/download")
        assert dl.status_code == 200, dl.text
        assert dl.headers.get("content-type", "").startswith("application/zip")

        bio = io.BytesIO(dl.content)
        with zipfile.ZipFile(bio, "r") as zf:
            names = set(zf.namelist())
            expected = {"project.json", "markers.json", "regions.json", "cue_sheet.txt"}
            missing = expected - names
            assert not missing, f"ZIP missing: {missing}. Contains: {names}"
            for name in expected:
                assert zf.getinfo(name).file_size > 0, f"{name} is empty"

        # 9. Preflight: export should be ok now
        r = c.post("/api/projects/smoke/chapters/ch001/preflight", json={
            "operation": "export", "generation_config_id": "default", "format": "daw",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_preflight_unknown_format_blocks_ok(self, tmp_path):
        """Preflight export with unknown format must set ok=false."""
        c = self._make_client(tmp_path)
        c.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "smoke2",
        })
        c.post("/api/bake", json={
            "book_id": "smoke2", "chapter_id": "ch001",
        })
        r = c.post("/api/projects/smoke2/chapters/ch001/preflight", json={
            "operation": "export", "format": "unknown_fmt",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False, (
            f"ok must be false for unknown format, got {data}"
        )
        assert any("format" in e.lower() for e in data["blocking_errors"]), (
            f"blocking_errors must mention format: {data['blocking_errors']}"
        )

    def test_preflight_runtime_checks_present(self, tmp_path):
        """Preflight includes LLM gateway and TTS engine checks."""
        c = self._make_client(tmp_path)
        c.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "smoke3",
        })
        r = c.post("/api/projects/smoke3/chapters/ch001/preflight", json={
            "operation": "bake",
        })
        assert r.status_code == 200
        checks = {c_["name"]: c_ for c_ in r.json()["checks"]}
        assert "llm_gateway" in checks, f"llm_gateway check missing. Checks: {list(checks)}"
        assert "tts_engine" in checks, f"tts_engine check missing. Checks: {list(checks)}"
        # Mock should pass
        assert checks["llm_gateway"]["status"] == "pass"
        assert checks["tts_engine"]["status"] == "pass"

    def test_preflight_mock_config_passes(self, tmp_path):
        """Mock LLM/TTS config returns pass without 500."""
        c = self._make_client(tmp_path)
        c.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "smoke4",
        })
        # Update to a valid config with mock
        c.post("/api/projects/smoke4/generation-config", json={
            "generation_config_id": "default",
            "tts_engine": "mock",
            "reading_profile": "enhanced",
            "execution_mode": "balanced",
        })
        r = c.post("/api/projects/smoke4/chapters/ch001/preflight", json={
            "operation": "bake",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        # TTS engine check should pass
        tts_check = next(
            c_ for c_ in data["checks"] if c_["name"] == "tts_engine"
        )
        assert tts_check["status"] == "pass", (
            f"mock TTS should pass. Got: {tts_check}"
        )

    def test_export_real_endpoint_still_400_unknown_format(self, tmp_path):
        """Real export endpoint still returns 400 for unknown format."""
        c = self._make_client(tmp_path)
        c.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "smoke5",
        })
        c.post("/api/bake", json={
            "book_id": "smoke5", "chapter_id": "ch001",
        })
        r = c.post("/api/projects/smoke5/chapters/ch001/exports?format=unknown")
        assert r.status_code == 400, r.text
