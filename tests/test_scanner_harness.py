"""Tests for scanner Harness control plane (Part A)."""

import json

import pytest

from vn_core.harness import GateDecision, HarnessGate
from vn_core.store import ProjectStore


class TestCommitScanResult:
    @pytest.fixture
    def store(self, tmp_path):
        db = tmp_path / "scanner_harness.sqlite"
        s = ProjectStore(str(db))
        s.initialize()
        yield s
        s.close()

    @pytest.fixture
    def harness(self):
        return HarnessGate()

    def test_characters_committed(self, harness, store):
        result = harness.commit_scan_result(
            store, "book_001", "ch001",
            characters=[
                {"name": "陆明", "aliases": ["少主"],
                 "traits": ["male", "young"], "first_seen": "ch001"},
                {"name": "林晚", "aliases": ["林姑娘"],
                 "traits": ["female"], "first_seen": "ch001"},
            ],
        )
        assert result.decision == GateDecision.pass_decision, result.reason

        chars = store.get_characters("book_001")
        names = {json.loads(c["names"])[0] for c in chars}
        assert "陆明" in names
        assert "林晚" in names

    def test_glossary_committed(self, harness, store):
        result = harness.commit_scan_result(
            store, "book_001", "ch001",
            glossary_terms=[
                {"term": "剑法", "definition": "sword technique",
                 "category": "skill"},
            ],
        )
        assert result.decision == GateDecision.pass_decision, result.reason

    def test_empty_scan_passes(self, harness, store):
        result = harness.commit_scan_result(store, "book_001", "ch001")
        assert result.decision == GateDecision.pass_decision

    def test_missing_name_fails(self, harness, store):
        result = harness.commit_scan_result(
            store, "book_001", "ch001",
            characters=[{"traits": ["male"]}],  # no name
        )
        assert result.decision == GateDecision.fail_decision
        assert "name" in result.reason.lower()

        # Verify nothing was committed
        chars = store.get_characters("book_001")
        assert chars == []

    def test_provenance_exists(self, harness, store):
        harness.commit_scan_result(
            store, "book_001", "ch001",
            characters=[{"name": "test_char"}],
        )
        conn = store._get_conn()
        row = conn.execute(
            "SELECT * FROM provenance WHERE stage='scanner'",
        ).fetchone()
        assert row is not None
        assert dict(row)["unit_id"] == "ch001"

    @pytest.mark.asyncio
    async def test_existing_scanner_test_still_passes(self, store):
        """Regression: the old scanner test flow still works via Store."""
        from vn_core.llm_gateway import LLMGateway
        from vn_core.scanner import BookScanner

        scanner = BookScanner(LLMGateway(), store)
        result = await scanner._extract_characters(
            "book_001", "ch001",
            "陆明背着包走来。林晚站在门口。",
        )
        assert isinstance(result, dict)
        assert "characters" in result
