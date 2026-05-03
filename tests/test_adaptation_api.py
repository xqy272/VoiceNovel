"""Tests for adaptation rollback HTTP API (Part C)."""

import json
import os

import pytest
from fastapi.testclient import TestClient

from vn_server.api import create_app


@pytest.fixture
def client(tmp_path):
    data_dir = tmp_path / "data"
    store_path = str(tmp_path / "adapt_api.sqlite")
    app = create_app(data_dir=str(data_dir), store_path=store_path)
    return TestClient(app)


class TestAdaptationOpsAPI:
    def test_list_ops_empty(self, client):
        # Import a book first so the book exists
        from pathlib import Path
        golden = Path(__file__).parent / "golden_books" / "mountain_inn.txt"
        resp = client.post("/api/projects", json={
            "source_path": str(golden), "book_id": "adapt_api_test",
        })
        assert resp.status_code == 200, resp.text

        resp2 = client.get(
            "/api/projects/adapt_api_test/chapters/ch001/adaptation-ops",
        )
        assert resp2.status_code == 200

    def test_replay_display_excludes_tts_only(self, client):
        from pathlib import Path
        golden = Path(__file__).parent / "golden_books" / "mountain_inn.txt"
        client.post("/api/projects", json={
            "source_path": str(golden), "book_id": "adapt_replay",
        })

        ops = [
            {"op_id": "op1", "segment_id": "s1", "original": "2024年",
             "normalized": "2 0 2 4 年", "scope": "tts_only"},
            {"op_id": "op2", "segment_id": "s1", "original": "　",
             "normalized": " ", "scope": "display_and_tts"},
        ]
        resp = client.post(
            "/api/projects/adapt_replay/chapters/ch001/adaptation-ops/replay",
            json={"source_text": "2024年　test", "ops": ops, "scope": "display_and_tts"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # tts_only op NOT applied
        assert "2024年" in data["text"]
        assert "2 0 2 4 年" not in data["text"]

    def test_diff_endpoint(self, client):
        from pathlib import Path
        golden = Path(__file__).parent / "golden_books" / "mountain_inn.txt"
        client.post("/api/projects", json={
            "source_path": str(golden), "book_id": "adapt_diff",
        })

        resp = client.post(
            "/api/projects/adapt_diff/chapters/ch001/adaptation-ops/diff",
            json={"before": "abc", "after": "adc"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "changes" in data
        assert data["before"] == "abc"
        assert data["after"] == "adc"

    def test_rollback_with_valid_ops_succeeds(self, tmp_path):
        """End-to-end rollback: write ops -> rollback -> verify new artifact."""
        from pathlib import Path

        from vn_core.adaptation import TextAdapter

        # Use a single store for both setup and API
        data_dir = tmp_path / "data_rb"
        store_path = str(tmp_path / "rb_shared.sqlite")
        app = create_app(data_dir=str(data_dir), store_path=store_path)
        shared_client = TestClient(app)

        book_id = "adapt_rb_ok"
        golden = Path(__file__).parent / "golden_books" / "mountain_inn.txt"
        shared_client.post("/api/projects", json={
            "source_path": str(golden), "book_id": book_id,
        })

        # Get the app's store to write ops
        from vn_core.store import ProjectStore
        rb_store = ProjectStore(store_path)

        adapter = TextAdapter()
        result = adapter.adapt_pre_segment("ch001_p000_pre", "Hello  world...")
        rb_store.write_text_adaptation_ops(book_id, "ch001", result.operations)

        decision_rows = rb_store.get_text_adaptation_ops(book_id, unit_id="ch001")
        assert len(decision_rows) > 0
        raw = decision_rows[0].get("value", {})
        op_id = raw.get("op_id", "")
        assert op_id, f"No op_id in stored op: {raw}"

        resp = shared_client.post(
            f"/api/projects/{book_id}/chapters/ch001/adaptation-ops/rollback",
            json={"op_ids": [op_id], "reason": "test rollback"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "artifact_version_id" in data
        assert op_id in data["rolled_back_op_ids"]

        # Verify new artifact exists, is active, and has file_path
        conn = rb_store._get_conn()
        art = conn.execute(
            "SELECT * FROM artifacts WHERE artifact_version_id=?",
            (data["artifact_version_id"],),
        ).fetchone()
        assert art is not None
        assert art["status"] == "active"
        assert art["file_path"], "artifact must have file_path"
        assert os.path.exists(art["file_path"]), f"file not found: {art['file_path']}"

        # Verify file content is raw ops (list of dicts), not decision rows
        file_content = json.loads(Path(art["file_path"]).read_text(encoding="utf-8"))
        assert isinstance(file_content, list)
        assert len(file_content) > 0
        assert "op_id" in file_content[0], "File content should be raw ops with op_id"

        # Verify decisions are queryable (rollback ops persisted as decisions)
        new_decisions = rb_store.get_text_adaptation_ops(book_id, unit_id="ch001")
        rollback_ops = [
            d for d in new_decisions
            if "rollback" in str(d.get("value", {}).get("op_id", ""))
        ]
        assert len(rollback_ops) > 0, (
            f"Rollback ops not found in decisions. Got: {new_decisions}"
        )

        # Verify replay works on the new ops
        from vn_core.adaptation import replay_adaptation_ops
        text, _ = replay_adaptation_ops("Hello  world...", file_content)
        assert isinstance(text, str)
        rb_store.close()

    def test_rollback_without_ops_returns_404(self, client):
        from pathlib import Path
        golden = Path(__file__).parent / "golden_books" / "mountain_inn.txt"
        book_id = "adapt_rb_404"
        client.post("/api/projects", json={
            "source_path": str(golden), "book_id": book_id,
        })
        resp = client.post(
            f"/api/projects/{book_id}/chapters/ch001/adaptation-ops/rollback",
            json={"op_ids": ["nonexistent"], "reason": "test"},
        )
        assert resp.status_code == 404

    def test_malformed_stored_op_does_not_500(self, tmp_path):
        """A malformed op must return 422, never 500."""
        from pathlib import Path
        data_dir = tmp_path / "data_mal3"
        store_path = str(tmp_path / "mal_shared3.sqlite")

        book_id = "adapt_mal3"
        golden = Path(__file__).parent / "golden_books" / "mountain_inn.txt"

        # Write malformed op BEFORE creating the app, using the same DB file.
        # segment_id MUST start with ch001_ so get_text_adaptation_ops(unit_id='ch001') finds it.
        import sqlite3
        conn = sqlite3.connect(store_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS decisions (
            book_id TEXT NOT NULL, segment_id TEXT NOT NULL,
            decision_type TEXT NOT NULL, value TEXT NOT NULL DEFAULT '{}',
            confidence REAL NOT NULL DEFAULT 1.0,
            status TEXT NOT NULL DEFAULT 'inferred',
            user_locked INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT '',
            evidence TEXT NOT NULL DEFAULT '[]',
            created_by TEXT NOT NULL DEFAULT '',
            run_id TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (book_id, segment_id, decision_type))""")
        conn.execute(
            "INSERT INTO decisions (book_id, segment_id, decision_type, value) "
            "VALUES (?, ?, ?, ?)",
            (book_id, "ch001_p999_s999", "text_adaptation:broken_op",
             '{"op_id": "broken_op", "some_field": "no_original_or_normalized"}'),
        )
        conn.commit()
        conn.close()

        # Now create app pointing at the same store
        app = create_app(data_dir=str(data_dir), store_path=store_path)
        shared_client = TestClient(app)
        shared_client.post("/api/projects", json={
            "source_path": str(golden), "book_id": book_id,
        })

        resp = shared_client.post(
            f"/api/projects/{book_id}/chapters/ch001/adaptation-ops/rollback",
            json={"op_ids": ["broken_op"], "reason": "test"},
        )
        assert resp.status_code == 422, (
            f"Expected 422, got {resp.status_code}: {resp.text}"
        )
        detail = resp.json().get("detail", "")
        assert "warnings" in detail.lower() or "valid" in detail.lower(), (
            f"422 detail should mention malformed op reason: {detail}"
        )


class TestAdaptationAPIRegression:
    """Verify full bake still works after adding adaptation API."""

    def test_bake_still_works(self, client):
        from pathlib import Path
        golden = Path(__file__).parent / "golden_books" / "mountain_inn.txt"
        client.post("/api/projects", json={
            "source_path": str(golden), "book_id": "bake_after_api",
        })
        resp = client.post("/api/bake", json={
            "book_id": "bake_after_api", "chapter_id": "ch001",
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("success") is True, data.get("errors", [])
