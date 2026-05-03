"""Tests for preflight API endpoint and cost estimate integration."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vn_server.api import create_app

GOLDEN_BOOK = Path(__file__).parent / "golden_books" / "mountain_inn.txt"


def _pf_post(client, book_id, chapter_id, operation="bake",
             generation_config_id="default", fmt="daw"):
    return client.post(
        f"/api/projects/{book_id}/chapters/{chapter_id}/preflight",
        json={
            "operation": operation,
            "generation_config_id": generation_config_id,
            "format": fmt,
        },
    )


class TestPreflightAPI:
    @pytest.fixture
    def client(self, tmp_path):
        data_dir = tmp_path / "data"
        store_path = str(tmp_path / "pf.sqlite")
        app = create_app(data_dir=str(data_dir), store_path=store_path)
        return TestClient(app)

    def _import(self, client, book_id="pf_test"):
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": book_id,
        })

    # --- success ---

    def test_preflight_bake_ok(self, client):
        self._import(client)
        r = _pf_post(client, "pf_test", "ch001")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert len(data["blocking_errors"]) == 0
        assert data["operation"] == "bake"
        names = {c["name"] for c in data["checks"]}
        assert "chapter_exists" in names
        assert "generation_config" in names
        assert data["estimated_cost"] is not None
        cost = data["estimated_cost"]
        assert cost["segment_count_est"] > 0
        assert "total_cost_usd" in cost

    def test_preflight_cold_start_ok(self, client):
        self._import(client)
        r = _pf_post(client, "pf_test", "ch001", operation="cold_start")
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

    def test_preflight_rebuild_ok(self, client):
        self._import(client)
        r = _pf_post(client, "pf_test", "ch001", operation="rebuild")
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

    # --- blocking errors ---

    def test_preflight_missing_chapter(self, client):
        self._import(client)
        r = _pf_post(client, "pf_test", "ch999")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is False
        assert len(data["blocking_errors"]) >= 1
        assert any("ch999" in e for e in data["blocking_errors"])
        # estimated_cost present but zeroed
        assert data["estimated_cost"]["segment_count_est"] == 0

    def test_preflight_missing_generation_config(self, client):
        self._import(client)
        r = _pf_post(client, "pf_test", "ch001",
                     generation_config_id="missing_cfg")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is False
        assert any("missing_cfg" in e for e in data["blocking_errors"])

    def test_preflight_export_without_package(self, client):
        self._import(client)
        r = _pf_post(client, "pf_test", "ch001", operation="export")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is False
        assert any("reader_package" in e.lower() or "valid" in e.lower()
                   for e in data["blocking_errors"])

    def test_preflight_export_with_package_ok(self, client, tmp_path):
        store_path = str(tmp_path / "pf.sqlite")
        data_dir = str(tmp_path / "data_pf2")
        app = create_app(data_dir=data_dir, store_path=store_path)
        c2 = TestClient(app)
        self._import(c2, "pf_exp")
        c2.post("/api/bake", json={
            "book_id": "pf_exp", "chapter_id": "ch001",
        })
        r = _pf_post(c2, "pf_exp", "ch001", operation="export")
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

    # --- cost estimate ---

    def test_preflight_cost_fields_present(self, client):
        self._import(client)
        r = _pf_post(client, "pf_test", "ch001")
        assert r.status_code == 200
        cost = r.json()["estimated_cost"]
        assert cost is not None
        for field in ("segment_count_est", "tts_total_chars",
                       "total_duration_minutes", "total_cost_usd"):
            assert field in cost, f"Missing cost field: {field}"

    def test_preflight_cost_not_500_when_rate_unavailable(self, client):
        self._import(client)
        r = _pf_post(client, "pf_test", "ch001")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "estimated_cost" in data

    # --- response structure ---

    def test_preflight_response_structure(self, client):
        self._import(client)
        r = _pf_post(client, "pf_test", "ch001")
        assert r.status_code == 200
        data = r.json()
        for key in ("ok", "operation", "book_id", "chapter_id",
                     "checks", "blocking_errors", "warnings", "estimated_cost"):
            assert key in data, f"Missing top-level key: {key}"

    # --- existing 409 behavior preserved ---

    def test_bake_still_rejects_missing_chapter_409(self, client):
        self._import(client)
        r = client.post("/api/bake", json={
            "book_id": "pf_test", "chapter_id": "ch999",
        })
        assert r.status_code == 409, r.text
