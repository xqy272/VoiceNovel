"""Tests for atomic artifact data file writing in commit_stage_result."""

import json
import os
from pathlib import Path

import pytest

from vn_core.contracts.stage_result import StageResult
from vn_core.harness import GateDecision, HarnessGate
from vn_core.store import ProjectStore


@pytest.fixture
def harness():
    return HarnessGate()


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "adat.sqlite"
    s = ProjectStore(str(db))
    s.initialize()
    yield s
    s.close()


class TestArtifactDataAtomic:
    def test_successful_data_artifact(self, harness, store):
        """artifact active; file_path exists; metadata.data_key correct; JSON correct."""
        r = harness.commit_stage_result(store, StageResult(
            stage="test", book_id="b1", unit_id="u1",
            proposed_artifacts=[{
                "artifact_type": "segments",
                "artifact_version_id": "b1_segments_u1_v001",
                "unit_id": "u1",
                "data": [{"op_id": "op1", "text": "hello"}],
                "input_hash": "abc",
            }],
            provenance={"stage": "test", "unit_id": "u1"},
        ))
        assert r.decision == GateDecision.pass_decision, r.reason

        art = store.get_active_artifact("b1", "segments", "u1")
        assert art is not None
        assert art["status"] == "active"
        fp = art["file_path"]
        assert fp, "file_path must be set"
        assert os.path.exists(fp), f"file not found: {fp}"

        meta = json.loads(art.get("metadata", "{}"))
        assert "data_key" in meta
        assert meta["data_key"].endswith(".json")

        content = json.loads(Path(fp).read_text(encoding="utf-8"))
        assert content == [{"op_id": "op1", "text": "hello"}]

    def test_relative_db_path(self, tmp_path):
        """artifact_data is under the store db's parent, even with relative path."""
        cwd = os.getcwd()
        try:
            os.chdir(str(tmp_path))
            store2 = ProjectStore("rel.sqlite")
            store2.initialize()
            harness2 = HarnessGate()

            r = harness2.commit_stage_result(store2, StageResult(
                stage="test", book_id="b_rel", unit_id="u1",
                proposed_artifacts=[{
                    "artifact_type": "segments",
                    "artifact_version_id": "b_rel_seg_v001",
                    "unit_id": "u1",
                    "data": [{"k": "v"}],
                    "input_hash": "x",
                }],
                provenance={"stage": "test", "unit_id": "u1"},
            ))
            assert r.decision == GateDecision.pass_decision, r.reason

            art = store2.get_active_artifact("b_rel", "segments", "u1")
            fp = art["file_path"]
            # Must be inside tmp_path/artifact_data, not at filesystem root
            resolved = os.path.abspath(fp)
            expected_dir = os.path.abspath(str(tmp_path / "artifact_data"))
            assert resolved.startswith(expected_dir), (
                f"Expected file under {expected_dir}, got {resolved}"
            )
            store2.close()
        finally:
            os.chdir(cwd)

    def test_malicious_artifact_version_id(self, harness, store):
        """vid with ../ \\ : chars still stays inside artifact_data."""
        raw_db = getattr(store, "db_path", ".")
        data_dir = os.path.abspath(
            os.path.join(os.path.dirname(os.path.abspath(str(raw_db))), "artifact_data"),
        )
        for bad_vid in ["../escape", "sub\\dir", "a:b", "../../etc_passwd"]:
            r = harness.commit_stage_result(store, StageResult(
                stage="test", book_id="b_mal", unit_id="u1",
                proposed_artifacts=[{
                    "artifact_type": "segments",
                    "artifact_version_id": bad_vid,
                    "unit_id": "u1",
                    "data": [{"x": 1}],
                    "input_hash": "y",
                }],
                provenance={"stage": "test", "unit_id": "u1"},
            ))
            assert r.decision == GateDecision.pass_decision, (
                f"Failed for vid={bad_vid}: {r.reason}"
            )
            art = store.get_active_artifact("b_mal", "segments", "u1")
            fp = os.path.abspath(art["file_path"])
            # File must be inside artifact_data directory
            assert fp.startswith(data_dir + os.sep), (
                f"Path escaped artifact_data: {fp}"
            )
            assert os.path.exists(fp), f"File missing for vid={bad_vid}: {fp}"

    def test_rename_failure_returns_fail(self, harness, store, monkeypatch):
        """Monkeypatch os.replace to throw OSError → fail_decision, no DB artifact."""

        # First monkeypatch the module-level _os reference
        import vn_core.harness as h_mod

        def _failing_replace(src, dst):
            raise OSError("simulated replace failure")

        monkeypatch.setattr(h_mod._os, "replace", _failing_replace)

        r = harness.commit_stage_result(store, StageResult(
            stage="test", book_id="b_monkey", unit_id="u1",
            proposed_artifacts=[{
                "artifact_type": "segments",
                "artifact_version_id": "b_monkey_v001",
                "unit_id": "u1",
                "data": [{"m": 1}],
                "input_hash": "mk",
            }],
            provenance={"stage": "test", "unit_id": "u1"},
        ))
        assert r.decision == GateDecision.fail_decision, r.reason
        assert "replace" in r.reason.lower()

        # DB must have no artifact
        art = store.get_active_artifact("b_monkey", "segments", "u1")
        assert art is None, f"Artifact should not exist after rollback: {art}"

    def test_commit_failure_after_replace_cleans_final(self, harness, store, monkeypatch):
        """If DB commit fails after replace, final file must be cleaned up."""
        import re as _re

        raw_db = getattr(store, "db_path", ".")
        data_dir = os.path.abspath(
            os.path.join(
                os.path.dirname(os.path.abspath(str(raw_db))), "artifact_data",
            ),
        )
        safe_name = _re.sub(r"[^a-zA-Z0-9_.-]", "_", "b_cfail2_v001") + ".json"
        final_path = os.path.abspath(os.path.join(data_dir, safe_name))

        # Cause commit failure by making the first artifact INSERT invalid
        # (supersede + insert succeeds), then a later DB op fails.
        # Simpler: monkeypatch _os.replace to succeed but cause a DB-level
        # failure by making conn.commit raise via monkeypatching the
        # _get_conn wrapper to return a connection whose commit we control.
        conn = store._get_conn()

        class _FailingConnWrapper:
            def __init__(self, real_conn):
                self._c = real_conn
            def commit(self):
                raise RuntimeError("simulated commit failure")
            def __getattr__(self, name):
                return getattr(self._c, name)

        store._conn = _FailingConnWrapper(conn)
        try:
            r = harness.commit_stage_result(store, StageResult(
                stage="test", book_id="b_cfail2", unit_id="u1",
                proposed_artifacts=[{
                    "artifact_type": "segments",
                    "artifact_version_id": "b_cfail2_v001",
                    "unit_id": "u1",
                    "data": [{"c": 1}],
                    "input_hash": "c2",
                }],
                provenance={"stage": "test", "unit_id": "u1"},
            ))
        finally:
            store._conn = conn

        assert r.decision == GateDecision.fail_decision, r.reason

        assert not os.path.exists(final_path), (
            f"Final file should be cleaned after commit failure: {final_path}"
        )
