"""Tests for adaptation replay, diff, rollback, and scope isolation."""

import pytest

from vn_core.adaptation import (
    TextAdapter,
    diff_text,
    replay_adaptation_ops,
    replay_display_text,
    replay_tts_text,
    rollback_adaptation_ops,
)
from vn_core.store import ProjectStore


class TestReplayAdaptationOps:
    def test_replay_basic(self):
        ops = [
            {"op_id": "op1", "segment_id": "s1", "original": "2024年",
             "normalized": "2 0 2 4 年", "scope": "tts_only",
             "category": "tts_normalization"},
        ]
        text, warnings = replay_adaptation_ops("2024年夏天", ops)
        assert text == "2 0 2 4 年夏天"
        assert warnings == []

    def test_replay_no_match_produces_warning(self):
        ops = [
            {"op_id": "op2", "segment_id": "s1", "original": "xyz",
             "normalized": "abc", "scope": "display_and_tts"},
        ]
        text, warnings = replay_adaptation_ops("hello world", ops)
        assert text == "hello world"
        assert len(warnings) == 1
        assert "not found" in warnings[0]

    def test_replay_suggest_only_skipped(self):
        ops = [
            {"op_id": "op3", "segment_id": "s1", "original": "test",
             "normalized": "changed", "scope": "suggest_only"},
        ]
        text, _ = replay_adaptation_ops("test text", ops)
        assert text == "test text"

    def test_replay_skips_malformed_ops(self):
        ops = [
            {"op_id": "ok", "segment_id": "s1", "original": "a",
             "normalized": "b", "scope": "display_and_tts"},
            "not_a_dict",
            {"op_id": "also_ok", "segment_id": "s1", "original": "c",
             "normalized": "d", "scope": "display_and_tts"},
        ]
        text, warnings = replay_adaptation_ops("a text c", ops)
        assert "b" in text
        assert "d" in text
        assert len(warnings) >= 1

    def test_display_replay_excludes_tts_only(self):
        ops = [
            {"op_id": "d1", "segment_id": "s1", "original": "2024年",
             "normalized": "2 0 2 4 年", "scope": "tts_only"},
            {"op_id": "d2", "segment_id": "s1", "original": "　",
             "normalized": " ", "scope": "display_and_tts"},
        ]
        text, _ = replay_display_text("2024年　text", ops)
        # tts_only op NOT applied
        assert "2024年" in text
        assert "2 0 2 4 年" not in text
        # display op applied
        assert " " in text

    def test_tts_replay_includes_tts_only(self):
        ops = [
            {"op_id": "t1", "segment_id": "s1", "original": "2024年",
             "normalized": "2 0 2 4 年", "scope": "tts_only"},
        ]
        text, _ = replay_tts_text("2024年夏天", ops)
        assert text == "2 0 2 4 年夏天"


class TestDiffText:
    def test_equal_texts(self):
        d = diff_text("hello", "hello")
        assert all(c["kind"] == "equal" for c in d["changes"])

    def test_replacement(self):
        d = diff_text("abc", "adc")
        kinds = {c["kind"] for c in d["changes"]}
        assert "replace" in kinds or "delete" in kinds or "insert" in kinds

    def test_different_lengths(self):
        d = diff_text("short", "short and long")
        assert d["before"] == "short"
        assert d["after"] == "short and long"
        assert len(d["changes"]) > 0

    def test_empty_inputs(self):
        d = diff_text("", "hello")
        assert d["changes"] is not None
        d2 = diff_text("hello", "")
        assert d2["changes"] is not None


class TestRollback:
    def test_rollback_creates_new_ops(self):
        ops = [
            {"op_id": "r1", "segment_id": "s1", "original": "bad",
             "normalized": "good", "scope": "display_and_tts"},
            {"op_id": "r2", "segment_id": "s1", "original": "old",
             "normalized": "new", "scope": "tts_only"},
        ]
        new_ops, text = rollback_adaptation_ops(
            "bad old text", ops, {"r1"}, "test rollback",
        )
        assert len(new_ops) == 2
        # r1 was rolled back (no-op created)
        assert any("rollback" in o.get("op_id", "") for o in new_ops)
        # r2 still applied
        assert "new" in text

    def test_rollback_does_not_delete_history(self):
        ops = [
            {"op_id": "hist1", "segment_id": "s1", "original": "x",
             "normalized": "y", "scope": "display_and_tts"},
        ]
        new_ops, _ = rollback_adaptation_ops("x", ops, {"hist1"}, "undo")
        # Original ops list was not mutated
        assert ops[0]["normalized"] == "y"
        assert len(new_ops) == 1


class TestStoreAdaptationOpsQuery:
    @pytest.fixture
    def store(self, tmp_path):
        db = tmp_path / "adapt_query.sqlite"
        s = ProjectStore(str(db))
        s.initialize()
        yield s
        s.close()

    def test_write_and_read_back_ops(self, store):
        adapter = TextAdapter()
        result = adapter.adapt_pre_segment("s001_pre", "Hello  world...")
        store.write_text_adaptation_ops("book_001", "ch001", result.operations)

        # Query without unit_id filter — ops were written with segment_id from
        # the adaptation call, which starts with "s001_pre", not "ch001".
        ops = store.get_text_adaptation_ops("book_001")
        assert len(ops) > 0

        # Query by specific segment_id should also work
        ops2 = store.get_text_adaptation_ops(
            "book_001", segment_id="s001_pre",
        )
        assert len(ops2) > 0

    def test_empty_result(self, store):
        ops = store.get_text_adaptation_ops("book_001", unit_id="nonexistent")
        assert ops == []
